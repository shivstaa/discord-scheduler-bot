import asyncio
import discord
import asyncpg
from datetime import datetime
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
        bot.pool = await asyncpg.create_pool(
            host=os.getenv("HOST"),
            database=os.getenv("DATABASE"),
            user=os.getenv("USER"),
            password=os.getenv("PASSWORD")
        )
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
        
    except Exception as e:
        print(e)

# create private event
@bot.tree.command(name="create_private_event")
@app_commands.describe(
    event_name="Event name", 
    event_start_date="Event Start Date", 
    event_end_date="Event End Date", 
    event_start_time="Event Start Time", 
    event_end_time="Event End Time",
    event_location="Event Location"
)
async def create_private_event(
    interaction: discord.Interaction, 
    event_name: str, 
    event_location: str, 
    event_start_date: str, 
    event_end_date: str, 
    event_start_time: str, 
    event_end_time: str
):
    uiud = str(interaction.user.id)
    user_name = interaction.user.name
    event_start = f"{event_start_date} {event_start_time}"
    event_end = f"{event_end_date} {event_end_time}"
    try:
        event_start = datetime.strptime(f"{event_start_date} {event_start_time}", "%Y-%m-%d %H:%M:%S")
        event_end = datetime.strptime(f"{event_end_date} {event_end_time}", "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        await interaction.response.send_message(
            "Invalid timestamps, please make sure your timestamps follow the format (YYYY-MM-DD) for date and (HH:MM:SS) for time.",
            ephemeral=True
        )
        return
    async with bot.pool.acquire() as conn:

        user = await conn.fetchrow("SELECT * FROM \"user\" WHERE uiud = $1", uiud)
        if user is None:
            await conn.execute("INSERT INTO \"user\" (uiud, name) VALUES ($1, $2)", uiud, user_name)
            
        overlap = await conn.fetchrow(
            """
            SELECT * FROM event
            WHERE uiud = $1
            AND timestart < $3 
            AND timeend > $2
            """,
            uiud, event_start, event_end
        )
        if overlap:
            await interaction.response.send_message(
                f"{interaction.user.mention}, there is an overlapping event."
            )
            return
        
        
        eid = await conn.fetchval(
            "INSERT INTO event (uiud, meetingname, location, timestart, timeend) VALUES ($1, $2, $3, $4, $5) RETURNING eid",
            uiud, event_name, event_location, event_start, event_end
        )
        if eid:
            await conn.execute(
                """
                INSERT INTO scheduled (uiud, eid, status, notification) 
                VALUES ($1, $2, 'Yes', 0)
                """,
                uiud, eid
            )
            await interaction.response.send_message(
                f"{interaction.user.mention}, {event_name} at {event_location} has been scheduled for {event_start_date} from {event_start_time} to {event_end_time}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{interaction.user.mention}, there was an issue creating the event.", ephemeral=True
            )

# create group event
@bot.tree.command(name="create_group_event")
@app_commands.describe(
    event_name="Event name", 
    event_start_date="Event Start Date", 
    event_end_date="Event End Date", 
    event_start_time="Event Start Time", 
    event_end_time="Event End Time",
    event_location="Event Location"
)
async def create_group_event(
    interaction: discord.Interaction, 
    event_name: str, 
    event_location: str, 
    event_start_date: str, 
    event_end_date: str, 
    event_start_time: str, 
    event_end_time: str
):
    if interaction.guild is None:
        await interaction.response.send_message("This is for creating server events!", ephemeral=True)
        return

    gid = interaction.guild_id
    guild_name = interaction.guild.name
    uiud = str(interaction.user.id)
    user_name = interaction.user.name
    try:
        event_start = datetime.strptime(f"{event_start_date} {event_start_time}", "%Y-%m-%d %H:%M:%S")
        event_end = datetime.strptime(f"{event_end_date} {event_end_time}", "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        await interaction.response.send_message(
            "Invalid timestamps, please make sure your timestamps follow the format (YYYY-MM-DD) for date and (HH:MM:SS) for time.",
            ephemeral=True
        )
        return
    
    async with bot.pool.acquire() as conn:
        # Check if the user exists
        user = await conn.fetchrow("SELECT * FROM \"user\" WHERE uiud = $1", uiud)
        if user is None:
            await conn.execute("INSERT INTO \"user\" (uiud, name) VALUES ($1, $2)", uiud, user_name)
        
        group = await conn.fetchrow("SELECT * FROM \"group\" WHERE gid = $1", gid)
        if group is None:
            await conn.execute("INSERT INTO \"group\" (gid, groupname) VALUES ($1, $2)", gid, guild_name)
            
        usergroup = await conn.fetchrow(
            "SELECT * FROM usergroup WHERE uiud = $1 AND gid = $2", 
            uiud, gid
        )
        if usergroup is None:
            await conn.execute(
                "INSERT INTO usergroup (uiud, gid) VALUES ($1, $2)", 
                uiud, gid
            )
        


        eid = await conn.fetchval(
            "INSERT INTO event (uiud, gid, meetingname, location, timestart, timeend) VALUES ($1, $2, $3, $4, $5, $6) RETURNING eid",
            uiud, gid, event_name, event_location, event_start, event_end
        )
        if eid:
            await conn.execute(
                """
                INSERT INTO scheduled (uiud, eid, status, notification) 
                VALUES ($1, $2, 'Yes', 0)
                """,
                uiud, eid
            )
            await interaction.response.send_message(
                f"{interaction.user.mention}, {event_name} at {event_location} has been scheduled for {event_start_date} from {event_start_time} to {event_end_time} for the group {guild_name}."
            )
        else:
            await interaction.response.send_message(
                f"{interaction.user.mention}, there was an issue creating the group event.",
                ephemeral=True
            )
            

#list out all events (outputs only to original user)
@bot.tree.command(name="show_events")
async def show_events(interaction: discord.Interaction):
    async with bot.pool.acquire() as conn:
        uiud = str(interaction.user.id)
        rows = await conn.fetch(
            "SELECT meetingname, location, timestart, timeend FROM event WHERE uiud = $1", uiud
        )
        if rows:
            response = "Here are your events:\n" + "\n".join(
                f"{row['meetingname']} at {row['location']}, from {row['timestart']} to {row['timeend']}."
                for row in rows
            )
        else:
            response = "No events."
        await interaction.response.send_message(response, ephemeral=True)
        
@bot.tree.command(name="show_server_events")
async def show_server_events(interaction: discord.Interaction):
    gid = interaction.guild_id 
    if gid is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    async with bot.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT meetingname, location, timestart, timeend FROM event WHERE gid = $1", gid
        )

        if rows:
            response = f"Here are {interaction.guild.name}'s events:\n" + "\n".join(
                f"{row['meetingname']} at {row['location']}, from {row['timestart']} to {row['timeend']}."
                for row in rows
            )
        else:
            response = "No server events."
        await interaction.response.send_message(response)

    

bot.run(os.getenv("DISCORD_TOKEN"))
