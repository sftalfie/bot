import discord
from discord import app_commands, ui
import os
from dotenv import load_dotenv
import re
import asyncio

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
BACKUP_GUILD_ID = 1450781750887448589
ORIGINAL_GUILD_ID = 1369775313235480586

class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.guilds = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def on_message(self, message):
        if message.author == self.user:
            return
        if message.guild.id == ORIGINAL_GUILD_ID:
            backup_guild = self.get_guild(BACKUP_GUILD_ID)
            if backup_guild:
                backup_channel = discord.utils.get(backup_guild.channels, name=message.channel.name)
                if backup_channel and isinstance(backup_channel, discord.TextChannel):
                    files = [await att.to_file() for att in message.attachments]
                    await backup_channel.send(content=f"**{message.author}**: {message.content}", files=files, embeds=message.embeds)

    async def on_guild_channel_create(self, channel):
        backup_guild = self.get_guild(BACKUP_GUILD_ID)
        if backup_guild and channel.guild.id == ORIGINAL_GUILD_ID:
            if isinstance(channel, discord.TextChannel):
                await backup_guild.create_text_channel(name=channel.name, topic=channel.topic, position=channel.position)
            elif isinstance(channel, discord.VoiceChannel):
                await backup_guild.create_voice_channel(name=channel.name, position=channel.position)

    async def on_guild_channel_delete(self, channel):
        backup_guild = self.get_guild(BACKUP_GUILD_ID)
        if backup_guild and channel.guild.id == ORIGINAL_GUILD_ID:
            backup_channel = discord.utils.get(backup_guild.channels, name=channel.name)
            if backup_channel:
                await backup_channel.delete()


bot = MyBot()

@bot.tree.command(name="backup", description="Copy all channels and messages from the original server to the backup server")
async def backup(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('Only admins can use this command.', ephemeral=True)
        return
    original_guild = bot.get_guild(ORIGINAL_GUILD_ID)
    backup_guild = bot.get_guild(BACKUP_GUILD_ID)
    if not original_guild or not backup_guild:
        await interaction.response.send_message('Original or backup server not found.', ephemeral=True)
        return
    await interaction.response.defer()
    try:
     
        for channel in backup_guild.channels:
            await channel.delete()

        total_channels = len([c for c in original_guild.channels if isinstance(c, discord.TextChannel)])
        processed_channels = 0

    
        for channel in original_guild.channels:
            if isinstance(channel, discord.TextChannel):
                backup_channel = await backup_guild.create_text_channel(name=channel.name, topic=channel.topic, position=channel.position)
              
                messages_to_copy = []
                async for message in channel.history(limit=None, oldest_first=True):
                    if message.author != bot.user: 
                        messages_to_copy.append(message)

               
                batch_size = 5
                for i in range(0, len(messages_to_copy), batch_size):
                    batch = messages_to_copy[i:i + batch_size]
                    tasks = []
                    for message in batch:
                        async def send_message(msg):
                            try:
                                files = []
                                total_size = 0
                                for att in msg.attachments:
                                    if len(files) >= 10 or total_size + att.size > 8 * 1024 * 1024:
                                        break
                                    file = await att.to_file()
                                    files.append(file)
                                    total_size += att.size
                                await backup_channel.send(content=f"**{msg.author}**: {msg.content}", files=files, embeds=msg.embeds)
                            except discord.HTTPException as e:
                                if e.code == 40005:
                                    pass
                                else:
                                    raise
                        tasks.append(send_message(message))
                    await asyncio.gather(*tasks)
                processed_channels += 1
                if processed_channels % 5 == 0 or processed_channels == total_channels:
                    await interaction.followup.send(f'Progress: {processed_channels}/{total_channels} channels copied.', ephemeral=True)
            elif isinstance(channel, discord.VoiceChannel):
                await backup_guild.create_voice_channel(name=channel.name, position=channel.position)
        await interaction.followup.send('Backup completed: all channels and messages copied to backup server.')
    except Exception as e:
        await interaction.followup.send(f'Error during backup: {str(e)}')

bot.run(TOKEN)
