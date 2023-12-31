import asyncio
import discord
import asyncpg
from datetime import datetime
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Modal, Button, View, TextInput
from discord import ButtonStyle
from typing import Optional
import os
from tz_convert import local_to_utc, utc_to_local, time_format_locale, date_format, find_timezone, convert_locale, local_to_utc_date, validate_time_input
import timedelta
from dotenv import load_dotenv
import pytz

load_dotenv()
intents = discord.Intents.all()
reminder_status = asyncio.Event()
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
        reminder.start()
        cleanup.start()
        print(f"Synced {len(synced)} command(s)")

    except Exception as e:
        print("Error ", e)


@tasks.loop(minutes=1)
async def reminder():
    await bot.wait_until_ready()
    current_time = datetime.utcnow()

    async with bot.pool.acquire() as conn:
        events = await conn.fetch(
            """
            SELECT s.uiud, s.eid, e.meetingname, e.timestart, e.timeend, e.gid, s.notification
            FROM scheduled s
            INNER JOIN event e ON s.eid = e.eid
            WHERE e.timestart <= $1
            AND s.notification = 0
            """,
            current_time
        )

        for event in events:
            if not event['gid']:
                user = await bot.fetch_user(event['uiud'])
                if user:
                    await user.send(f"'{event['meetingname']}' is starting soon!")

            else:
                server = bot.get_guild(event['gid'])
                if server:
                    role = discord.utils.get(
                        server.roles, name=f"Event {event['eid']}")
                    if role:
                        # this just picks either the system or first available text channel, so idk what yall want
                        channel = server.system_channel or next(
                            (x for x in server.text_channels), None)
                        if channel:
                            await channel.send(f"{role.mention} Your event '{event['meetingname']}' is starting soon!")
                    else:
                        channel = server.system_channel or next(
                            (x for x in server.text_channels), None)
                        if channel:
                            await channel.send(f"Your event '{event['meetingname']}' is starting soon!")

            await conn.execute(
                "UPDATE scheduled SET notification = 1 WHERE uiud = $1 AND eid = $2",
                event['uiud'], event['eid']
            )
    reminder_status.set()


@tasks.loop(minutes=1)
async def cleanup():
    await reminder_status.wait()
    current_time = datetime.utcnow()

    async with bot.pool.acquire() as conn:
        ended = await conn.fetch(
            """
            SELECT eid, meetingname, gid
            FROM event
            WHERE timeend <= $1
            """,
            current_time
        )

        for event in ended:
            if event['gid']:
                server = bot.get_guild(event['gid'])
                if server:
                    role_name = f"Event {event['eid']}"
                    role = discord.utils.get(server.roles, name=role_name)
                    if role:
                        try:
                            await role.delete(reason=f"Event {event['eid']} has ended.")
                        except discord.Forbidden:
                            print(
                                f"The bot doesn't have permission to delete roles in this server, please contact your server admins!")
                        except discord.HTTPException as e:
                            print(
                                f"Failed to delete role for event {event['eid']}: {e}")

            await conn.execute("DELETE FROM scheduled WHERE eid = $1", event['eid'])
            await conn.execute("DELETE FROM event WHERE eid = $1", event['eid'])
    reminder_status.clear()


