import requests
import json
from datetime import datetime, timedelta
import discord
from discord import app_commands
import pytz
import aiohttp
from dateutil.relativedelta import relativedelta
from bs4 import BeautifulSoup
import asyncio
import os
import random
import logging
from typing import List, Dict, Optional  # Import typing modules for compatibility

# Initialize logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Initialize Discord client and intents
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Constants
whitelist = [861158345842884638, 712179834700431440, 277479464621965313, 
             521724336499851267, 372975036669362188, 691010113535869028, 373372334603501578]
ANNOUNCEMENT_CHANNELS = [1318209002097610857]
channel_messages: Dict[int, Dict[str, int]] = {}
file_lock = asyncio.Lock()

# Ensure votes.json exists
def initialize_votes_file():
    try:
        if not os.path.exists('votes.json'):
            with open('votes.json', 'w') as f:
                json.dump({}, f)
    except Exception as e:
        logging.error(f"Error initializing votes file: {str(e)}")

# Helper function to safely load votes
async def load_votes() -> Dict:
    async with file_lock:
        try:
            with open("votes.json", "r") as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Error loading votes: {str(e)}")
            return {}

# Helper function to safely save votes
async def save_votes(votes: Dict):
    async with file_lock:
        try:
            with open("votes.json", "w") as file:
                json.dump(votes, file, indent=4)
        except Exception as e:
            logging.error(f"Error saving votes: {str(e)}")

# Save channel_messages to a file
async def save_channel_messages():
    async with file_lock:
        try:
            with open("channel_messages.json", "w") as file:
                json.dump(channel_messages, file, indent=4)
        except Exception as e:
            logging.error(f"Error saving channel messages: {str(e)}")

# Load channel_messages from a file
async def load_channel_messages() -> Dict[int, Dict[str, int]]:
    async with file_lock:
        try:
            with open("channel_messages.json", "r") as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Error loading channel messages: {str(e)}")
            return {}

# Autocomplete function for CTF names
async def ctf_name_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36"
            "(KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36"
        }

        now = datetime.utcnow().timestamp()
        twenty_five_days = datetime.utcnow() + relativedelta(days=+25)
        twenty_five_days = twenty_five_days.timestamp()

        r = requests.get(
            "https://ctftime.org/api/v1/events/?limit=100"
            + "&start="
            + str(int(now))
            + "&finish="
            + str(int(twenty_five_days)),
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()

        # Filter CTF names based on user input
        ctf_names = [event["title"] for event in data if current.lower() in event["title"].lower()]
        return [app_commands.Choice(name=name, value=name) for name in ctf_names[:25]]  # Limit to 25 choices

    except Exception as e:
        logging.error(f"Error fetching CTF names: {str(e)}")
        return []  # Return an empty list on error

# Define the command with autocomplete
@tree.command(name="addctfchannels", description="Add a CTF channel by name")
@app_commands.autocomplete(ctf_name=ctf_name_autocomplete)
async def add_ctf_channels(interaction: discord.Interaction, ctf_name: str):
    if interaction.user.id in whitelist:
        try:
            # Check if the user has manage_channels and manage_roles permissions
            if not interaction.user.guild_permissions.manage_channels or not interaction.user.guild_permissions.manage_roles:
                await interaction.response.send_message(
                    "❌ You don't have permission to manage channels or roles!", ephemeral=True
                )
                return

            # Check if the bot has manage_channels and manage_roles permissions
            if not interaction.guild.me.guild_permissions.manage_channels or not interaction.guild.me.guild_permissions.manage_roles:
                await interaction.response.send_message(
                    "❌ I don't have permission to manage channels or roles!", ephemeral=True
                )
                return

            # Create or get the CTF category
            ctf_category = discord.utils.get(interaction.guild.categories, name="CTF Competition") or await interaction.guild.create_category("CTF Competition")
            
            # Create a role for the CTF channel
            ctf_role = discord.utils.get(interaction.guild.roles, name=f"CTF-{ctf_name}") or await interaction.guild.create_role(name=f"CTF-{ctf_name}")

            # Set up channel permissions
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                ctf_role: discord.PermissionOverwrite(read_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True)
            }
            
            # Create the CTF channel
            channel = await interaction.guild.create_text_channel(
                ctf_name,
                category=ctf_category,
                overwrites=overwrites
            )
            
            # Send announcement messages
            for announcement_id in ANNOUNCEMENT_CHANNELS:
                announcement_channel = client.get_channel(announcement_id)
                if announcement_channel:
                    announce_msg = await announcement_channel.send(
                        f"""🏁 New CTF: **{ctf_name}** is now available!
React with 👍 to gain access."""
                    )
                    await announce_msg.add_reaction("👍")
                    channel_messages[announce_msg.id] = {'channel_id': channel.id, 'role_id': ctf_role.id}
            
            await save_channel_messages()  # Persist channel_messages
            
            # Send DM to user about channel creation
            try:
                await interaction.user.send(f"✅ New channel created: **{ctf_name}**")
            except discord.Forbidden:
                pass  # Unable to DM user
                
            await interaction.response.send_message(f"✅ Created channel for **{ctf_name}**", ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Not authorized", ephemeral=True)

async def fetch_upcoming_events():
    start = int(datetime.now().timestamp())
    end = int((datetime.now() + timedelta(weeks=2)).timestamp())
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36"
                      "(KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f'https://ctftime.org/api/v1/events/?limit=5&start={start}&finish={end}',
            headers=headers
        ) as response:
            return await response.json() if response.status == 200 else None

