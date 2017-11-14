import aiohttp

class Cog:
    def __init__(self, bot):
        self.bot = bot

async def hastebin(session: aiohttp.ClientSession, text: str, extension:str="py") -> str:
    """ Pastes something to Hastebin, and returns the link to it. """
    async with session.post('https://hastebin.com/documents', data=text) as resp:
        resp_json = await resp.json()
        return f"https://hastebin.com/{resp_json['key']}.{extension}"
