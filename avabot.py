from discord.ext import commands
import avaconfig as cfg
import rethinkdb as r
import aiohttp

cog_list = [
    "admin",
    "basic",
    "avascrape"
]

class AvaBot(commands.Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.config = cfg 

        for cog_name in cog_list:
            try:
                print(f"Loading {cog_name}")
                self.load_extension(f"ext.{cog_name}")
            except Exception as err:
                print(f"Failed to load {cog_name}!!11!!11!!!11")

        # We only need to connect to rethink once...
        self.r = r
        self.r.connect("localhost", 28015, "ava").repl()

ava = AvaBot(
    command_prefix="a!",
    description="A bot that scrapes avasdemon.com for updates and announces them to people opted in!",
    pm_help=None
)

print("oof!")
ava.run(cfg.token)
