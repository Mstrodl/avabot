import asyncio
import urllib.parse as urlparse

import discord
import aiohttp
import lxml.html
import lxml.etree
from discord.ext import commands

import avaconfig as cfg
from .common import Cog

class AvaRSS(Cog):
    """Updates users when new Ava's Demon pages are released"""

    def __init__(self, bot):
        super().__init__(bot)
        self.file_handle = open("latest_page.txt", "r+")
        self.last_known_page = int(self.file_handle.read()) or 0
        self.reencode_parser = lxml.etree.XMLParser(encoding="utf-8")
        self.check_loop = None

    async def on_ready(self):
        self.bot.logger.info("Bot ready!")
        async def run_check():
            while True:
                self.bot.logger.info("Checking RSS automatically...")
                await self.check_rss()
                await asyncio.sleep(5 * 60) # Check RSS every 5 min
        self.check_loop = self.bot.loop.create_task(run_check())

    async def check_rss(self):
        self.bot.logger.info("Downloading RSS feed")
        async with self.bot.session.get("http://feeds.feedburner.com/AvasDemon?format=xml") as resp:
            original_text = await resp.text()
            if resp.status == 200:
                self.bot.logger.info("Downloaded RSS feed successfully!")
                # Ugh, we have to re-encode it because they have an encoding declaration... See: http://lxml.de/parsing.html#python-unicode-strings
                text_reencoded = original_text.encode("utf-8")
                parsed = lxml.etree.fromstring(text_reencoded, parser=self.reencode_parser)
                links = parsed.cssselect("rss channel item link")
                # This looks confusing, but what we do here is like map() but that might be removed at some point?
                pages = [{
                    "number": self.parse_number(page_link.text),
                    "link": page_link.text
                } for page_link in links]

                if pages[0]["number"] == self.last_known_page:
                    self.bot.logger.info("No new pages")
                else:
                    self.bot.logger.info("Found a new page!")
                    new_pages = [page for page in pages if page["number"] > self.last_known_page]
                    await self.announce_pages(new_pages[-1], new_pages[0])
                    self.last_known_page = pages[0]["number"]
            else:
                raise RSSException(original_text)

    async def announce_pages(self, oldest_page, newest_page):
        """Alerts the users of a new page!"""
        channel = self.bot.get_channel(cfg.alert_channel)
        newest_page_n = newest_page["number"]
        oldest_page_n = oldest_page["number"]
        oldest_page_link = oldest_page["link"]
        new_page_role = discord.utils.get(channel.guild.roles,
                                          id=cfg.new_page_role)

        if self.bot.prod: await new_page_role.edit(mentionable=True,
                                                   reason="New page!")
        else: await new_page_role.edit(mentionable=False,
                                       reason="Local bot, new page without ping")
        
        await channel.send(f"{new_page_role.mention} Henlo bitches! More Ava's demon pages!!1111!!!11!!!\n"
                           f"Pages {oldest_page_n}-{newest_page_n} were just released"
                           f"({newest_page_n - oldest_page_n} pages)!\n"
                           f"View: {oldest_page_link}")
        
        if self.bot.prod: await new_page_role.edit(mentionable=False,
                                                   reason="New page!")

    @commands.command()
    @commands.is_owner()
    async def force_recheck(self, ctx):
        await self.check_rss()
        await ctx.send("Done")

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

    def parse_number(self, link):
        parsed_link = urlparse.urlparse(link)
        page_number = urlparse.parse_qs(parsed_link.query)["page"][0]
        return int(page_number)

    def __unload(self):
        self.check_loop.cancel()
        self.file_handle.seek(0)
        self.file_handle.write(str(self.last_known_page))
        self.file_handle.truncate()
        self.file_handle.close()


def setup(bot):
    bot.add_cog(AvaRSS(bot))