class CreatePrivateView(discord.ui.View):
    def __init__(self, event_details, uiud, user_name, timezone, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.event_details = event_details
        self.uiud = uiud
        self.user_name = user_name
        self.timezone = timezone
        self.future = asyncio.Future()

    @discord.ui.button(label="Submit", style=discord.ButtonStyle.green)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Extract event details
        event_name = self.event_details['event_name']
        event_location = self.event_details['event_location']
        event_start = f"{self.event_details['event_start_date']} {local_to_utc(self.event_details['event_start_time'])}"
        event_end = f"{self.event_details['event_end_date']} {local_to_utc(self.event_details['event_end_time'])}"
        try:
            event_start_cpy = event_start
            event_end_cpy = event_end

            event_start_utc = local_to_utc_date(event_start_cpy)
            event_end_utc = local_to_utc_date(event_end_cpy)

            event_start = datetime.strptime(
                event_start, "%Y-%m-%d %H:%M:%S")
            event_end = datetime.strptime(
                event_end, "%Y-%m-%d %H:%M:%S")

            # if not validate_time_input(event_start_utc, event_end_utc):
            #     raise ValueError(
            #         "Event start time is either past or after event end time")

        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            self.future.set_result(True)
            return

        async with bot.pool.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM \"user\" WHERE uiud = $1", self.uiud)
            if user is None:
                await conn.execute("INSERT INTO \"user\" (uiud, name) VALUES ($1, $2)", self.uiud, self.user_name)

            eid = await conn.fetchval(
                "INSERT INTO event (uiud, meetingname, location, timestart, timeend) VALUES ($1, $2, $3, $4, $5) RETURNING eid",
                self.uiud, event_name, event_location, event_start, event_end)

            if eid:
                await conn.execute(
                    "INSERT INTO scheduled (uiud, eid, status, notification) VALUES ($1, $2, 'Yes', 0)",
                    self.uiud, eid)
                role_name = f"Event {eid}"
                await notification_role(interaction.guild, interaction.user.id, role_name)
                await interaction.response.send_message(
                    f"{interaction.user.mention}, {event_name} at {event_location} has been scheduled for {date_format(self.event_details['event_start_date'])} to {date_format(self.event_details['event_end_date'])} from {convert_locale(local_to_utc(self.event_details['event_start_time']), self.timezone)} to {convert_locale(local_to_utc(self.event_details['event_end_time']), self.timezone)}.", ephemeral=True)

            else:
                await interaction.response.send_message(
                    f"{interaction.user.mention}, there was an issue creating the event.", ephemeral=True)

        self.future.set_result(True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Operation canceled.", ephemeral=True)

        self.future.set_result(True)


class CreateServerView(discord.ui.View):
    def __init__(self, event_details, uiud, user_name, gid, timezone, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.event_details = event_details
        self.uiud = uiud
        self.user_name = user_name
        self.gid = gid
        self.timezone = timezone
        self.future = asyncio.Future()

    @discord.ui.button(label="Submit", style=discord.ButtonStyle.green)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Extract event details
        event_name = self.event_details['event_name']
        event_location = self.event_details['event_location']
        event_start = f"{self.event_details['event_start_date']} {local_to_utc(self.event_details['event_start_time'])}"
        event_end = f"{self.event_details['event_end_date']} {local_to_utc(self.event_details['event_end_time'])}"
        try:
            event_start_cpy = event_start
            event_end_cpy = event_end

            event_start_utc = local_to_utc_date(event_start_cpy)
            event_end_utc = local_to_utc_date(event_end_cpy)

            event_start = datetime.strptime(
                event_start, "%Y-%m-%d %H:%M:%S")
            event_end = datetime.strptime(
                event_end, "%Y-%m-%d %H:%M:%S")

            # if not validate_time_input(event_start_utc, event_end_utc):
            #     raise ValueError(
            #         "Event start time is either past or after event end time")

        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            self.future.set_result(True)
            return

        # Database operations
        async with bot.pool.acquire() as conn:

            # Insert new event
            eid = await conn.fetchval(
                "INSERT INTO event (uiud, gid, meetingname, location, timestart, timeend) VALUES ($1, $2, $3, $4, $5, $6) RETURNING eid",
                self.uiud, self.gid, event_name, event_location, event_start, event_end)

            if eid:
                await conn.execute(
                    "INSERT INTO scheduled (uiud, eid, status, notification) VALUES ($1, $2, 'Yes', 0)",
                    self.uiud, eid)
                role_name = f"Event {eid}"
                await notification_role(interaction.guild, interaction.user.id, role_name)
                await interaction.response.send_message(
                    f"{interaction.user.mention}, {event_name} at {event_location} has been scheduled for {date_format(self.event_details['event_start_date'])} to {date_format(self.event_details['event_end_date'])} from {convert_locale(local_to_utc(self.event_details['event_start_time']), self.timezone)} to {convert_locale(local_to_utc(self.event_details['event_end_time']), self.timezone)}.", ephemeral=True)

            else:
                await interaction.response.send_message(
                    f"{interaction.user.mention}, there was an issue creating the event.",
                    ephemeral=True)

            self.future.set_result(True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Operation canceled.", ephemeral=True)
        self.future.set_result(True)


class DeleteView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, event_id: int, event_name: str, bot):
        super().__init__(timeout=180)
        self.interaction = interaction
        self.event_id = event_id
        self.event_name = event_name
        self.bot = bot
        self.value = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("You are not authorized to perform this action.", ephemeral=True)
            return

        async with self.bot.pool.acquire() as conn:
            # Delete the event
            await conn.execute("DELETE FROM scheduled WHERE eid = $1", self.event_id)
            await conn.execute("DELETE FROM event WHERE eid = $1", self.event_id)

            server = self.interaction.guild
            if server:
                role_name = f"Event {self.event_id}"
                role = discord.utils.get(server.roles, name=role_name)
                if role:
                    try:
                        await role.delete(reason=f"Event {self.event_id} deleted")
                    except discord.Forbidden:
                        await interaction.response.send_message("The bot does not have permissions to delete roles, and the notification role has not been deleted. Please contact your server admins for help.", ephemeral=True)
                        return
                    except discord.HTTPException as e:
                        await interaction.response.send_message(f"Failed to delete notification role: {e}, please notify your admins to delete this role.", ephemeral=True)
                        return

            await interaction.response.send_message(f"Event '{self.event_name}' has been successfully deleted.", ephemeral=True)
        self.value = True
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()


class PaginationView(View):
    def __init__(self, data, embed_creator, interaction):
        super().__init__()
        self.data = data
        self.embed_creator = embed_creator
        self.interaction = interaction
        self.current_page = 0
        self.total_pages = len(data)

        # Previous button
        self.previous_button = Button(
            label='Previous', style=discord.ButtonStyle.grey, disabled=True)
        self.previous_button.callback = self.on_previous
        self.add_item(self.previous_button)

        # Next button
        self.next_button = Button(
            label='Next', style=discord.ButtonStyle.grey, disabled=self.total_pages <= 1)
        self.next_button.callback = self.on_next
        self.add_item(self.next_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.interaction.user.id

    async def on_previous(self, interaction: discord.Interaction):
        # Move to prev page and update embed/buttons
        if self.current_page > 0:
            self.current_page -= 1
            embed = self.embed_creator(self.data[self.current_page])
            self.previous_button.disabled = self.current_page == 0
            self.next_button.disabled = self.current_page == self.total_pages - 1
            await interaction.response.edit_message(embed=embed, view=self)

    async def on_next(self, interaction: discord.Interaction):
        # Move to next page and update embed/buttons
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            embed = self.embed_creator(self.data[self.current_page])
            self.previous_button.disabled = self.current_page == 0
            self.next_button.disabled = self.current_page == self.total_pages - 1
            await interaction.response.edit_message(embed=embed, view=self)


class NotificationView(discord.ui.View):
    def __init__(self, event_id, event_name, user_id, uiud, gid):
        super().__init__(timeout=180)
        self.event_id = event_id
        self.event_name = event_name
        self.user_id = user_id
        self.uiud = uiud
        self.gid = gid
        self.future = asyncio.Future()

    @discord.ui.button(label="Notify Me", style=discord.ButtonStyle.green)
    async def notify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with bot.pool.acquire() as conn:
            existing_signup = await conn.fetchrow(
                "SELECT * FROM scheduled WHERE uiud = $1 AND eid = $2",
                self.uiud, self.event_id
            )
            if not existing_signup:
                await conn.execute(
                    "INSERT INTO scheduled (uiud, eid, status, notification) VALUES ($1, $2, 'Yes', 1)",
                    self.uiud, self.event_id
                )
                role_name = f"Event {self.event_id}"
                await notification_role(interaction.guild, interaction.user.id, role_name)
                await interaction.response.send_message(f"You will be notified for '{self.event_name}'.", ephemeral=True)
                self.future.set_result(True)
            else:
                await interaction.response.send_message(f"You are already signed up for '{self.event_name}'.", ephemeral=True)
                self.future.set_result(True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Handle the cancellation of the command
        await interaction.response.send_message("Command canceled.", ephemeral=True)
        self.future.set_result(True)


class RemoveNotificationView(discord.ui.View):
    def __init__(self, event_id, uiud, interaction):
        super().__init__(timeout=180)
        self.event_id = event_id
        self.uiud = uiud
        self.interaction = interaction
        self.future = asyncio.Future()

    @discord.ui.button(label="Remove Notification", style=discord.ButtonStyle.red)
    async def remove_button(self,  interaction: discord.Interaction, button: discord.ui.Button):
        # Logic to remove the notification
        async with bot.pool.acquire() as conn:
            # Check if the user is signed up for the event
            signup = await conn.fetchrow(
                "SELECT * FROM scheduled WHERE uiud = $1 AND eid = $2",
                self.uiud, self.event_id
            )
            print(f"Query result: {signup}")
            if signup:
                # Remove the user from the scheduled table
                await conn.execute(
                    "DELETE FROM scheduled WHERE uiud = $1 AND eid = $2",
                    self.uiud, self.event_id
                )

                # Attempt to remove the role from server user
                server = self.interaction.guild
                if server:
                    role_name = f"Event {self.event_id}"
                    role = discord.utils.get(server.roles, name=role_name)
                    member = server.get_member(int(self.uiud))
                    if role and member:
                        try:
                            await member.remove_roles(role, reason=f"User opted out of event {self.event_id} notifications")
                        except discord.Forbidden:
                            await interaction.response.send_message(
                                "The bot does not have permissions to delete roles, and the notification role has not been removed. Please contact your server admins for help.",
                                ephemeral=True
                            )
                            self.future.set_result(True)
                            return
                        except discord.HTTPException as e:
                            await interaction.response.send_message(
                                f"Failed to delete notification role: {e}, please notify your admins to delete this role.",
                                ephemeral=True
                            )
                            self.future.set_result(True)
                            return

                await interaction.response.send_message(
                    f"You will no longer receive notifications for event ID {self.event_id}.",
                    ephemeral=True
                )
                self.future.set_result(True)

            else:
                await interaction.response.send_message(
                    f"You are not signed up for notifications for event ID {self.event_id}, or it does not exist.",
                    ephemeral=True
                )
                self.future.set_result(True)

            self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Handle the cancellation of the command
        await interaction.response.send_message("Notification removal canceled.", ephemeral=True)
        self.future.set_result(True)
        self.stop()


# create private event
@bot.tree.command(name="create_private_event")
@app_commands.describe(
    event_name="Event name",
    event_location="Event Location",
    event_start_date="Event Start Date (YYYY-MM-DD)",
    event_end_date="Event End Date (YYYY-MM-DD)",
    event_start_time="Event Start Time (HH:MM:SS)",
    event_end_time="Event End Time (HH:MM:SS)"
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
    event_details = {
        'event_name': event_name,
        'event_location': event_location,
        'event_start_date': event_start_date,
        'event_end_date': event_end_date,
        'event_start_time': event_start_time,
        'event_end_time': event_end_time
    }
    uiud = str(interaction.user.id)
    user_name = interaction.user.name

    embed = discord.Embed(
        title="Event Confirmation",
        description="Please confirm the event creation:",
        color=discord.Color.blue()
    )

    embed.add_field(name="📧 Event", value=event_name, inline=False)
    embed.add_field(name="📍 Location", value=event_location, inline=False)
    embed.add_field(
        name="📅 Dates", value=f"{date_format(event_start_date)} to {date_format(event_end_date)}", inline=False)
    embed.add_field(
        name="⏰ Time", value=f"{event_start_time} to {event_end_time}", inline=False)

    # Questionable if this even works...
    embed.timestamp = datetime.now()
    timezone = find_timezone(embed.timestamp)

    # Sending the embed
    view = CreatePrivateView(
        event_details=event_details, uiud=uiud, user_name=user_name, timezone=timezone)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    await view.future
    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        # Message might be already deleted, ignore this exception
        pass
    except Exception as e:
        print(f"Error in deleting message after submit: {e}")


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
    uiud = str(interaction.user.id)
    user_name = interaction.user.name

    event_details = {
        'event_name': event_name,
        'event_location': event_location,
        'event_start_date': event_start_date,
        'event_end_date': event_end_date,
        'event_start_time': event_start_time,
        'event_end_time': event_end_time
    }
    embed = discord.Embed(
        title="Event Confirmation",
        description="Please confirm the event creation:",
        color=discord.Color.blue()
    )
    print("event start date: ", event_start_date)
    print("event end date: ", event_end_date)

    embed.add_field(name="📧 Event", value=event_name, inline=False)
    embed.add_field(name="📍 Location", value=event_location, inline=False)
    embed.add_field(
        name="📅 Dates", value=f"{date_format(event_start_date)} to {date_format(event_end_date)}", inline=False)
    embed.add_field(
        name="⏰ Time", value=f"{event_start_time} to {event_end_time}", inline=False)

    embed.timestamp = datetime.now()
    timezone = find_timezone(embed.timestamp)

    view = CreateServerView(
        event_details=event_details,
        uiud=uiud,
        user_name=user_name,
        gid=gid,
        timezone=timezone
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    await view.future
    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        # Message might be already deleted, ignore this exception
        pass
    except Exception as e:
        print(f"Error in deleting message after submit: {e}")


# delete event
@bot.tree.command(name="delete_event")
@app_commands.describe(
    event_id="Event ID"
)
async def delete_event(interaction: discord.Interaction, event_id: int):
    uiud = str(interaction.user.id)
    gid = interaction.guild_id

    async with bot.pool.acquire() as conn:
        # Check if event exists
        event = await conn.fetchrow("SELECT * FROM event WHERE eid = $1 AND uiud = $2", event_id, uiud)

        if event:

            embed = discord.Embed(
                title="Event Deletion Confirmation", color=discord.Color.red())
            embed.add_field(name="Event ID", value=event_id)
            embed.add_field(name="Event Name", value=event['meetingname'])
            embed.set_footer(
                text="Please confirm if you want to delete this event.")

            view = DeleteView(interaction, event_id, event['meetingname'], bot)

            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            await view.wait()
            try:
                await interaction.delete_original_response()
            except discord.NotFound:
                # Message might be already deleted, ignore this exception
                pass
            except Exception as e:
                print(f"Error in deleting message after submit: {e}")
        else:
            await interaction.response.send_message(
                f"{interaction.user.mention}, event '{event_id}' not found or you don't have permission to delete it.",
                ephemeral=True
            )


# List server events
@bot.tree.command(name="list_server_events", description="This command lists all server events happening in the future.")
async def list_server_events(interaction: discord.Interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message("Server events can only be displayed while using this command in a server.", ephemeral=True)
        return

    async with bot.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT eid, meetingname, location, timestart, timeend FROM event WHERE gid = $1",
            interaction.guild_id
        )

    if not rows:
        await interaction.response.send_message(f"No events available for {interaction.guild.name}.")
        return

    # Paginate rows into pages of events
    events_per_page = 4
    pages = [rows[i:i + events_per_page]
             for i in range(0, len(rows), events_per_page)]

    def create_embed(page_rows):
        embed = discord.Embed(title=f"Events for {interaction.guild.name}")

        embed.timestamp = datetime.now()
        timezone = find_timezone(embed.timestamp)

        for row in page_rows:
            start_time_info = row['timestart'].strftime(
                '%Y-%m-%d %H:%M:%S'
            )
            end_time_info = row['timeend'].strftime(
                '%Y-%m-%d %H:%M:%S'
            )
            start_date, start_time = start_time_info.split(' ')
            end_date, end_time = end_time_info.split(' ')

            start_date, end_date = date_format(
                start_date), date_format(end_date)
            embed.add_field(name=f"{row['meetingname']} (ID: {row['eid']})",
                            value=f"\n📍 Location: {row['location']} \n 📅 Date: {start_date} to {end_date} \n⌚ Time: {convert_locale(start_time, timezone)} to {convert_locale(end_time, timezone)}.\n", inline=False)
        return embed

    view = PaginationView(pages, create_embed, interaction)
    embed = create_embed(pages[0])
    await interaction.response.send_message(embed=embed, view=view)


# list out all events (private, public)
@bot.tree.command(name="show_events", description="This lists all events you have created and/or signed up for.")
async def show_events(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

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

    if not rows:
        await interaction.followup.send("You have no events scheduled.", ephemeral=True)
        return

    events_per_page = 4
    pages = [rows[i:i + events_per_page]
             for i in range(0, len(rows), events_per_page)]

    def create_embed(page_rows):
        embed = discord.Embed(title="Your Events")
        embed.timestamp = datetime.now()
        timezone = find_timezone(embed.timestamp)

        for row in page_rows:
            start_time_info = row['timestart'].strftime('%Y-%m-%d %H:%M:%S')
            end_time_info = row['timeend'].strftime('%Y-%m-%d %H:%M:%S')
            start_date, start_time = start_time_info.split(' ')
            end_date, end_time = end_time_info.split(' ')

            start_time, end_time = convert_locale(
                start_time, timezone), convert_locale(end_time, timezone)
            start_date, end_date = date_format(
                start_date), date_format(end_date)

            embed.add_field(
                name=f"{row['meetingname']} (ID: {row['eid']})",
                value=f"📍 Location: {row['location']}\n 📅 Date: {start_date} to {end_date}\n ⏲ Time: {start_time} to {end_time}",
                inline=False
            )

        return embed

    # Initialize and send the first page
    view = PaginationView(pages, create_embed, interaction)
    embed = create_embed(pages[0])
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


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
        user = await conn.fetchrow("SELECT * FROM \"user\" WHERE uiud = $1", uiud)
        if user is None:
            await conn.execute("INSERT INTO \"user\" (uiud, name) VALUES ($1, $2)", uiud, interaction.user.name)

        event = await conn.fetchrow(
            # AND gid = $2",
            "SELECT meetingname, eid, location, timestart, timeend FROM event WHERE eid = $1",
            event_number  # ,gid
        )

        if event:
            start_time_info = event['timestart'].strftime(
                '%Y-%m-%d %H:%M:%S'
            )
            end_time_info = event['timeend'].strftime(
                '%Y-%m-%d %H:%M:%S'
            )
            start_date, start_time = start_time_info.split(' ')
            end_date, end_time = end_time_info.split(' ')
            start_date, end_date = date_format(
                start_date), date_format(end_date)

            embed = discord.Embed(title=event['meetingname'])
            embed.timestamp = datetime.now()
            timezone = find_timezone(embed.timestamp)
            # embed = discord.Embed(name=f"{event['meetingname']}

            embed.add_field(name=f"(ID: {event['eid']})",
                            value=f"\n📍 Location: {event['location']} \n 📅 Date: {start_date} to {end_date} \n⌚ Time: {convert_locale(start_time, timezone)} to {convert_locale(end_time, timezone)}.\n", inline=False)
            view = NotificationView(
                event['eid'], event['meetingname'], interaction.user.id, uiud, gid
            )

            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            await view.future

            try:
                await interaction.delete_original_response()
            except discord.NotFound:
                # Message might be already deleted, ignore this exception
                pass
            except Exception as e:
                print(f"Error in deleting message after submit: {e}")

        else:
            await interaction.response.send_message(
                f"Event number {event_number} is either not in this server, or the event number is invalid",
                ephemeral=True
            )


@bot.tree.command(name="remove_notification")
@app_commands.describe(event_id="The event number you want to stop getting notifications for")
# Removes notification based on event id
async def remove_notification(interaction: discord.Interaction, event_id: int):
    uiud = str(interaction.user.id)

    # Create an embed for the confirmation message
    embed = discord.Embed(
        title="Remove Notification",
        description=f"Do you want to remove the notification for event ID {event_id}?",
        color=discord.Color.dark_red()
    )

    view = RemoveNotificationView(event_id, uiud, interaction)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    await view.wait()
    await view.future
    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        # Message might be already deleted, ignore this exception
        pass
    except Exception as e:
        print(f"Error in deleting message after submit: {e}")


async def notification_role(server, user_id, role_name):
    if server:
        existing_role = discord.utils.get(server.roles, name=role_name)
        if not existing_role:
            # Create the role
            try:
                new_role = await server.create_role(name=role_name, mentionable=True, reason="New event role")

            except discord.Forbidden:
                print(
                    "The bot does not have permissions to create roles. Please contact your server admins for help.")
                return None
        else:
            new_role = existing_role
            if not new_role.mentionable:
                try:
                    await new_role.edit(mentionable=True)
                except discord.Forbidden:
                    print(
                        "The bot does not have permissions to edit roles. Please contact your server admins for help.")
                    return None

        member = server.get_member(user_id)
        if member:
            try:
                await member.add_roles(new_role, reason="Assigned for event signup")
                return new_role
            except discord.Forbidden:
                print(
                    "The bot does not have permissions to assign roles. Please contact your server admins for help.")
        else:
            print("Member not found in the server.")
    return None


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
        if new_meetingname is not None:
            fields_to_update['meetingname'] = new_meetingname
        if new_location is not None:
            fields_to_update['location'] = new_location

        # Handling date and time updates
        try:
            if new_datestart or new_timestart:
                existing_start = event['timestart']
                new_start_date = new_datestart if new_datestart else existing_start.strftime(
                    "%Y-%m-%d")
                new_start_time = new_timestart if new_timestart else existing_start.strftime(
                    "%H:%M:%S")
                new_eventstart = datetime.strptime(
                    f"{new_start_date} {new_start_time}", "%Y-%m-%d %H:%M:%S")
                new_eventstart = (new_eventstart)
                fields_to_update['timestart'] = new_eventstart

            if new_dateend or new_timeend:
                existing_end = event['timeend']
                new_end_date = new_dateend if new_dateend else existing_end.strftime(
                    "%Y-%m-%d")
                new_end_time = new_timeend if new_timeend else existing_end.strftime(
                    "%H:%M:%S")
                new_eventend = datetime.strptime(
                    f"{new_end_date} {new_end_time}", "%Y-%m-%d %H:%M:%S")
                new_eventend = (new_eventend)
                fields_to_update['timeend'] = new_eventend

        except ValueError as e:
            await interaction.response.send_message("Invalid date or time format.", ephemeral=True)
            return

        if fields_to_update:
            set_parts = [f"{key} = ${i + 1}" for i,
                         key in enumerate(fields_to_update.keys())]
            values = list(fields_to_update.values())
            values.append(event_id)
            update_query = f"UPDATE event SET {', '.join(set_parts)} WHERE eid = ${len(values)}"
            await conn.execute(update_query, *values)
            await interaction.response.send_message("Event updated successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("No changes specified for the event.", ephemeral=True)


bot.run(os.getenv("DISCORD_TOKEN"))
