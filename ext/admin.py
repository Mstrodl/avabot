"""
Handy exec (eval, debug) cog. Allows you to run code on the bot during runtime. This cog
is a combination of the exec commands of other bot authors:

Credit:
    - Rapptz (Danny)
        - https://github.com/Rapptz/RoboDanny/blob/master/cogs/repl.py#L31-L75
    - b1naryth1ef (B1nzy, Andrei)
        - https://github.com/b1naryth1ef/b1nb0t/blob/master/plugins/util.py#L220-L257

Features:
    - Strips code markup (code blocks, inline code markup)
    - Access to last result with _
    - _get and _find instantly available without having to import discord
    - Redirects stdout so you can print()
    - Sane syntax error reporting
    - Quickly retry evaluations
"""

import io
import os
import logging
import textwrap
import traceback
import asyncio
import inspect
from contextlib import redirect_stdout

import aiohttp
import discord
from discord.ext import commands

from .common import Cog, hastebin

log = logging.getLogger(__name__)


def strip_code_markup(content: str) -> str:
    """ Strips code markup from a string. """
    # ```py
    # code
    # ```
    if content.startswith("```") and content.endswith("```"):
        # grab the lines in the middle
        return "\n".join(content.split("\n")[1:-1])

    # `code`
    return content.strip("` \n")


async def run_subprocess(cmd: str) -> str:
    """Runs a subprocess and returns the output."""
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    results = await process.communicate()
    return "".join(x.decode("utf-8") for x in results)


def format_syntax_error(e: SyntaxError) -> str:
    """ Formats a SyntaxError. """
    if e.text is None:
        return "```py\n{0.__class__.__name__}: {0}\n```".format(e)
    # display a nice arrow
    return "```py\n{0.text}{1:>{0.offset}}\n{2}: {0}```".format(
        e, "^", type(e).__name__)


