#!/usr/bin/env python3

import logging
import os
import asyncio
import time
import traceback

import aiohttp
from rethinkdb import RethinkDB
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
    self.config = cfg

    logging.basicConfig(
      format="[%(levelname)s] - %(message)s",
      level=logging.INFO if os.environ.get("LOG_INFO") else (
        logging.INFO if self.prod else logging.DEBUG))
    self.logger = logging.getLogger("avabot")
    self.session = aiohttp.ClientSession(loop=self.loop)
    self.start_time = int(round(time.time() * 1000))
    self.uptime = lambda: int(round(time.time() * 1000) - self.start_time)
    self.public_dev = False

    # We only need to connect to rethink once...
    self.r = RethinkDB()
    self.r.set_loop_type("asyncio")
    self.db_connect_task = self.loop.create_task(self._db_connect())

    for cog_name in cog_list:
      try:
        self.logger.info(f"Loading {cog_name}")
        self.load_extension(f"ext.{cog_name}")
      except Exception as err:
        self.logger.error(f"Failed to load {cog_name}!! {err}")

  async def _db_connect(self):
    conn = await self.r.connect("localhost", 28015, "ava")
    conn.repl()
    self.r_connection = conn
    return conn

  async def on_message(self, message):
    if not self.prod and not await self.is_owner(message.author) and not self.public_dev:
      return 
    ctx = await self.get_context(message)
    await self.invoke(ctx)


  async def on_command_error(self, ctx, error):
    # Borrowed from Ave's rolebot:
    # https://gitlab.com/aoz/rolebot/blob/5376333bd13560cda09cbebe17b2aec09b5b9c99/rolebot.py#L80-111
    
    self.logger.error(f"Error with \"{ctx.message.content}\" from \"{ctx.message.author}\" "
                      f"({ctx.message.author.id}) of type {type(error)}: {error}")
    
    if isinstance(error, commands.NoPrivateMessage):
      return await ctx.send("This command doesn't work on DMs.")
    elif isinstance(error, commands.MissingPermissions):
      roles_needed = '\n- '.join(error.missing_perms)
      return await ctx.send(f"{ctx.author.mention}: You don't have the right"
                            " permissions to run this command. You need: "
                            f"```- {roles_needed}```")
    elif isinstance(error, commands.BotMissingPermissions):
      roles_needed = '\n-'.join(error.missing_perms)
      return await ctx.send(f"{ctx.author.mention}: Bot doesn't have "
                            "the right permissions to run this command. "
                            "Please add the following roles: "
                            f"```- {roles_needed}```")
    elif isinstance(error, commands.CommandOnCooldown):
      return await ctx.send(f"{ctx.author.mention}: You're being "
                            "ratelimited. Try in "
                            f"{error.retry_after:.1f} seconds.")
  
    help_text = f"Usage of this command is: ```{ctx.prefix}"\
                f"{ctx.command.signature}```\nPlease see `{ctx.prefix}help "\
                f"{ctx.command.name}` for more info about this command."
    if isinstance(error, commands.BadArgument):
      return await ctx.send(f"{ctx.author.mention}: You gave incorrect "
                            f"arguments. {help_text}")
    elif isinstance(error, commands.MissingRequiredArgument):
      return await ctx.send(f"{ctx.author.mention}: You gave incomplete "
                            f"arguments. {help_text}")
    elif isinstance(error, commands.errors.CommandInvokeError):
      if isinstance(error.original, discord.Forbidden):
        if ctx.command.name == "help":
          # can"t dm that person :(
          try:
            await ctx.send(f"i cant dm {ctx.author.mention}")
          except discord.Forbidden:
            pass
          return
        return await self.handle_forbidden(ctx)

      # get the traceback
      tb = "".join(
        traceback.format_exception(
          type(
            error.original),
          error.original,
          error.original.__traceback__))

      # form a good human-readable message
      header = f"Command error: {type(error.original).__name__}: {error.original}"
      message = header + "\n" + str(tb)

      await ctx.send(f"oof ```py\n{tb}\n```")

      self.dispatch("uncaught_command_invoke_error",
              error.original, (message, tb, ctx))
      self.logger.error(message)
      return

ava = AvaBot(
  command_prefix="av!" if os.environ.get("pm_id") else "wr!",
  description="A bot that scrapes various webcomics for updates and announces them to people opted in!",
  pm_help=None)

ava.run(cfg.token)
