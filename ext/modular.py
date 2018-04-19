# https://killsixbilliondemons.com/feed/
# http://twokinds.keenspot.com/feed.xml
# http://mylifewithfel.smackjeeves.com/rss/


import asyncio
import json
import re
import os

import discord
import aiohttp
import lxml.html
import rethinkdb as r
import dateutil.parser
import datetime
import lxml.etree
import lxml.html
import urllib.parse
from discord.ext import commands

from .common import Cog

page_num_regex = r"((?:-|\d){3,5})"  # Used to match page #s in RSS feed titles
parser = lxml.etree.XMLParser(encoding="utf-8")
html_parser = lxml.html.HTMLParser(encoding="utf-8")


class BadPage(Exception):
  pass

async def http_req(url, headers={}, body=None):
  async with aiohttp.ClientSession() as session:
    chosen_req = session.post if body else session.get
    async with chosen_req(url, headers=headers, data=body) as resp:
      return {
        "text": await resp.text(),
        "resp": resp
      }


async def common_rss(comic):
  resp = await http_req(comic["rss_url"])
  text = resp["text"]

  if resp["resp"].status == 200:
    text_reencoded = text.encode("utf-8")
    parsed = lxml.etree.fromstring(text_reencoded, parser=parser)
    post = parsed.cssselect("rss channel item")[0]
    title = post.cssselect("title")[0].text
    url = post.cssselect("link")[0].text
    page_num_search = re.search(page_num_regex, title)
    if not page_num_search:
      raise BadPage(f"No unique ID found for page title: '{title}'")
    page_num = page_num_search.group(1)
    found_pubdate = post.cssselect("pubDate")
    if found_pubdate:
      time = dateutil.parser.parse(found_pubdate[0].text)
    else:
      time = r.now()
    return {
      "latest_post": {
        "unique_id": page_num,
        "url": url,
        "title": title,
        "time": time
      }
    }


async def twokinds_scrape(comic):
  resp = await http_req(comic["base_url"])
  text = resp["text"]
  text_reencoded = text.encode("utf-8")
  xml_document = lxml.html.fromstring(text_reencoded, parser=html_parser)
  # Grab the newest page from the 'latest' button
  article_obj = xml_document.cssselect("article.comic")[0]
  permalink_page = article_obj.cssselect("div.below-nav p.permalink a")[0]
  permalink_url = permalink_page.attrib["href"]
  title = article_obj.cssselect("img[alt=\"Comic Page\"]")[0].attrib["title"]
  try:
    page_num = int(os.path.basename(os.path.split(permalink_url)[0]))
  except ValueError as err:
    raise BadPage(f"No unique ID found for page title: '{title}'")
  
  return {
    "latest_post": {
      "unique_id": page_num,
      "url": f'{comic["base_url"]}{permalink_url}',
      "title": title,
      "time": r.now()
    }
  }

# Ava's Demon scraper because the she doesn't update RSS as soon...
async def avasdemon_scrape(comic):
  resp = await http_req(f'{comic["base_url"]}/pages.php', {
    "Origin": comic["base_url"],
    "Referer": f'{comic["base_url"]}/pages.php',
    "Content-Type": "application/x-www-form-urlencoded"
  }, "page=0001")
  text = resp["text"]
  xml_document = lxml.html.fromstring(text)
  # Grab the newest page from the 'latest' button
  latest_url = xml_document.cssselect("img[src=\"latest.png\"]")[0] \
                           .getparent().attrib["href"]
  
  query_params = urllib.parse.parse_qs(urllib.parse.urlparse(latest_url).query)
  page_num = query_params["page"][0]
  return {
    "latest_post": {
      "unique_id": page_num,
      "url": f'{comic["base_url"]}/{latest_url}',
      "title": f"Page {page_num}",
      "time": r.now()
    }
  }


async def xkcd_fetch(comic):
  resp = await http_req(f'{comic["base_url"]}/info.0.json')
  text = resp["text"]
  page = json.loads(text)
  return {
    "latest_post": {
      "unique_id": page["num"],
      "url": f'{comic["base_url"]}/{page["num"]}',
      "title": f'{page["title"]} ({page["alt"]}',
      "time": r.time(int(page["year"]), int(page["month"]), int(page["day"]), "Z")
    }
  }


async def twitter_listener(user):
  handle = comic["handle"] # User's Twitter handle
  

