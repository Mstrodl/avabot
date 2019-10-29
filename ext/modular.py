# https://killsixbilliondemons.com/feed/
# http://twokinds.keenspot.com/feed.xml
# http://mylifewithfel.smackjeeves.com/rss/


import asyncio
import json
import re
import os
import math
import time

import discord
import aiohttp
# Oops, my finger slipped
import lxml.html
# import rethinkdb as r
import dateutil.parser
import datetime
import lxml.etree
import lxml.html
import urllib.parse
from discord.ext import commands

from .common import Cog

page_num_regex = r"((?:-|\d){3,5})"  # Used to match page #s in RSS feed titles
# Some newer comics just seem to work better this way
comic_link_regex = r"\/(?:dnw)?comic\/([a-z0-9_\-]+)(?:\/)?$"
comic_link_num_regex = r"comic=((?:-|\d){3,5})$"
parser = lxml.etree.XMLParser(encoding="utf-8")
html_parser = lxml.html.HTMLParser(encoding="utf-8")


class BadPage(Exception):
  pass

async def http_req(url, headers={}, body=None):
  async with aiohttp.ClientSession() as session:
    chosen_req = session.post if body else session.get
    async with chosen_req(url, headers=headers, data=body) as resp:
      return {
        "text": await resp.read(),
        "resp": resp
      }


async def status_page(comic, bot):
  base_url = comic["statuspage_slug"] + ".statuspage.io" \
          if comic.get("statuspage_slug", None) != None \
          else comic["statuspage_url"]
  resp = await http_req("https://" + base_url + "/history.json")
  text = resp["text"]

  if resp["resp"].status == 200:
    parsed = json.loads(text)

    months = parsed.get("months", None)
    if months == None:
      raise BadPage(f"No months prop")
    month = months[0]
    if month == None:
      raise BadPage(f"No months listed")
    incidents = month.get("incidents", None)
    if incidents == None:
      raise BadPage(f"No incidents prop")
    incident = incidents[0]
    if incident == None:
      raise BadPage(f"No incidents listed")

    return {
      "latest_post": {
        "unique_id": incident["code"],
        "url": f"https://{base_url}/incidents/{incident['code']}",
        "title": incident["name"],
        "time": bot.r.now(),
      }
    }
  else:
    raise BadPage("Non-200 status code: " + str(resp["resp"].status))

async def common_rss(comic, bot):
  resp = await http_req(comic["rss_url"])
  text = resp["text"]

  if resp["resp"].status == 200:
    parsed = lxml.etree.fromstring(text, parser=parser)
    post = parsed.cssselect("rss channel item")[0]
    title = post.cssselect("title")[0].text
    url = post.cssselect("link")[0].text
    page_num_search = re.search(page_num_regex, title)
    if not page_num_search:
      page_num_search = re.search(comic_link_regex, url)
    if not page_num_search:
      page_num_search = re.search(comic_link_num_regex, url)
    if not page_num_search:
      page_num_search = re.search(r"(.*)", url)
      # raise BadPage(f"No unique ID found for page title: '{title}' or url: '{url}'")

    page_num = page_num_search.group(1)
    found_pubdate = post.cssselect("pubDate")
    if found_pubdate:
        time = dateutil.parser.parse(found_pubdate[0].text).astimezone(bot.r.make_timezone("0:00"))
    else:
      time = bot.r.now()
    return {
      "latest_post": {
        "unique_id": page_num,
        "url": url,
        "title": title,
        "time": time
      }
    }

async def egs_scrape(comic, bot):
  resp = await http_req(comic["base_url"])
  text = resp["text"]
  xml_document = lxml.html.fromstring(text, parser=html_parser)
  comic_date_element = xml_document.cssselect('#leftarea div[style*="font-family"]')[0]
  comic_img_element = xml_document.cssselect('#cc-comic')[0]
  comic_date = lxml.html.tostring(comic_date_element)
  comic_name = comic_img_element.attrib["title"]
  return {
    "latest_post": {
      "unique_id": comic_name,
      "url": f'{comic["base_url"]}{comic_name}',
      "title": comic_date,
      "time": bot.r.now()
    }
  }

async def twokinds_scrape(comic, bot):
  resp = await http_req(comic["base_url"])
  text = resp["text"]
  xml_document = lxml.html.fromstring(text, parser=html_parser)
  # Grab the newest page from the 'latest' button
  article_obj = xml_document.cssselect("article.comic")[0]
  permalink_page = article_obj.cssselect("div.below-nav p.permalink a[href^=\"/comic\/\"]")[0]
  permalink_url = permalink_page.attrib["href"]
  title = article_obj.cssselect("img[alt=\"Comic Page\"]")[0].attrib["title"]
  try:
    page_num = int(os.path.basename(os.path.split(permalink_url)[0]))
  except ValueError as err:
    raise BadPage(f"No unique ID found for page URL: '{permalink_url}'")
  
  return {
    "latest_post": {
      "unique_id": page_num,
      "url": f'{comic["base_url"]}{permalink_url}',
      "title": title,
      "time": bot.r.now()
    }
  }

# Ava's Demon scraper because the she doesn't update RSS as soon...
async def avasdemon_scrape(comic, bot):
  resp = await http_req(f'{comic["base_url"]}/js/comicQuickLinks.js?v=' + str(math.floor(time.time())))

  blob = re.search(r'var ad_cql="(.*)";$', resp["text"].decode()).group(1)
  comic_data = ''.join([chr(int(chars, 16)) for chars in re.findall(r".{1,2}", blob)])
  page_num = re.search(r"var latestComicLinkHtml=(\d+);", comic_data).group(1)

  return {
    "latest_post": {
      "unique_id": page_num,
      "url": f'{comic["base_url"]}/pages.php#{page_num}',
      "title": f"Page {page_num}",
      "time": bot.r.now()
    }
  }


