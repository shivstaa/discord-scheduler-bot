import discord
from discord import app_commands
from discord.ext import commands
import os
from dotenv import load_dotenv
load_dotenv()

intents = discord.Intents.all()
# intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')

    # verifies # of commands that are functional on Discord
    try: 
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

# create private event
@bot.tree.command(name="create_private_event")
@app_commands.describe(event_name="Event name", event_start_date="Event Start Date", event_end_date="Event End Date", event_start_time="Event Start Time", event_end_time="Event End Time")
async def create_private_event(interaction: discord.Interaction, event_name: str, event_start_date: str, event_end_date: str, event_start_time: str, event_end_time: str):
    await interaction.response.send_message(f"{interaction.user.name} {event_name} created from {event_start_date} at {event_start_time} to {event_end_date} at {event_end_time}")

# create group event
@bot.tree.command(name="create_group_event")
@app_commands.describe(event_name="Event name", event_start_date="Event Start Date", event_end_date="Event End Date", event_start_time="Event Start Time", event_end_time="Event End Time")
async def create_group_event(interaction: discord.Interaction, event_name: str, event_start_date: str, event_end_date: str, event_start_time: str, event_end_time: str):
    await interaction.response.send_message(f"{interaction.user.name} {event_name} created from {event_start_date} at {event_start_time} to {event_end_date} at {event_end_time}")


bot.run(os.getenv("DISCORD_TOKEN"))