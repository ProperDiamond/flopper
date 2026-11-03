"""Discord bot for practising NSW HSC Chemistry short-answer questions."""

import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from chemistry_quiz import (
    ACTIVE_MCQ_RACES,
    _missing_bot_permissions,
    daily_settings,
    has_daily_post,
    post_question,
    play_mcq_race,
    record_daily_post,
    register_chemistry_quiz,
)


load_dotenv()

OWNER_ID = 417216848720035862


class ChemistryClient(discord.Client):
    async def setup_hook(self) -> None:
        await super().setup_hook()
        print("Connecting to Discord and syncing chemistry commands…", flush=True)
        synced = await tree.sync()
        print(f"Synced {len(synced)} chemistry command(s).", flush=True)
        if not daily_question_poster.is_running():
            daily_question_poster.start()


intents = discord.Intents.default()
client = ChemistryClient(intents=intents)
tree = app_commands.CommandTree(client)
register_chemistry_quiz(tree)


_daily_errors_logged: set[tuple[int, str]] = set()


@tasks.loop(seconds=30)
async def daily_question_poster() -> None:
    for (
        guild_id, channel_id, hour, minute, timezone_name, interval_hours,
        question_mode, module, topic,
    ) in daily_settings():
        try:
            timezone = ZoneInfo(timezone_name)
            now = datetime.now(timezone)
            local_date = now.date().isoformat()
            if interval_hours == 24:
                if (now.hour, now.minute) < (hour, minute):
                    continue
                schedule_key = local_date
            else:
                slot_hour = (now.hour // interval_hours) * interval_hours
                due_at = now.replace(
                    hour=slot_hour, minute=minute, second=0, microsecond=0
                )
                if now < due_at:
                    continue
                schedule_key = f"{local_date}T{slot_hour:02d}:{minute:02d}"
            if has_daily_post(guild_id, schedule_key):
                continue

            channel = client.get_channel(channel_id)
            if channel is None:
                channel = await client.fetch_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                raise TypeError(f"Configured channel {channel_id} is not a server text channel")

            if question_mode == "mcq_race":
                bot_member = channel.guild.me
                if bot_member is None:
                    raise PermissionError("Bot membership in this server is unavailable")
                permissions = channel.permissions_for(bot_member)
                missing = [
                    label
                    for attribute, label in (
                        ("send_messages", "Send Messages"),
                        ("embed_links", "Embed Links"),
                        ("attach_files", "Attach Files"),
                    )
                    if not getattr(permissions, attribute)
                ]
                if missing:
                    raise PermissionError(
                        "Missing channel permissions: " + ", ".join(missing)
                    )
                if channel.id in ACTIVE_MCQ_RACES:
                    continue
                ACTIVE_MCQ_RACES.add(channel.id)
                record_daily_post(guild_id, schedule_key, channel_id, 0, 0)
                asyncio.create_task(
                    _run_scheduled_mcq_race(channel),
                    name=f"scheduled-mcq-race-{guild_id}-{schedule_key}",
                )
                _daily_errors_logged.discard((guild_id, local_date))
                continue

            missing = _missing_bot_permissions(channel)
            if missing:
                raise PermissionError("Missing channel permissions: " + ", ".join(missing))

            message, thread = await post_question(channel, module, topic)
            record_daily_post(guild_id, schedule_key, channel_id, message.id, thread.id)
            _daily_errors_logged.discard((guild_id, local_date))
            print(
                f"Posted scheduled question for guild {guild_id} in thread {thread.id} "
                f"({schedule_key}).",
                flush=True,
            )
        except Exception as error:
            error_key = (guild_id, datetime.now().date().isoformat())
            if error_key not in _daily_errors_logged:
                print(f"Daily question failed for guild {guild_id}: {error}", flush=True)
                _daily_errors_logged.add(error_key)


async def _run_scheduled_mcq_race(channel: discord.TextChannel) -> None:
    try:
        await play_mcq_race(channel, rounds=5)
    except Exception as error:
        print(f"Scheduled MCQ race failed in channel {channel.id}: {error}", flush=True)
    finally:
        ACTIVE_MCQ_RACES.discard(channel.id)


@daily_question_poster.before_loop
async def wait_for_discord_ready() -> None:
    await client.wait_until_ready()


@tree.command(name="sync", description="Owner only")
async def sync_commands(interaction: discord.Interaction) -> None:
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "This command is only for the owner of this bot.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    synced = await tree.sync()
    await interaction.followup.send(
        f"Command tree synced ({len(synced)} commands).", ephemeral=True
    )


@client.event
async def on_ready() -> None:
    print(f"Chemistry bot online as {client.user}", flush=True)


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN is missing from the environment or .env file")

client.run(token)