@tree.command(name="upcoming", description="Get the upcoming CTF events in the next 2 weeks.")
async def upcoming(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        
        # Fetch up to 10 events
        start = int(datetime.now().timestamp())
        end = int((datetime.now() + timedelta(weeks=2)).timestamp())
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36"
                         "(KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'https://ctftime.org/api/v1/events/?limit=10&start={start}&finish={end}',
                headers=headers
            ) as response:
                events = await response.json() if response.status == 200 else None

        if not events:
            await interaction.followup.send("No upcoming CTF events found.")
            return

        embeds = []
        for event in events:
            start_time = datetime.strptime(event['start'], "%Y-%m-%dT%H:%M:%S%z")
            end_time = datetime.strptime(event['finish'], "%Y-%m-%dT%H:%M:%S%z")
            duration = end_time - start_time
            duration_str = f"{duration.days}d {duration.seconds//3600}h"
            
            embed = discord.Embed(
                title=event['title'],
                color=random.randint(0, 0xFFFFFF)
            )
            
            description = (
                f"**Event ID:** {event['id']}\n"
                f"**Weight:** {event['weight']}\n"
                f"**Duration:** {duration_str}\n"
                f"**Start Time:** {start_time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                f"**End Time:** {end_time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                f"**Format:** {event['format']}\n"
                f"**[More Info]({event['url']})**"
            )
            embed.description = description
            
            if event.get('logo'):
                embed.set_thumbnail(url=event['logo'])
                
            embeds.append(embed)
            
        await interaction.followup.send(embeds=embeds)

    except requests.RequestException as e:
        await interaction.followup.send(f"❌ Error fetching CTF events: {str(e)}")
    except Exception as e:
        await interaction.followup.send(f"❌ An unexpected error occurred: {str(e)}")


@tree.command(
    name="moreinfo",
    description="Get more information about a specific CTF by CTF Time ID",
)
async def moreinfo(interaction: discord.Interaction, eventid: int):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36"
        }
        r = requests.get(
            "https://ctftime.org/api/v1/events/" + str(eventid) + "/", headers=headers
        )
        r.raise_for_status()
        data = r.json()

        event_title = data["title"]
        event_url = data["url"]
        event_start = data["start"]
        event_end = data["finish"]
        event_description = data["description"]
        event_image = data["logo"]

        event_start = datetime.strptime(event_start, "%Y-%m-%dT%H:%M:%S%z")
        event_start = event_start.timestamp()

        event_end = datetime.strptime(event_end, "%Y-%m-%dT%H:%M:%S%z")
        event_end = event_end.timestamp()

        embed = discord.Embed(
            title=event_title,
            url=event_url,
            description=event_description,
            type="article",
        )

        embed.set_thumbnail(url=event_image)

        embed.add_field(name="Start Date", value="<t:" + str(int(event_start)) + ":d>", inline=True)
        embed.add_field(name="End Date", value="<t:" + str(int(event_end)) + ":d>", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="Start Time", value="<t:" + str(int(event_start)) + ":t>", inline=True)
        embed.add_field(name="End Time", value="<t:" + str(int(event_end)) + ":t>", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="When?", value="<t:" + str(int(event_start)) + ":R>", inline=False)

        await interaction.response.send_message(embed=embed)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            await interaction.response.send_message(
                f"❌ CTF with ID {eventid} not found.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Error fetching CTF info: {str(e)}", ephemeral=True
            )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ An unexpected error occurred: {str(e)}", ephemeral=True
        )