async def xkcd_fetch(comic, bot):
  resp = await http_req(f'{comic["base_url"]}/info.0.json')
  text = resp["text"]
  page = json.loads(text)
  return {
    "latest_post": {
      "unique_id": page["num"],
      "url": f'{comic["base_url"]}/{page["num"]}',
      "title": f'{page["title"]} ({page["alt"]}',
      "time": bot.r.time(int(page["year"]), int(page["month"]), int(page["day"]), "Z")
    }
  }


async def twitter_listener(user, bot):
  handle = comic["handle"] # User's Twitter handle
  

webcomics = [
  {
    "slug": "discordstatus",
    "friendly": "Discord Status",
    "check_updates": status_page,
    "statuspage_slug": "discord"
  },
  {
    "slug": "cloudflarestatus",
    "friendly": "Cloutflare Status",
    "check_updates": status_page,
    "statuspage_slug": "cloudflare"
  },
  {
    "slug": "githubstatus",
    "friendly": "Github Status",
    "check_updates": status_page,
    "statuspage_url": "www.githubstatus.com"
  },
  {
    "slug": "redditstatus",
    "friendly": "Reddit Status",
    "check_updates": status_page,
    "statuspage_slug": "reddit"
  },
  {
    "slug": "dostatus",
    "friendly": "Digital Ocean Status",
    "check_updates": status_page,
    "statuspage_url": "status.digitalocean.com"
  },
  {
    "slug": "gitlabstatus",
    "friendly": "GitLab Status",
    "check_updates": common_rss,
    "rss_url": "https://status.gitlab.com/pages/5b36dc6502d06804c08349f7/rss"
  },
  {
    "slug": "webplatformnews",
    "friendly": "Web Platform News",
    "check_updates": common_rss,
    "rss_url": "https://webplatform.news/feed.xml"
  },
  {
    "slug": "questionablecontent",
    "friendly": "Questionable Content",
    "check_updates": common_rss,
    "rss_url": "https://www.questionablecontent.net/QCRSS.xml"
  },
  {
    "slug": "overthehedge",
    "friendly": "Over the Hedge",
    "check_updates": common_rss,
    "rss_url": "https://overthehedgeblog.wordpress.com/feed"
  },
  {
    "slug": "pv02",
    "friendly": "A robot named Pivot",
    "check_updates": common_rss,
    "rss_url": "https://www.pv02comic.com/feed/"
  },
#  {
#    "slug": "smbc",
#    "friendly": "Saturday Morning Breakfast Cereal",
#    "check_updates": common_rss,
#    "rss_url": "http://www.smbc-comics.com/comic/rss"
#  },
#  {
#    "slug": "back",
#    "friendly": "BACK",
#    "check_updates": common_rss,
#    "rss_url": "http://backcomic.com/rss.xml"
#  },
  {
    "slug": "tove",
    "friendly": "TOVE",
    "check_updates": common_rss,
    "rss_url": "http://www.tovecomic.com/comic/rss"
  },
  {
    "slug": "drugsandwires",
    "friendly": "DRUGS & WIRES",
    "check_updates": common_rss,
    "rss_url": "https://www.drugsandwires.fail/feed/"
  },
  {
    "slug": "twokinds",
    "friendly": "Two Kinds",
    "check_updates": twokinds_scrape,
    "base_url": "http://twokinds.keenspot.com"
  },
  {
    "slug": "egs",
    "friendly": "El Goonish Shive",
    "check_updates": egs_scrape,
    "base_url": "https://egscomics.com/comic/"
  },  
  {
    "base_url": "https://avasdemon.com",
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
    "rss_url": "http://www.mylifewithfel.com/rss/"
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
        try:
          await self.check_updates()
        except Exception as err:
          self.bot.logger.exception("penid")
          self.bot.logger.exception(err)
        await asyncio.sleep(10 * 60)  # Check RSS every 10 min
    self.check_loop = self.bot.loop.create_task(run_check())

  def __unload(self):
    self.check_loop.cancel()

  async def check_updates(self):
    for comic in webcomics:
      # haha yes we have the comics now we do their update hook!
      friendly_name = comic["friendly"]
      self.bot.logger.info(f"Fetching {friendly_name}")
      try:
        results = await comic["check_updates"](comic, self.bot)
      except lxml.etree.XMLSyntaxError as err:
        self.bot.logger.error(f"Error occurred while fetching {friendly_name}: {err}")
      except aiohttp.client_exceptions.ClientConnectionError as err:
        self.bot.logger.error(f"Error occurred while fetching {friendly_name}: {err}")
        continue
      except BadPage as err:
        self.bot.logger.error(f"Error occurred while fetching {friendly_name}: {err}")
        continue
      except Exception as err:
        self.bot.logger.error(f"VERY bad, this should never happen! {friendly_name}: {err}")
        self.bot.logger.exception(err)
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
    response = f"New panels for {friendly_name}!\nLatest panel:\n{post_title}\n{url}"

    if self.bot.prod and self.bot.config.mastodon and self.bot.config.mastodon["token"] and self.bot.config.mastodon["instance_url"]:
      await http_req(f"{self.bot.config.mastodon['instance_url']}/api/v1/statuses",
                     {"Authorization":
                      f"Bearer {self.bot.config.mastodon['token']}"},
                     {
                       "status": f"{response}\n\n #avabot_update #avabot_update_{comic['slug']}",
                       "visibility": "unlisted"
                     })
      
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
    results = await self.bot.r.table("subscriptions").filter(sub_dict).delete().run()
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
    await self.bot.r.table("subscriptions").filter(sub_dict).delete().run()
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
