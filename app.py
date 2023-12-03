import asyncio
import discord
import asyncpg
from datetime import datetime
from discord import app_commands
from discord.ext import commands
from typing import Optional
import os
from tz_convert import local_to_utc, utc_to_local
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
            user=os.getenv("USER_NAME"),
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
    event_start_date="Event Start Date (YYYY-MM-DD)",
    event_end_date="Event End Date (YYYY-MM-DD)",
    event_start_time="Event Start Time (HH:MM:SS)",
    event_end_time="Event End Time (HH:MM:SS)",
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
        event_start = datetime.strptime(
            f"{event_start_date} {event_start_time}", "%Y-%m-%d %H:%M:%S")
        event_end = datetime.strptime(
            f"{event_end_date} {event_end_time}", "%Y-%m-%d %H:%M:%S")
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
    event_start_date="Event Start Date (YYYY-MM-DD)",
    event_end_date="Event End Date (YYYY-MM-DD)",
    event_start_time="Event Start Time (HH:MM:SS)",
    event_end_time="Event End Time (HH:MM:SS)",
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
        event_start = datetime.strptime(
            f"{event_start_date} {event_start_time}", "%Y-%m-%d %H:%M:%S")
        event_end = datetime.strptime(
            f"{event_end_date} {event_end_time}", "%Y-%m-%d %H:%M:%S")
        # convert to UTC
        event_start, event_end = local_to_utc(
            event_start), local_to_utc(event_end)
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

# delete event


@bot.tree.command(name="delete_event")
@app_commands.describe(
    event_id="Event ID"
)
async def delete_event(interaction: discord.Interaction, event_id: int):
    uiud = str(interaction.user.id)
    gid = interaction.guild_id

    async with bot.pool.acquire() as conn:
        # Check if the event exists
        event = await conn.fetchrow("SELECT * FROM event WHERE eid = $1 AND uiud = $2", event_id, uiud)

        if event:
            # Delete the event and associated entries
            await conn.execute("DELETE FROM scheduled WHERE eid = $1", event_id)
            await conn.execute("DELETE FROM event WHERE eid = $1", event_id)

            await interaction.response.send_message(
                f"{interaction.user.mention}, event '{event['meetingname']}' has been deleted.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{interaction.user.mention}, event '{event_id}' not found or you don't have permission to delete it.",
                ephemeral=True
            )


# list out all events (outputs only to original user)
@bot.tree.command(name="show_events")
async def show_events(interaction: discord.Interaction):
    uiud = str(interaction.user.id)
    gid = interaction.guild_id
    async with bot.pool.acquire() as conn:
        personal = await conn.fetch(
            "SELECT eid, meetingname, location, timestart, timeend FROM event WHERE uiud = $1 AND gid IS NULL", uiud
        )
        if gid:
            server = await conn.fetch(
                """
                SELECT e.eid, e.meetingname, e.location, e.timestart, e.timeend 
                FROM event e
                INNER JOIN scheduled s ON e.eid = s.eid
                WHERE e.gid = $1 AND s.uiud = $2
                """, gid, uiud
            )
        else:
            server = []

        rows = personal + server

        if rows:
            # Convert from UTC back to the user's time
            response = "Here are your events:\n" + "\n".join(
                f"{row['meetingname']} at {row['location']}, from {utc_to_local(row['timestart'])} to {utc_to_local(row['timeend'])}." for row in rows
            )
        else:
            response = "You have no events scheduled."

        await interaction.response.send_message(response, ephemeral=True)


# shows all server events so a user can potentially sign up for it
@bot.tree.command(name="show_server_events")
async def show_server_events(interaction: discord.Interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message("Server events can only be displayed while using this command in a server.", ephemeral=True)
        return

    async with bot.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT eid, meetingname, location, timestart, timeend FROM event WHERE gid = $1",
            interaction.guild_id
        )

    if rows:
        response = f"Here are the events for {interaction.guild.name}:\n" + "\n".join(
            f"Event {row['eid']}: {row['meetingname']} at {row['location']}, from {row['timestart']} to {row['timeend']}."
            for row in rows
        )
    else:
        response = f"No events available for {interaction.guild.name}."

    await interaction.response.send_message(response)


