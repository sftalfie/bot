import discord
from discord import app_commands
import os, asyncio, json
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

ORIGINAL_GUILD_ID = 1369775313235480586
BACKUP_GUILD_ID = 1450781750887448589

CHANNEL_CONCURRENCY = 5
MESSAGE_CONCURRENCY = 30
DATA_FILE = "sync_data.json"

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

CHANNEL_MAP = {}
WEBHOOK_MAP = {}
MESSAGE_MAP = {}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump({
            "channels": CHANNEL_MAP,
            "messages": MESSAGE_MAP
        }, f)

def load_data():
    global CHANNEL_MAP, MESSAGE_MAP
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            CHANNEL_MAP = {int(k): int(v) for k, v in data.get("channels", {}).items()}
            MESSAGE_MAP = {int(k): int(v) for k, v in data.get("messages", {}).items()}

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        load_data()

bot = Bot()

async def get_webhook(channel):
    if channel.id in WEBHOOK_MAP:
        return WEBHOOK_MAP[channel.id]
    hook = await channel.create_webhook(name="Mirror")
    WEBHOOK_MAP[channel.id] = hook
    return hook

async def copy_text_channel(src, backup_guild, msg_sem):
    bc = await backup_guild.create_text_channel(
        name=src.name,
        topic=src.topic,
        position=src.position
    )
    CHANNEL_MAP[src.id] = bc.id
    save_data()
    hook = await get_webhook(bc)

    async for msg in src.history(limit=None, oldest_first=True):
        async with msg_sem:
            try:
                files = [await a.to_file() for a in msg.attachments[:10]]
                sent = await hook.send(
                    content=(msg.content or "") + f"\n🔗 {msg.jump_url}",
                    username=str(msg.author),
                    avatar_url=msg.author.display_avatar.url,
                    embeds=msg.embeds,
                    files=files,
                    wait=True
                )
                MESSAGE_MAP[msg.id] = sent.id
            except:
                pass
    save_data()

@bot.tree.command(name="backup")
async def backup(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("no", ephemeral=True)
        return

    src = bot.get_guild(ORIGINAL_GUILD_ID)
    dst = bot.get_guild(BACKUP_GUILD_ID)

    await interaction.response.defer(ephemeral=True)

    for c in dst.channels:
        await c.delete()

    CHANNEL_MAP.clear()
    MESSAGE_MAP.clear()
    save_data()

    sem_c = asyncio.Semaphore(CHANNEL_CONCURRENCY)
    sem_m = asyncio.Semaphore(MESSAGE_CONCURRENCY)

    async def proc(ch):
        async with sem_c:
            if isinstance(ch, discord.TextChannel):
                await copy_text_channel(ch, dst, sem_m)
            elif isinstance(ch, discord.VoiceChannel):
                vc = await dst.create_voice_channel(name=ch.name, position=ch.position)
                CHANNEL_MAP[ch.id] = vc.id
                save_data()

    await asyncio.gather(*[proc(c) for c in src.channels])

    await interaction.followup.send("done", ephemeral=True)

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild or msg.guild.id != ORIGINAL_GUILD_ID:
        return
    if msg.channel.id not in CHANNEL_MAP:
        return

    bc = bot.get_channel(CHANNEL_MAP[msg.channel.id])
    hook = await get_webhook(bc)

    try:
        files = [await a.to_file() for a in msg.attachments[:10]]
        sent = await hook.send(
            content=(msg.content or "") + f"\n🔗 {msg.jump_url}",
            username=str(msg.author),
            avatar_url=msg.author.display_avatar.url,
            embeds=msg.embeds,
            files=files,
            wait=True
        )
        MESSAGE_MAP[msg.id] = sent.id
        save_data()
    except:
        pass

@bot.event
async def on_message_edit(before, after):
    if after.id not in MESSAGE_MAP:
        return
    bc_id = CHANNEL_MAP.get(after.channel.id)
    if not bc_id:
        return
    bc = bot.get_channel(bc_id)
    try:
        msg = await bc.fetch_message(MESSAGE_MAP[after.id])
        await msg.edit(content=(after.content or "") + f"\n🔗 {after.jump_url}", embeds=after.embeds)
    except:
        pass

@bot.event
async def on_message_delete(msg):
    if msg.id not in MESSAGE_MAP:
        return
    bc_id = CHANNEL_MAP.get(msg.channel.id)
    if not bc_id:
        return
    bc = bot.get_channel(bc_id)
    try:
        m = await bc.fetch_message(MESSAGE_MAP[msg.id])
        await m.delete()
        MESSAGE_MAP.pop(msg.id, None)
        save_data()
    except:
        pass

@bot.event
async def on_guild_channel_create(ch):
    if ch.guild.id != ORIGINAL_GUILD_ID:
        return
    dst = bot.get_guild(BACKUP_GUILD_ID)
    if isinstance(ch, discord.TextChannel):
        bc = await dst.create_text_channel(name=ch.name, topic=ch.topic, position=ch.position)
        CHANNEL_MAP[ch.id] = bc.id
    elif isinstance(ch, discord.VoiceChannel):
        vc = await dst.create_voice_channel(name=ch.name, position=ch.position)
        CHANNEL_MAP[ch.id] = vc.id
    save_data()

@bot.event
async def on_guild_channel_delete(ch):
    if ch.id not in CHANNEL_MAP:
        return
    bc = bot.get_channel(CHANNEL_MAP[ch.id])
    if bc:
        await bc.delete()
    CHANNEL_MAP.pop(ch.id, None)
    save_data()

bot.run(TOKEN)
