import logging
import os
import asyncio
import time
import traceback

import aiohttp
import rethinkdb as r
import discord
from discord.ext import commands

import avaconfig as cfg

cog_list = [
    "admin",
    "basic",
    "modular",
    "exec"
]

class AvaBot(commands.Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prod = True if os.environ.get("pm_id") else False
        logging.basicConfig(format="[%(levelname)s] - %(message)s", level=logging.INFO if self.prod else logging.DEBUG)
        self.logger = logging.getLogger("avabot")
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.start_time = int(round(time.time() * 1000))
        self.uptime = lambda: int(round(time.time() * 1000) - self.start_time)

        # We only need to connect to rethink once...
        self.r = r
        self.r.set_loop_type("asyncio")
        self.r_connection = self.loop.create_task(self._db_connect())

        for cog_name in cog_list:
            try:
                print(f"Loading {cog_name}")
                self.load_extension(f"ext.{cog_name}")
            except Exception as err:
                print(err)
                self.logger.error(f"Failed to load {cog_name}!!11!!11!!!11")

    async def _db_connect(self):
        conn = await self.r.connect("localhost", 28015, "ava")
        conn.repl()
        self.r_connection = conn

    async def on_command_error(self, ctx, ex):
        # dog bot good go use it for things https://github.com/slice/dogbot
        if getattr(ex, "should_suppress", False):
            self.logger.debug("Suppressing exception: %s", ex)
            return

        see_help = f"pls see `{ctx.prefix}help {ctx.command.qualified_name}`" if ctx.command else\
            "look at help bitch"

        if isinstance(ex, commands.errors.BadArgument):
            message = str(ex)
            if not message.endswith("."):
                message = message + "."
            await ctx.send(f"fix ur args: {message}, {see_help}")
        elif isinstance(ex, commands.errors.MissingRequiredArgument):
            await ctx.send(f"missing arg: {ex} {see_help}")
        elif isinstance(ex, commands.NoPrivateMessage):
            await ctx.send("no dms")
        elif isinstance(ex, commands.errors.DisabledCommand):
            await ctx.send("command is disabled")
        elif isinstance(ex, asyncio.TimeoutError):
            await ctx.send("timed out")
        elif isinstance(ex, commands.errors.CommandInvokeError):
            if isinstance(ex.original, discord.Forbidden):
                if ctx.command.name == "help":
                    # can"t dm that person :(
                    try:
                        await ctx.send(f"i cant dm {ctx.author.mention}")
                    except discord.Forbidden:
                        pass
                    return
                return await self.handle_forbidden(ctx)

            # get the traceback
            tb = "".join(traceback.format_exception(type(ex.original), ex.original, ex.original.__traceback__))

            # form a good human-readable message
            header = f"Command error: {type(ex.original).__name__}: {ex.original}"
            message = header + "\n" + str(tb)

            await ctx.send(f"oof ```py\n{tb}\n```")

            self.dispatch("uncaught_command_invoke_error", ex.original, (message, tb, ctx))
            self.logger.error(message)
           
ava = AvaBot(
    command_prefix="av!" if os.environ.get("pm_id") else "wr!",
    description="A bot that scrapes various webcomics for updates and announces them to people opted in!",
    pm_help=None
)

print("oof!")
ava.run(cfg.token)