@bot.tree.command(name="get_notified")
@app_commands.describe(event_number="The event number you want to get notified for")
async def get_notified(interaction: discord.Interaction, event_number: int):
    # Ensure this is used within a server
    if interaction.guild_id is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    uiud = str(interaction.user.id)
    gid = interaction.guild_id

    async with bot.pool.acquire() as conn:
        # Check if the event exists in the server
        event = await conn.fetchrow(
            "SELECT eid, meetingname FROM event WHERE eid = $1 AND gid = $2",
            event_number, gid
        )

        if event:
            existing_signup = await conn.fetchrow(
                "SELECT * FROM scheduled WHERE uiud = $1 AND eid = $2",
                uiud, event['eid']
            )

            if not existing_signup:
                await conn.execute(
                    "INSERT INTO scheduled (uiud, eid, status, notification) VALUES ($1, $2, 'Yes', 0)",
                    # right now im gonna do it so 'Yes' just means signed up and 0 means not notified, you would change to 1 once they have been, and then they wont get pinged again that way.
                    uiud, event['eid']
                )
                await interaction.response.send_message(
                    f"You have been signed up for '{event['meetingname']}'.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"You are already signed up for '{event['meetingname']}'.",
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                f"Event number {event_number} is either not in this server, or the event number is invalid",
                ephemeral=True
            )

@bot.tree.command(name="modify_event")
@app_commands.describe(
    event_id="ID of the event to modify",
    new_meetingname="New name for the meeting (optional)",
    new_location="New location for the event (optional)",
    new_datestart="New start date for the event in YYYY-MM-DD format (optional)",
    new_dateend="New end date for the event in YYYY-MM-DD format (optional)",
    new_timestart="New start time for the event in HH:MM format (optional)",
    new_timeend="New end time for the event in HH:MM format (optional)"
)
async def modify_event(interaction: discord.Interaction,
    event_id: int,
    new_meetingname: Optional[str] = None,
    new_location: Optional[str] = None,
    new_datestart: Optional[str] = None,
    new_dateend: Optional[str] = None,
    new_timestart: Optional[str] = None, 
    new_timeend: Optional[str] = None):
    uiud = str(interaction.user.id)
    async with bot.pool.acquire() as conn:
        event = await conn.fetchrow("SELECT * FROM event WHERE eid = $1 AND uiud = $2", event_id, uiud)
        if not event:
            await interaction.response.send_message("Event not found or you do not have permission to modify this event.", ephemeral=True)
            return

        fields_to_update = {}
        if new_meetingname is not None: fields_to_update['meetingname'] = new_meetingname
        if new_location is not None: fields_to_update['location'] = new_location

        # Handling date and time updates
        try:
            if new_datestart or new_timestart:
                existing_start = event['timestart']
                new_start_date = new_datestart if new_datestart else existing_start.strftime("%Y-%m-%d")
                new_start_time = new_timestart if new_timestart else existing_start.strftime("%H:%M:%S")
                new_eventstart = datetime.strptime(f"{new_start_date} {new_start_time}", "%Y-%m-%d %H:%M:%S")
                new_eventstart = (new_eventstart)
                fields_to_update['timestart'] = new_eventstart

            if new_dateend or new_timeend:
                existing_end = event['timeend']
                new_end_date = new_dateend if new_dateend else existing_end.strftime("%Y-%m-%d")
                new_end_time = new_timeend if new_timeend else existing_end.strftime("%H:%M:%S")
                new_eventend = datetime.strptime(f"{new_end_date} {new_end_time}", "%Y-%m-%d %H:%M:%S")
                new_eventend = (new_eventend)
                fields_to_update['timeend'] = new_eventend

        except ValueError as e:
            await interaction.response.send_message("Invalid date or time format.", ephemeral=True)
            return

        if fields_to_update:
            set_parts = [f"{key} = ${i + 1}" for i, key in enumerate(fields_to_update.keys())]
            values = list(fields_to_update.values())
            values.append(event_id)
            update_query = f"UPDATE event SET {', '.join(set_parts)} WHERE eid = ${len(values)}"
            await conn.execute(update_query, *values)
            await interaction.response.send_message("Event updated successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("No changes specified for the event.", ephemeral=True)

bot.run(os.getenv("DISCORD_TOKEN"))
