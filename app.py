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
from tz_convert import local_to_utc, utc_to_local, time_format_locale, date_format, find_timezone, convert_locale
from dotenv import load_dotenv
import pytz

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
        print("Error ", e)


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
        event_name = self.event_details['event_name']
        event_location = self.event_details['event_location']
        event_start = f"{self.event_details['event_start_date']} {local_to_utc(self.event_details['event_start_time'])}"
        event_end = f"{self.event_details['event_end_date']} {local_to_utc(self.event_details['event_end_time'])}"

        try:
            event_start = datetime.strptime(event_start, "%Y-%m-%d %H:%M:%S")
            event_end = datetime.strptime(event_end, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            await interaction.response.send_message(
                "Invalid timestamps, please make sure your timestamps follow the format (YYYY-MM-DD) for date and (HH:MM:SS) for time.", ephemeral=True)
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

        # Parse date and time
        try:
            event_start = datetime.strptime(event_start, "%Y-%m-%d %H:%M:%S")
            event_end = datetime.strptime(event_end, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            await interaction.response.send_message(
                "Invalid timestamps, please make sure your timestamps follow the format (YYYY-MM-DD) for date and (HH:MM:SS) for time.",
                ephemeral=True)
            self.future.set_result(True)
            return

        # Database operations
        async with bot.pool.acquire() as conn:
            # Check for overlapping events
            overlap = await conn.fetchrow(
                "SELECT * FROM event WHERE gid = $1 AND timestart < $3 AND timeend > $2",
                self.gid, event_start, event_end)

            if overlap:
                await interaction.response.send_message(
                    f"{interaction.user.mention}, there is an overlapping event.",
                    ephemeral=True)
                self.future.set_result(True)
                return

            # Insert new event
            eid = await conn.fetchval(
                "INSERT INTO event (uiud, gid, meetingname, location, timestart, timeend) VALUES ($1, $2, $3, $4, $5, $6) RETURNING eid",
                self.uiud, self.gid, event_name, event_location, event_start, event_end)

            if eid:
                await conn.execute(
                    "INSERT INTO scheduled (uiud, eid, status, notification) VALUES ($1, $2, 'Yes', 0)",
                    self.uiud, eid)
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
            embed.add_field(name=f"{row['meetingname']} (ID: {row['eid']})",
                            value=f"\n📍 Location: {row['location']} \n ⌚ Time: {convert_locale(row['timestart'], timezone)} to {convert_locale(row['timeend'], timezone)}.\n", inline=False)
        return embed

    view = PaginationView(pages, create_embed, interaction)
    embed = create_embed(pages[0])
    await interaction.response.send_message(embed=embed, view=view)


# list out all events (outputs only to original user) -- TO-DO -> NEEDS TO BE FIXED
@bot.tree.command(name="show_events", description="This lists all events you have created and/or signed up for.")
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
            response = "Here are your events:\n"
            for row in rows:
                start_time_info = row['timestart'].strftime(
                    '%Y-%m-%d %H:%M:%S'
                )
                end_time_info = row['timeend'].strftime(
                    '%Y-%m-%d %H:%M:%S'
                )
                start_date, start_time = start_time_info.split(' ')
                end_date, end_time = end_time_info.split(' ')

                start_time, end_time = utc_to_local(
                    start_time), utc_to_local(end_time)
                start_date, end_date = date_format(
                    start_date), date_format(end_date)

                response += f"{row['meetingname']} (ID: {row['eid']}) at {row['location']}, {start_date} to {end_date} from {start_time} to {end_time}\n"
        else:
            response = "You have no events scheduled."

        await interaction.response.send_message(response, ephemeral=True)


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
            "SELECT eid, meetingname FROM event WHERE eid = $1 AND gid = $2",
            event_number, gid
        )

        if event:
            embed = discord.Embed(title=event['meetingname'])
            embed.add_field(name="Event ID", value=event['eid'], inline=True)
            # Add more fields as necessary
            embed.timestamp = datetime.now()
            timezone = find_timezone(embed.timestamp)

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

# @bot.tree.command(name="get_notified")
# @app_commands.describe(event_number="The event number you want to get notified for")
# async def get_notified(interaction: discord.Interaction, event_number: int):
#     # Ensure this is used within a server
#     if interaction.guild_id is None:
#         await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
#         return

#     uiud = str(interaction.user.id)
#     gid = interaction.guild_id

#     async with bot.pool.acquire() as conn:
#         user = await conn.fetchrow("SELECT * FROM \"user\" WHERE uiud = $1", uiud)
#         if user is None:
#             await conn.execute("INSERT INTO \"user\" (uiud, name) VALUES ($1, $2)", uiud, interaction.user.name)
#         # Check if the event exists in the server
#         event = await conn.fetchrow(
#             "SELECT eid, meetingname FROM event WHERE eid = $1 AND gid = $2",
#             event_number, gid
#         )

#         if event:
#             existing_signup = await conn.fetchrow(
#                 "SELECT * FROM scheduled WHERE uiud = $1 AND eid = $2",
#                 uiud, event['eid']
#             )

#             if not existing_signup:
#                 await conn.execute(
#                     "INSERT INTO scheduled (uiud, eid, status, notification) VALUES ($1, $2, 'Yes', 0)",
#                     # right now im gonna do it so 'Yes' just means signed up and 0 means not notified, you would change to 1 once they have been, and then they wont get pinged again that way.
#                     uiud, event['eid']
#                 )
#                 role_name = f"Event {event['eid']}"
#                 await notification_role(interaction.guild, interaction.user.id, role_name)
#                 await interaction.response.send_message(
#                     f"You have been signed up for '{event['meetingname']}'.",
#                     ephemeral=True
#                 )
#             else:
#                 await interaction.response.send_message(
#                     f"You are already signed up for '{event['meetingname']}'.",
#                     ephemeral=True
#                 )
#         else:
#             await interaction.response.send_message(
#                 f"Event number {event_number} is either not in this server, or the event number is invalid",
#                 ephemeral=True
#             )


@bot.tree.command(name="stop_notifications")
@app_commands.describe(event_id="The event number you want to stop getting notifications for")
async def stop_notifications(interaction: discord.Interaction, event_id: int):
    uiud = str(interaction.user.id)
    server = interaction.guild

    async with bot.pool.acquire() as conn:
        # Check if the user is signed up for event
        signup = await conn.fetchrow(
            "SELECT * FROM scheduled WHERE uiud = $1 AND eid = $2",
            uiud, event_id
        )

        if signup:
            # Remove the user from the scheduled table
            await conn.execute(
                "DELETE FROM scheduled WHERE uiud = $1 AND eid = $2",
                uiud, event_id
            )

            # Attempt to remove the role from server user
            if server:
                role_name = f"Event {event_id}"
                role = discord.utils.get(server.roles, name=role_name)
                member = server.get_member(int(uiud))
                if role and member:
                    try:
                        await member.remove_roles(role, reason=f"User opted out of event {event_id} notifications")
                    except discord.Forbidden:
                        await interaction.response.send_message(
                            "The bot does not have permissions to delete roles, and the notification role has not been removed. Please contact your server admins for help.",
                            ephemeral=True
                        )
                        return
                    except discord.HTTPException as e:
                        await interaction.response.send_message(
                            f"Failed to delete notification role: {e}, please notify your admins to delete this role.",
                            ephemeral=True
                        )
                        return
            else:
                await interaction.response.send_message("Please use delete event when removing personal events, as no role is created for personal event notifications.", ephemeral=True)
                return

            await interaction.response.send_message(
                f"You will no longer receive notifications for event ID {event_id}.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"You are not signed up for notifications for event ID {event_id}, or it does not exist for you.",
                ephemeral=True
            )


async def notification_role(server, user_id, role_name):
    if server:
        existing_role = discord.utils.get(server.roles, name=role_name)
        if not existing_role:
            # Create the role
            try:
                new_role = await server.create_role(name=role_name, reason="New event role")
            except discord.Forbidden:
                print(
                    "The bot does not have permissions to create roles. Please contact your server admins for help.")
                return None
        else:
            new_role = existing_role

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
