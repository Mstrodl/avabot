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
        self.ready = False
        if self.bot.is_ready():
            self.on_ready()

    async def on_ready(self):
        if self.ready:
            return self.bot.logger.debug("Bot already ready, not initialising loop again...")

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
        newest_page_n = newest_page["number"]
        oldest_page_n = oldest_page["number"]
        oldest_page_link = oldest_page["link"]
        for guild in self.bot.guilds:
            try:
                self.bot.logger.debug(f"Announcing new page in {guild.name}")
                guild_config = await self.find_guild_config(guild)
                self.bot.logger.debug(f"Got guild config for {guild.name}")
                channel = guild.get_channel(guild_config["channel_id"])
                new_page_role = discord.utils.get(guild.roles,
                                                  id=guild_config.get("role_id")) if guild_config.get("role_id") else None
                
                self.bot.logger.debug(f"Got past role part for {guild.name}")
                
                if self.bot.prod and new_page_role: await new_page_role.edit(mentionable=True,
                                                                             reason="New page!")
                elif new_page_role: await new_page_role.edit(mentionable=False,
                                                             reason="Local bot, new page without ping")
                role_mention_str = new_page_role.mention if new_page_role else ""
                await channel.send(f"{role_mention_str} More Ava's demon pages!!\n"
                                   f"Pages {oldest_page_n}-{newest_page_n} were just released"
                                   f"({newest_page_n - oldest_page_n} pages)!\n"
                                   f"View: {oldest_page_link}")
                
                if self.bot.prod and new_page_role: await new_page_role.edit(mentionable=False,
                                                                             reason="New page!")
            except discord.DiscordException as err:
                self.bot.logger.warning(f"Discord threw an error when we announced in {guild.name}: {err}")

    @commands.group()
    @commands.guild_only()
    async def settings(self, ctx):
        """Change settings

        Change settings like where updates are posted and the role it pings (if any)
        """
        pass

    @settings.command()
    @commands.has_permissions(manage_roles=True)
    async def role(self, ctx, new_role: commands.RoleConverter = None):
        """Set role to ping on updates (can be assigned with "subscribe" command)"""
        await self.update_guild_config(ctx.guild, {
            "role_id": new_role.id if new_role else None
        })
        role_str = f"`{new_role.name}`" if new_role else "nobody"
        return await ctx.send(f"Done! I will now ping {role_str} whenever there's an update!")

    @settings.command()
    @commands.has_permissions(manage_channels=True)
    async def channel(self, ctx, new_channel: commands.TextChannelConverter):
        """Set channel to send updates to"""
        if not new_channel:
            raise MissingRequiredArgument("new_channel")

        await self.update_guild_config(ctx.guild, {
            "channel_id": new_channel.id
        })
        
        return await ctx.send(f"Done! I will now post in {new_channel.name} whenever there's an update!")

    async def update_guild_config(self, guild, new_config):
        res = await self.bot.r.table("guilds").get(str(guild.id)).run()
        if not res:
            res = {}

        return await self.bot.r.table("guilds").insert({
            "id": str(guild.id),
            "channel_id": str(new_config.get("channel_id") or res.get("channel_id")) if new_config.get("channel_id") or res.get("channel_id") else None,
            "role_id": str(new_config.get("role_id") or res.get("role_id")) if new_config.get("role_id") or res.get("role_id") else None
        }, conflict="update").run()

    async def find_guild_config(self, guild):
        self.bot.logger.debug(f"Finding guild config for {guild}")
        res = await self.bot.r.table("guilds").get(str(guild.id)).run()
        if not res:
            self.bot.logger.debug(f"No guild config for {guild.name}, generating and saving!")
            res = {
                "id": str(guild.id),
                "channel_id": 0,
                "role_id": 0
            }
            await self.bot.r.table("guilds").insert(res).run()
            self.bot.logger.debug(f"Inserted guild config for {guild.name}")
        if not res.get("channel_id") or not guild.get_channel(int(res["channel_id"])):
            self.bot.logger.debug(f"No channel for {guild.name}!")
            # This insanity chooses the top guild (based on position) we have permission to send messages in
            res["channel_id"] = sorted([chan for chan in guild.channels if isinstance(chan, discord.abc.Messageable) and chan.permissions_for(guild.me).send_messages], key=lambda channel: channel.position)[0].id
        if res.get("role_id") and not discord.utils.get(guild.roles, id=int(res["role_id"] or 0)):
            self.bot.logger.debug(f"No role for {guild.name}!")
            res["role_id"] = None

        self.bot.logger.debug(f"Response created for {guild.name}")

        return {
            "id": guild.id,
            "channel_id": int(res.get("channel_id")),
            "role_id": int(res.get("role_id")) if res.get("role_id") else None
        }

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