class Admin(Cog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.sessions = set()
        self.last_result = None
        self.previous_code = None

    # TODO: replace with new eval from slice
    async def execute(self, ctx, code):
        log.info("Eval: %s", code)

        async def upload(file_name: str):
            with open(file_name, "rb") as fp:
                await ctx.send(file=discord.File(fp))

        async def send(*args, **kwargs):
            await ctx.send(*args, **kwargs)

        env = {
            "bot": ctx.bot,
            "ctx": ctx,
            "msg": ctx.message,
            "guild": ctx.guild,
            "channel": ctx.channel,
            "me": ctx.message.author,

            # modules
            "discord": discord,
            "commands": commands,

            # utilities
            "_get": discord.utils.get,
            "_find": discord.utils.find,
            "_upload": upload,
            "_send": send,

            # last result
            "_": self.last_result,
            "_p": self.previous_code
        }
        env.update(globals())

        # simulated stdout
        stdout = io.StringIO()

        # wrap the code in a function, so that we can use await
        wrapped_code = "async def func():\n" + textwrap.indent(code, "    ")

        # define the wrapped function
        try:
            exec(compile(wrapped_code, "<exec>", "exec"), env)
        except SyntaxError as e:
            return await ctx.send(format_syntax_error(e))

        func = env["func"]
        try:
            # execute the code
            with redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            # something went wrong
            try:
                await ctx.message.add_reaction("\N{EXCLAMATION QUESTION MARK}")
            except BaseException:
                pass
            stream = stdout.getvalue()
            await ctx.send("```py\n{}{}\n```".format(stream, traceback.format_exc()))
        else:
            # successful
            stream = stdout.getvalue()

            try:
                await ctx.message.add_reaction("\N{HUNDRED POINTS SYMBOL}")
            except BaseException:
                # couldn"t add the reaction, ignore
                log.warning(
                    "Failed to add reaction to eval message, ignoring.")

            try:
                self.last_result = self.last_result if ret is None else ret
                await ctx.send("```py\n{}{}\n```".format(stream, repr(ret)))
            except discord.HTTPException:
                # too long
                try:
                    url = await hastebin(ctx.bot.session, stream + repr(ret))
                    await ctx.send(f"hastebin: {url}")
                except aiohttp.ClientError:
                    await ctx.send("oof")

    @commands.command(hidden=True)
    async def repl(self, ctx):
        """Launches an interactive REPL session."""
        variables = {
            "ctx": ctx,
            "bot": self.bot,
            "message": ctx.message,
            "guild": ctx.guild,
            "channel": ctx.channel,
            "author": ctx.author,
            "pool": self.bot.pool,
            "_": None,
        }

        if ctx.channel.id in self.sessions:
            await ctx.send("Already running a REPL session in this channel. Exit it with `quit`.")
            return

        self.sessions.add(ctx.channel.id)
        await ctx.send("Enter code to execute or evaluate. `exit()` or `quit` to exit.")

        def check(m):
            return m.author.id == ctx.author.id and \
                m.channel.id == ctx.channel.id and \
                m.content.startswith("`")

        while True:
            try:
                response = await self.bot.wait_for("message", check=check, timeout=10.0 * 60.0)
            except asyncio.TimeoutError:
                await ctx.send("Exiting REPL session.")
                self.sessions.remove(ctx.channel.id)
                break

            cleaned = strip_code_markup(response.content)

            if cleaned in ("quit", "exit", "exit()"):
                await ctx.send("Exiting.")
                self.sessions.remove(ctx.channel.id)
                return

            executor = exec
            if cleaned.count("\n") == 0:
                # single statement, potentially "eval"
                try:
                    code = compile(cleaned, "<repl session>", "eval")
                except SyntaxError:
                    pass
                else:
                    executor = eval

            if executor is exec:
                try:
                    code = compile(cleaned, "<repl session>", "exec")
                except SyntaxError as e:
                    await ctx.send(format_syntax_error(e))
                    continue

            variables["message"] = response

            fmt = None
            stdout = io.StringIO()

            try:
                with redirect_stdout(stdout):
                    result = executor(code, variables)
                    if inspect.isawaitable(result):
                        result = await result
            except Exception as e:
                value = stdout.getvalue()
                fmt = f"```py\n{value}{traceback.format_exc()}\n```"
            else:
                value = stdout.getvalue()
                if result is not None:
                    fmt = f"```py\n{value}{result}\n```"
                    variables["_"] = result
                elif value:
                    fmt = f"```py\n{value}\n```"

            try:
                if fmt is not None:
                    if len(fmt) > 2000:
                        await ctx.send("Content too big to be printed.")
                    else:
                        await ctx.send(fmt)
            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                await ctx.send(f"Unexpected error: `{e}`")

    @commands.command(name="sh", aliases=["bash", "exec"])
    @commands.is_owner()
    async def shell(self, ctx, *, cmd):
        """Run a subprocess using shell."""
        async with ctx.typing():
            result = await run_subprocess(cmd)
        await ctx.send(f"```{result}```")

    @commands.command()
    @commands.is_owner()
    async def download(self, ctx, file):
        """Attaches a stored file"""
        with open(file, "rb") as f:
            try:
                await ctx.send(file=discord.File(f, file))
            except FileNotFoundError:
                await ctx.send(f"no such file: {file}")

    @commands.command()
    @commands.is_owner()
    async def upload(self, ctx):
        """Upload a file"""
        attachments = ctx.message.attachments

        if not attachments:
            await ctx.send("No attachment found! Please upload it in your next message.")

            def check(msg_: discord.Message) -> bool:
                return msg_.channel.id == ctx.channel.id and msg_.author.id == ctx.author.id and msg_.attachments

            try:
                msg = await self.bot.wait_for("message", check=check, timeout=60 * 10)
            except asyncio.TimeoutError:
                return await ctx.send("Stopped waiting for file upload, 10 minutes have passed.")

            attachments = msg.attachments

        for attachment in attachments:
            with open(attachment.filename, "wb") as f:
                attachment.save(f)
            await ctx.send(f"saved as {attachment.filename}")

    @commands.command(alias=["shutdown", "off", "poweroff"])
    @commands.is_owner()
    async def die(self, ctx):
        """Shuts down the bot safely"""
        await ctx.send("oof.")
        await self.bot.r_connection.close()
        await self.bot.session.close()
        for ext in list(self.bot.extensions):
            print(ext)
            self.bot.unload_extension(ext)
        await ctx.bot.logout()

    @commands.command()
    @commands.is_owner()
    async def load(self, ctx, cog):
        """loads a extension."""
        try:
            self.bot.load_extension(f"ext.{cog}")
        except Exception as e:
            await ctx.send(f"**`ERROR:`** ```py\n{traceback.format_exc()}\n``` - {e}")
        else:
            await ctx.send("**`SUCCESS`**")

    @commands.command()
    @commands.is_owner()
    async def unload(self, ctx, cog):
        """unloads a extension."""
        try:
            self.bot.unload_extension(f"ext.{cog}")
        except Exception as e:
            await ctx.send(f"**`ERROR:`** ```py\n{traceback.format_exc()}\n``` - {e}")
        else:
            await ctx.send("**`SUCCESS`**")

    @commands.command(name="reload")
    @commands.is_owner()
    async def cog_reload(self, ctx, *, cog: str):
        """Command which Reloads an extension."""
        if cog == "admin":
            await ctx.send("bad idea.")
            return
        try:
            self.bot.unload_extension(f"ext.{cog}")
            self.bot.load_extension(f"ext.{cog}")
        except Exception as e:
            await ctx.send(f"**`ERROR:`** ```py\n{traceback.format_exc()}\n``` - {e}")
        else:
            await ctx.send("**`SUCCESS`**")


def setup(bot):
    bot.add_cog(Admin(bot))
