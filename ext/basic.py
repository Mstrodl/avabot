from .common import Cog
from discord.ext import commands
import time

class Basic(Cog):
    """Basic commands"""

    @commands.command()
    async def ping(self, ctx):
        """Get's latency to Discord's API"""
        t1 = time.monotonic()
        m = await ctx.send("Pong!")
        t2 = time.monotonic()
        rtt = (t2 - t1) * 1000
        ws = self.bot.latency * 1000
        await m.edit(content=f"Pong! rtt: `{rtt:.1f}ms`, gateway: `{ws:.1f}ms`")

def setup(bot):
    bot.add_cog(Basic(bot))