webcomics = [
  {
    "slug": "twokinds",
    "friendly": "Two Kinds",
    "check_updates": twokinds_scrape,
    "base_url": "http://twokinds.keenspot.com"
  },
  {
    "base_url": "http://avasdemon.com",
    "friendly": "Ava's Demon",
    "check_updates": avasdemon_scrape,
    "slug": "avasdemon"
  },
  {
    "base_url": "https://xkcd.com",
    "friendly": "XKCD",
    "check_updates": xkcd_fetch,
    "slug": "xkcd"
  },
  {
    "slug": "mylifewithfel",
    "friendly": "My Life With Fel",
    "check_updates": common_rss,
    "rss_url": "http://mylifewithfel.smackjeeves.com/rss/"
  },
  {
    "slug": "killsixbilliondemons",
    "friendly": "Kill Six Billion Demons",
    "check_updates": common_rss,
    "rss_url": "https://killsixbilliondemons.com/feed/"
  } # ,
  # {
  #   "slug": "avasdemon",
  #   "friendly": "Ava's Demon",
  #   "check_updates": common_rss,
  #   "rss_url": "http://feeds.feedburner.com/AvasDemon?format=xml"
  # }
]


class Modular(Cog):
  """Updates users when new webcomics are released!"""

  def __init__(self, bot):
    super().__init__(bot)
    self.ready = False
    if self.bot.is_ready():
      self.check_updates()
    # We cache this because we're intellectuals who want efficiency
    self.comic_slugs = [comic["slug"] for comic in webcomics]
    self.comic_dict = {}
    for comic in webcomics:
      self.comic_dict[comic["slug"]] = comic

    async def run_check():
      await self.bot.db_connect_task
      while True:
        self.bot.logger.info("Checking RSS automatically...")
        await self.check_updates()
        await asyncio.sleep(5 * 60)  # Check RSS every 5 min
    self.check_loop = self.bot.loop.create_task(run_check())

  def __unload(self):
    self.check_loop.cancel()

  async def check_updates(self):
    for comic in webcomics:
      # haha yes we have the comics now we do their update hook!
      friendly_name = comic["friendly"]
      self.bot.logger.info(f"Fetching {friendly_name}")
      try:
        results = await comic["check_updates"](comic)
      except aiohttp.client_exceptions.ClientConnectionError as err:
        self.bot.logger.error(f"Error occurred while fetching {friendly_name}: {err}")
        continue
      except BadPage as err:
        self.bot.logger.error(f"Error occurred while fetching {friendly_name}: {err}")
        continue

      self.bot.logger.info(f"Checked for updates on {friendly_name}")
      announced_post = await self.bot.r.table("updates").get(comic["slug"]).run()

      if announced_post and results["latest_post"]["unique_id"] == announced_post["unique_id"]:
        self.bot.logger.info(f"No updates for {friendly_name}")
        continue
      self.bot.logger.info(f'Found update for {friendly_name}, unique_id: {results["latest_post"]["unique_id"]}')

      await self.bot.r.table("updates").insert({
        "id": comic["slug"],
        "unique_id": results["latest_post"]["unique_id"],
        "url": results["latest_post"]["url"],
        "title": results["latest_post"]["title"],
        "time": results["latest_post"]["time"]
      }, conflict="update").run()
      await self.announce_comic(comic, results)

  async def announce_comic(self, comic, results):
    channels = await self.get_channels(comic["slug"])
    friendly_name = comic["friendly"]
    post_title = results["latest_post"]["title"]
    url = results["latest_post"]["url"]
    response = f"New panels for {friendly_name}! Latest panel:\n*{post_title}*\n<{url}>"

    for channel in channels:
      if channel["role"]:
        new_page_role = channel["role"]
        try:
          if self.bot.prod:
            await new_page_role.edit(
              mentionable=True,
              reason=f"New panels for {friendly_name} ({post_title})")
          else:  # Safety precaution
            await new_page_role.edit(
              mentionable=False,
              reason="Local bot, new page without ping")
        except discord.Forbidden:
          pass

        try:
          await channel["channel"].send(channel["role"].mention + ": " + response)
        except discord.Forbidden:
          pass

        try:
          await new_page_role.edit(
            mentionable=False,
            reason=f"New panels for {friendly_name} ({post_title})")
        except discord.Forbidden:
          pass
      else:
        await channel["channel"].send(response)

  async def get_channels(self, comic_slug):
    subscriptions = await self.bot.r.table("subscriptions").get_all(comic_slug, index="slug").run()
    return [{
      "channel": self.bot.get_channel(int(subscription["channel_id"])),
      "role": (discord.utils.get(
        self.bot.get_channel(int(subscription["channel_id"])).guild.roles,
        id=int(subscription["role_id"])) if subscription["role_id"] else None) or None
    } async for subscription in subscriptions
      if self.bot.get_channel(int(subscription["channel_id"]))]

  @commands.command(aliases=["unsubscribe", "unsub", "sub"])
  async def subscribe(self, ctx, *, role: discord.Role=None):
    """Toggles your subscription to a webcomic"""
    if not role:
      subscriptions = self.bot.r \
      .table("subscriptions") \
      .get_all(str(ctx.guild.id), index="guild_id").run()

      role_list = "\n".join([
        f'{self.bot.get_channel(int(subscription["channel_id"])).mention} '
        f'**{self.comic_dict[subscription["slug"]]["friendly"]}**: '
        f'`{discord.utils.get(ctx.guild.roles, id=int(subscription["role_id"])).name}`'
        async for subscription in subscriptions 
        if subscription["role_id"] and
        discord.utils.get(ctx.guild.roles,
                  id=int(subscription["role_id"]))
      ])
      return await ctx.send(f"Available roles:\n"
                  f"{role_list}")

    if role.guild.id != ctx.guild.id:
      return await ctx.send("Role not found")

    allowed = await self.bot.r \
      .table("subscriptions") \
      .get_all(str(role.id), index="role_id") \
      .count() \
      .gt(0) \
      .run()

    if not allowed:
      return await ctx.send("Role not found")

    if role in ctx.author.roles:
      await ctx.author.remove_roles(role)
      return await ctx.send("Unsubscribed!")
    else:
      await ctx.author.add_roles(role)
      return await ctx.send("Subscribed!")

  @commands.group(invoke_without_command=True)
  async def subscriptions(self, ctx):
    """Manage subscriptions"""
    return await ctx.invoke(self.bot.get_command("help"), ctx.invoked_with)

  @subscriptions.command(name="list")
  async def subscriptions_list(self, ctx, channel: discord.TextChannel=None):
    """Shows a list of subscriptions in the server (Or just the channel specified"""
    filter_dict = {
      "guild_id": str(ctx.guild.id)
    }
    if channel:
      filter_dict["channel_id"] = str(channel.id)
      header = f"Subscriptions in {channel.mention}"
    else:
      header = "Subscriptions in this server"

    subscriptions = await self.bot.r \
      .table("subscriptions") \
      .filter(filter_dict) \
      .run()
    subscription_list = "\n".join([f'**{self.comic_dict[subscription["slug"]]["friendly"]}** {self.bot.get_channel(int(subscription["channel_id"])).mention}' +
                     ((" " +
                     discord.utils.get(
                       self.bot.get_channel(int(subscription["channel_id"])).guild.roles,
                       id=int(subscription["role_id"])).name)
                    if subscription["role_id"] and discord.utils.get(
                       self.bot.get_channel(int(subscription["channel_id"])).guild.roles,
                       id=int(subscription["role_id"])) else "")
                     async for subscription in subscriptions if self.bot.get_channel(int(subscription["channel_id"]))])

    await ctx.send(f"**{header}**\n"
             f"{subscription_list}")

  @subscriptions.command()
  @commands.has_permissions(administrator=True)
  async def remove(self, ctx, slug: str, channel: discord.TextChannel):
    """Removes subscription for a channel."""
    if slug not in self.comic_slugs:
      return await ctx.send("Comic not found!")
    if channel.guild.id != ctx.guild.id:
      return await ctx.send("Channel not found!")

    sub_dict = {
      "channel_id": str(channel.id),
      "guild_id": str(ctx.guild.id),
      "slug": slug
    }
    results = await r.table("subscriptions").filter(sub_dict).delete().run()
    if results["deleted"] <= 0:
      return await ctx.send("No subscriptions deleted")
    elif results["deleted"] > 0:
      return await ctx.send("Removed!")

  @subscriptions.command()
  @commands.has_permissions(administrator=True)
  async def add(self, ctx, slug: str, channel: discord.TextChannel, role: discord.Role=None):
    """Adds a subscription for a channel"""
    if not channel or channel.guild.id != ctx.guild.id:
      return await ctx.send("Channel not found!")
    if role and role.guild.id != ctx.guild.id:
      return await ctx.send("Role not found!")
    if slug not in self.comic_slugs:
      return await ctx.send("Comic not found!")

    sub_dict = {
      "channel_id": str(channel.id),
      "guild_id": str(ctx.guild.id),
      "slug": slug,
    }
    await r.table("subscriptions").filter(sub_dict).delete().run()
    sub_dict["role_id"] = str(role.id) if role else None

    await self.bot.r.table("subscriptions").insert(sub_dict).run()
    return await ctx.send(f'Done! {channel.mention} has a new subscription to {self.comic_dict[slug]["friendly"]}!')

  @commands.command()
  async def list(self, ctx):
    """Shows list of available webcomics and their slugs"""
    res = "\n".join(
      [f'**{webcomic["friendly"]}**: {webcomic["slug"]}' for webcomic in webcomics])
    return await ctx.send(res)

  @commands.command()
  @commands.is_owner()
  async def recheck_all(self, ctx):
    """Checks for updates to webcomics"""
    await self.check_updates()
    await ctx.send("triple gay")


def setup(bot):
  bot.add_cog(Modular(bot))
