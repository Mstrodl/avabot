import logging
import os

import aiohttp
import rethinkdb as r
from discord.ext import commands

import avaconfig as cfg

cog_list = [
    "admin",
    "basic",
    "avascrape"
]

class AvaBot(commands.Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logger = logging.getLogger("avabot")
        self.session = aiohttp.ClientSession(loop=self.loop)

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
                logging.error(f"Failed to load {cog_name}!!11!!11!!!11")

    async def _db_connect(self):
        conn = await self.r.connect("localhost", 28015, "ava")
        conn.repl()
        self.r_connection = conn
        
ava = AvaBot(
    command_prefix="av!" if os.environ.get("pm_id") else "wr!",
    description="A bot that scrapes avasdemon.com for updates and announces them to people opted in!",
    pm_help=None
)

print("oof!")
ava.run(cfg.token)
