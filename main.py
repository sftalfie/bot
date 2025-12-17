import discord
from discord import app_commands
import os, asyncio, json
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

ORIGINAL_GUILD_ID = 1369775313235480586
BACKUP_GUILD_ID = 1450781750887448589

CHANNEL_CONCURRENCY = 3
MESSAGE_CONCURRENCY = 30
DATA_FILE = "sync_data.json"

intents = discord.Intents.all()

CHANNEL_MAP = {}
CATEGORY_MAP = {}
THREAD_MAP = {}
WEBHOOK_MAP = {}
MESSAGE_MAP = {}
ROLE_MAP = {}

def save():
    with open(DATA_FILE, "w") as f:
        json.dump({
            "channels": CHANNEL_MAP,
            "categories": CATEGORY_MAP,
            "threads": THREAD_MAP,
            "messages": MESSAGE_MAP,
            "roles": ROLE_MAP
        }, f)

def load():
    global CHANNEL_MAP, CATEGORY_MAP, THREAD_MAP, MESSAGE_MAP, ROLE_MAP
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            d = json.load(f)
            CHANNEL_MAP = {int(k): int(v) for k, v in d.get("channels", {}).items()}
            CATEGORY_MAP = {int(k): int(v) for k, v in d.get("categories", {}).items()}
            THREAD_MAP = {int(k): int(v) for k, v in d.get("threads", {}).items()}
            MESSAGE_MAP = {int(k): int(v) for k, v in d.get("messages", {}).items()}
            ROLE_MAP = {int(k): int(v) for k, v in d.get("roles", {}).items()}

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        load()

bot = Bot()

async def webhook(ch):
    if ch.id in WEBHOOK_MAP:
        return WEBHOOK_MAP[ch.id]
    h = await ch.create_webhook(name="Mirror")
    WEBHOOK_MAP[ch.id] = h
    return h

async def files_embeds(msg):
    files = []
    for a in msg.attachments:
        try:
            files.append(await a.to_file())
        except:
            pass
    embeds = list(msg.embeds)
    return files[:10], embeds

async def mirror_history(src, dst, sem):
    h = await webhook(dst)
    async for m in src.history(limit=None, oldest_first=True):
        async with sem:
            try:
                f, e = await files_embeds(m)
                s = await h.send(
                    content=(m.content or "") + f"\n{m.jump_url}",
                    username=str(m.author),
                    avatar_url=m.author.display_avatar.url,
                    embeds=e,
                    files=f,
                    wait=True
                )
                MESSAGE_MAP[m.id] = s.id
            except Exception as e:
                print(f"Cannot send message {m.id}: {e}")

async def clone_channel(ch, dst, sem):
    overwrites = {}
    for target, perms in ch.overwrites.items():
        if isinstance(target, discord.Role):
            role_id = ROLE_MAP.get(target.id)
            if role_id:
                overwrites[dst.get_role(role_id)] = perms
        elif isinstance(target, discord.Member):
            overwrites[dst.get_member(target.id)] = perms

    if isinstance(ch, discord.TextChannel) or isinstance(ch, discord.NewsChannel):
        bc = await dst.create_text_channel(
            name=ch.name,
            topic=ch.topic,
            position=ch.position,
            overwrites=overwrites,
            category=dst.get_channel(CATEGORY_MAP.get(ch.category_id))
        )
        CHANNEL_MAP[ch.id] = bc.id
        save()
        await mirror_history(ch, bc, sem)
        async for t in ch.threads(limit=None):
            nt = await bc.create_thread(name=t.name, type=t.type)
            THREAD_MAP[t.id] = nt.id
            save()
            await mirror_history(t, nt, sem)
        archived = await ch.archived_threads().flatten()
        for t in archived:
            nt = await bc.create_thread(name=t.name, type=t.type)
            THREAD_MAP[t.id] = nt.id
            save()
            await mirror_history(t, nt, sem)

    elif isinstance(ch, discord.VoiceChannel):
        vc = await dst.create_voice_channel(
            name=ch.name,
            position=ch.position,
            overwrites=overwrites,
            category=dst.get_channel(CATEGORY_MAP.get(ch.category_id))
        )
        CHANNEL_MAP[ch.id] = vc.id
        save()

    elif isinstance(ch, discord.StageChannel):
        sc = await dst.create_stage_channel(
            name=ch.name,
            position=ch.position,
            overwrites=overwrites,
            category=dst.get_channel(CATEGORY_MAP.get(ch.category_id))
        )
        CHANNEL_MAP[ch.id] = sc.id
        save()

    elif isinstance(ch, discord.ForumChannel):
        fc = await dst.create_forum(
            name=ch.name,
            position=ch.position,
            overwrites=overwrites,
            category=dst.get_channel(CATEGORY_MAP.get(ch.category_id))
        )
        CHANNEL_MAP[ch.id] = fc.id
        save()
        async for t in ch.threads(limit=None):
            nt = await fc.create_thread(name=t.name)
            THREAD_MAP[t.id] = nt.id
            save()
            await mirror_history(t, nt, sem)
        archived = await ch.archived_threads().flatten()
        for t in archived:
            nt = await fc.create_thread(name=t.name)
            THREAD_MAP[t.id] = nt.id
            save()
            await mirror_history(t, nt, sem)

@bot.tree.command(name="backup")
async def backup(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Only admins can run this.", ephemeral=True)
        return

    src = bot.get_guild(ORIGINAL_GUILD_ID)
    dst = bot.get_guild(BACKUP_GUILD_ID)
    await interaction.response.defer(ephemeral=True)

    # Delete all categories and channels
    for c in dst.channels:
        try:
            await c.delete()
        except:
            pass
    for cat in dst.categories:
        try:
            await cat.delete()
        except:
            pass

    # Delete roles safely
    for r in dst.roles:
        if r != dst.default_role:
            try:
                await r.delete()
            except:
                pass

    CHANNEL_MAP.clear()
    CATEGORY_MAP.clear()
    THREAD_MAP.clear()
    MESSAGE_MAP.clear()
    ROLE_MAP.clear()
    save()

    # Clone roles
    for r in sorted(src.roles, key=lambda x: x.position):
        if r.is_default():
            ROLE_MAP[r.id] = dst.default_role.id
            continue
        try:
            new_r = await dst.create_role(
                name=r.name,
                permissions=r.permissions,
                colour=r.colour,
                hoist=r.hoist,
                mentionable=r.mentionable
            )
            ROLE_MAP[r.id] = new_r.id
        except:
            pass
    save()

    # Clone categories
    for cat in sorted(src.categories, key=lambda c: c.position):
        try:
            nc = await dst.create_category(name=cat.name, position=cat.position)
            CATEGORY_MAP[cat.id] = nc.id
        except:
            pass
    save()

    sem_c = asyncio.Semaphore(CHANNEL_CONCURRENCY)
    sem_m = asyncio.Semaphore(MESSAGE_CONCURRENCY)

    async def run(ch):
        async with sem_c:
            try:
                await clone_channel(ch, dst, sem_m)
            except Exception as e:
                print(f"Cannot clone channel {ch.name}: {e}")

    ordered = sorted(
        [c for c in src.channels if not isinstance(c, discord.CategoryChannel)],
        key=lambda c: c.position
    )
    await asyncio.gather(*[run(c) for c in ordered])
    await interaction.followup.send("Backup completed successfully.", ephemeral=True)

bot.run(TOKEN)
