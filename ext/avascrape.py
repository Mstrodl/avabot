from .common import Cog
from discord.ext import commands
from lxml import html
import aiohttp
import urllib.parse as parse
import avaconfig as cfg
import time
from datetime import datetime
import threading
import asyncio
import discord
from concurrent.futures import ProcessPoolExecutor

class AvaScrape(Cog):
    """Commands used to control the scraper"""

    def __init__(self, bot):
        super().__init__(bot)
        self.scrape_days = [0, 1]
        self.ready = False

    async def on_ready(self):
        if self.ready:
            return False
        self.ready = True
        while True:
            if datetime.today().weekday() in self.scrape_days:
                await self.scrape()
                await asyncio.sleep(3600)

    async def looper(self, func, delay):
        while True:
            await func(self)
            await asyncio.sleep(delay)

    @commands.command(alises=["scrape", "scr"])
    @commands.is_owner()
    async def forcescrape(self, ctx):
        """Forces another scrape"""
        await self.scrape()
        await ctx.send("Scraped!")

    async def scrape(self):
        """Scrapes avasdemon.com for new content"""
        db_res = await self.bot.loop.run_in_executor(ProcessPoolExecutor(), self.bot.r.table("data").get("lastpage").run)
        if not db_res:
            last_known_page = 0
        else:
            last_known_page = db_res["value"]
        # We have to pass in extra headers otherwise we get served a tiny version without the data we need D:
        res = await self.request("http://www.avasdemon.com/pages.php", {
            "Origin": "http://www.avasdemon.com",
            "Referer": "http://www.avasdemon.com/pages.php",
            "Content-Type": "application/x-www-form-urlencoded"
        }, "page=0001")
        parsed = html.fromstring(res)
        # Select the latest page link
        latestUrl = parsed.cssselect("img[src=\"latest.png\"]")[0].getparent().attrib["href"]
        # Parse out the page id from the url's query parameter
        latest_page = int(parse.parse_qs(parse.urlparse(latestUrl).query)["page"][0])
        # If this is the same page we had before,
        if latest_page == last_known_page:
            return False
        else:
            # Otherwise, there's a new page! Alert those that are subscribed! :D
            await self.alert_users(last_known_page + 1, latest_page)
            # Asyncio is annoying so we need this
            await self.bot.loop.run_in_executor(ProcessPoolExecutor(), self.bot.r.table("data").update({
                "id": "lastpage",
                "value": latest_page
            }).run)
            return latest_page

    async def alert_users(self, first_new_page, last_new_page):
        """Alerts the users of a new page!"""
        channel = self.bot.get_channel(cfg.alert_channel)
        new_page_role = discord.utils.get(channel.guild.roles, id=cfg.new_page_role)
        await new_page_role.edit(mentionable=True,
                                 reason="New page!")
        await channel.send(f"{new_page_role.mention} Henlo bitches! More Ava's demon pages!!1111!!!11!!!\n"
                           f"Pages {first_new_page}-{last_new_page} were just released"
                           f"({last_new_page - first_new_page} pages)!\n"
                           f"View: http://www.avasdemon.com/pages.php?page={str(first_new_page).zfill(4)}")
        await new_page_role.edit(mentionable=False,
                                 reason="New page!")

    async def request(self, url, headers, data):
        """Wrapper to make a request since it's stupid big"""
        async with self.bot.session.post(url, headers=headers, data=data) as response:
            return await response.text()

    @commands.command(aliases=["unsubscribe", "unsub", "sub"])
    async def subscribe(self, ctx):
        """Subscribes/Unsubscribes from page updates"""
        channel = self.bot.get_channel(cfg.alert_channel)
        new_page_role = discord.utils.get(channel.guild.roles, id=cfg.new_page_role)

        if not new_page_role in ctx.author.roles:
            await ctx.author.add_roles(new_page_role, reason="Subscribed to page updates", atomic=True)
            subscribed = True
        else:
            await ctx.author.remove_roles(new_page_role, reason="Unsubscribed from page updates", atomic=True)
            subscribed = False

        action_message = "Subscribed to" if subscribed else "Unsubscribed from"
        return await ctx.send(f"{action_message} page updates!")

def setup(bot):
    bot.add_cog(AvaScrape(bot))