@tree.command(
    name="ctfparticipants",
    description="Get a list of people participating in a CTF event.",
)
async def ctfparticipants(interaction: discord.Interaction, channel: discord.TextChannel):
    try:
        # Find the announcement message associated with the CTF channel
        announcement_message_id = None
        for msg_id, data in channel_messages.items():
            if data['channel_id'] == channel.id:
                announcement_message_id = msg_id
                break

        if not announcement_message_id:
            await interaction.response.send_message(
                f"No announcement message found for **{channel.name}**.", ephemeral=True
            )
            return

        # Fetch the announcement message
        announcement_channel = None
        for channel_id in ANNOUNCEMENT_CHANNELS:
            announcement_channel = client.get_channel(channel_id)
            if announcement_channel:
                try:
                    announcement_message = await announcement_channel.fetch_message(announcement_message_id)
                    break
                except discord.NotFound:
                    continue

        if not announcement_message:
            await interaction.response.send_message(
                f"Announcement message for **{channel.name}** not found.", ephemeral=True
            )
            return

        # Get users who reacted with 👍
        participants = []
        for reaction in announcement_message.reactions:
            if str(reaction.emoji) == "👍":
                async for user in reaction.users():
                    if not user.bot:  # Exclude the bot itself
                        participants.append({
                            "id": user.id,
                            "username": user.name,
                            "displayname": user.display_name
                        })
                break  # We only care about the 👍 reaction

        if not participants:
            await interaction.response.send_message(
                f"No participants found for **{channel.name}**.", ephemeral=True
            )
            return

        # Format the list of participants
        message = (
            f"> # **{channel.name}**\n"
            f"> ## Participants:\n"
        )
        for participant in participants:
            message += (
                f"> **{participant['displayname']}** ({participant['username']})\n"
            )

        await interaction.response.send_message(message, ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(
            f"❌ Error retrieving participants: {str(e)}", ephemeral=True
        )

@tree.command(name="createevent", description="Create an event with a name, start time, duration, and CTF code.")
async def createevent(
    interaction: discord.Interaction,
    event_name: str,
    start_in_hours: int,
    duration_hours: int,
    ctf_code: str,
):
    try:
        # Validate start_in_hours and duration_hours
        if start_in_hours < 0 or duration_hours < 0:
            await interaction.response.send_message(
                "❌ Start time and duration must be positive numbers.", ephemeral=True
            )
            return

        # Calculate the start time
        start_time = datetime.utcnow() + relativedelta(hours=+start_in_hours)
        end_time = start_time + relativedelta(hours=+duration_hours)

        # Format the event details
        event_details = (
            f"**Event Name:** {event_name}\n"
            f"**CTF Code:** {ctf_code}\n"
            f"**Start Time:** <t:{int(start_time.timestamp())}:f>\n"
            f"**End Time:** <t:{int(end_time.timestamp())}:f>\n"
            f"**Duration:** {duration_hours} hours"
        )

        # Create an embed for the event
        embed = discord.Embed(
            title="🎉 New CTF Event Created!",
            description=event_details,
            color=discord.Color.green()
        )

        # Send the embed as a response
        await interaction.response.send_message(embed=embed)

    except Exception as e:
        await interaction.response.send_message(
            f"❌ An error occurred while creating the event: {str(e)}", ephemeral=True
        )

@tree.command(name="archivectf", description="Archive a CTF channel.")
async def archivectf(interaction: discord.Interaction, channel: discord.TextChannel):
    if interaction.user.id in whitelist:
        try:
            archive_category = discord.utils.get(interaction.guild.categories, name="Archived CTFs")
            if not archive_category:
                try:
                    archive_category = await interaction.guild.create_category("Archived CTFs")
                except discord.Forbidden:
                    await interaction.response.send_message(
                        "❌ I don't have permission to create categories!", ephemeral=True
                    )
                    return

            await channel.edit(category=archive_category)
            await interaction.response.send_message(f"Archived {channel.name}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
    else:
        await interaction.response.send_message("Not authorized", ephemeral=True)

@tree.command(name="delchannel", description="Delete a channel by name.")
async def delchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if interaction.user.id in whitelist:
        try:
            channel_name = channel.name
            try:
                await channel.delete()
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I don't have permission to delete this channel!", ephemeral=True
                )
                return

            await interaction.response.send_message(
                f"Successfully deleted channel: {channel_name}", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Error deleting channel: {str(e)}", ephemeral=True
            )
    else:
        await interaction.response.send_message(
            "You are not authorized to use this command!", ephemeral=True
        )

@tree.command(name="delctfcategory", description="Delete a category and its channels by name.")
async def delctfcategory(interaction: discord.Interaction, category: discord.CategoryChannel):
    if interaction.user.id in whitelist:
        try:
            channels = category.channels
            
            # Delete all channels in the category
            for channel in channels:
                try:
                    await channel.delete()
                except discord.Forbidden:
                    await interaction.response.send_message(
                        f"❌ I don't have permission to delete {channel.name}!", ephemeral=True
                    )
                    return
            
            # Delete the category itself
            try:
                await category.delete()
            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I don't have permission to delete the category!", ephemeral=True
                )
                return
            
            await interaction.response.send_message(
                f"Successfully deleted category: {category.name}", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Error deleting category: {str(e)}", ephemeral=True
            )
    else:
        await interaction.response.send_message(
            "You are not authorized to use this command!", ephemeral=True
        )

@client.event
async def on_ready():
    initialize_votes_file()
    global channel_messages
    channel_messages = await load_channel_messages()
    try:
        await tree.sync()
    except Exception as e:
        logging.error(f"Error syncing commands: {str(e)}")
    logging.info("Bot is ready and running!")

# Run the bot
if __name__ == "__main__":
    token = os.environ['token']
    if not token:
        logging.error("Error: Discord token not found in secrets!")
        exit(1)
        
    client.run(token)
