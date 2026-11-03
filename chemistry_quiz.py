"""Post real HSC Chemistry short-answer question images to Discord."""

import asyncio
import io
import random
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands


DB_PATH = Path(__file__).with_name("chemistry.db")
DEFAULT_TIMEZONE = "Australia/Sydney"
DEFAULT_HOUR = 9
DEFAULT_MINUTE = 0
MCQ_ANSWER_TIMEOUT = 45
ACTIVE_MCQ_RACES: set[int] = set()


SUPPORTED_INTERVALS = (1, 2, 3, 4, 6, 8, 12, 24)
MODULE_CHOICES = (
    "Module 2: Introduction to Quantitative Chemistry",
    "Module 4: Drivers of Reactions",
    "Module 5: Equilibrium and Acid Reactions",
    "Module 6: Acid/base Reactions",
    "Module 7: Organic Chemistry",
    "Module 8: Applying Chemical Ideas",
)
TOPIC_CHOICES = (
    "Alcohols", "Analysis of Inorganic Substances", "Analysis of Organic Substances",
    "Calculating the Equilibrium Constant", "Chemical Synthesis and Design",
    "Energy Changes in Chemical Reactions", "Entropy and Gibbs Free Energy",
    "Factors that Affect Equilibrium", "Gas Laws", "Nomenclature", "Polymers",
    "Products of Reactions Involving Hydrocarbons", "Properties of Acids and Bases",
    "Quantitative Analysis", "Reactions of Organic Acids and Bases",
    "Solution Equilibria", "Static and Dynamic Equilibrium",
    "Using Brønsted–Lowry Theory",
)


def ensure_daily_tables() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                hour INTEGER NOT NULL DEFAULT 9,
                minute INTEGER NOT NULL DEFAULT 0,
                timezone TEXT NOT NULL DEFAULT 'Australia/Sydney',
                interval_hours INTEGER NOT NULL DEFAULT 24,
                question_mode TEXT NOT NULL DEFAULT 'short_answer',
                module TEXT,
                topic TEXT
            );
            CREATE TABLE IF NOT EXISTS daily_posts (
                guild_id INTEGER NOT NULL,
                schedule_key TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, schedule_key)
            );
            """
        )
        settings_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(daily_settings)")
        }
        if "interval_hours" not in settings_columns:
            connection.execute(
                "ALTER TABLE daily_settings ADD COLUMN interval_hours "
                "INTEGER NOT NULL DEFAULT 24"
            )
        if "question_mode" not in settings_columns:
            connection.execute(
                "ALTER TABLE daily_settings ADD COLUMN question_mode "
                "TEXT NOT NULL DEFAULT 'short_answer'"
            )
        for column in ("module", "topic"):
            if column not in settings_columns:
                connection.execute(f"ALTER TABLE daily_settings ADD COLUMN {column} TEXT")
        post_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(daily_posts)")
        }
        if "local_date" in post_columns and "schedule_key" not in post_columns:
            connection.execute(
                "ALTER TABLE daily_posts RENAME COLUMN local_date TO schedule_key"
            )


def daily_settings() -> list[tuple[int, int, int, int, str, int, str, str | None, str | None]]:
    ensure_daily_tables()
    with sqlite3.connect(DB_PATH) as connection:
        return connection.execute(
            "SELECT guild_id, channel_id, hour, minute, timezone, interval_hours, "
            "question_mode, module, topic "
            "FROM daily_settings"
        ).fetchall()


def has_daily_post(guild_id: int, schedule_key: str) -> bool:
    with sqlite3.connect(DB_PATH) as connection:
        return connection.execute(
            "SELECT 1 FROM daily_posts WHERE guild_id = ? AND schedule_key = ?",
            (guild_id, schedule_key),
        ).fetchone() is not None


def record_daily_post(
    guild_id: int, schedule_key: str, channel_id: int, message_id: int, thread_id: int
) -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO daily_posts
               (guild_id, schedule_key, channel_id, message_id, thread_id)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, schedule_key, channel_id, message_id, thread_id),
        )


def mcq_race_questions(rounds: int) -> list[tuple[int, int, int, str, bytes, str]]:
    with sqlite3.connect(DB_PATH) as connection:
        questions = connection.execute(
            """SELECT year, question_number, pdf_page, correct_option,
                      image_blob, source_pdf_url
               FROM mcq_questions"""
        ).fetchall()
    if len(questions) < rounds:
        raise LookupError(
            f"The database has only {len(questions)} MCQs; it needs at least {rounds}."
        )
    return random.sample(questions, rounds)


class MCQAnswerButton(discord.ui.Button["MCQAnswerView"]):
    def __init__(self, option: str) -> None:
        super().__init__(label=option, style=discord.ButtonStyle.primary)
        self.option = option

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.submit_answer(interaction, self.option)


class MCQAnswerView(discord.ui.View):
    def __init__(self, correct_option: str) -> None:
        super().__init__(timeout=MCQ_ANSWER_TIMEOUT)
        self.correct_option = correct_option
        self.winner_future: asyncio.Future[discord.User | discord.Member | None] = (
            asyncio.get_running_loop().create_future()
        )
        self.finished = False
        self.eliminated_players: set[int] = set()
        for option in "ABCD":
            self.add_item(MCQAnswerButton(option))

    async def submit_answer(
        self, interaction: discord.Interaction, option: str
    ) -> None:
        if self.finished:
            await interaction.response.send_message(
                "This round has finished.", ephemeral=True
            )
            return
        if interaction.user.id in self.eliminated_players:
            await interaction.response.send_message(
                "You are out for this round. You can answer again on the next question.",
                ephemeral=True,
            )
            return
        if option != self.correct_option:
            self.eliminated_players.add(interaction.user.id)
            await interaction.response.send_message(
                "Wrong answer—you are out for this round. Wait for the next question.",
                ephemeral=True,
            )
            return

        self.finished = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ {interaction.user.mention} got it first! The answer is **{option}**.",
            view=self,
        )
        if not self.winner_future.done():
            self.winner_future.set_result(interaction.user)

    async def on_timeout(self) -> None:
        self.finished = True
        for item in self.children:
            item.disabled = True
        if not self.winner_future.done():
            self.winner_future.set_result(None)


async def play_mcq_race(channel: discord.TextChannel, rounds: int) -> int:
    questions = mcq_race_questions(rounds)
    scores: dict[int, tuple[discord.User | discord.Member, int]] = {}
    for round_number, question in enumerate(questions, start=1):
        year, question_number, page, correct_option, image_blob, pdf_url = question
        filename = f"mcq_{year}_q{question_number}.png"
        embed = discord.Embed(
            title=f"MCQ Race · Round {round_number}/{rounds} · {year} Q{question_number}",
            description=(
                "Choose A, B, C, or D. The first correct click wins this round. "
                f"You have {MCQ_ANSWER_TIMEOUT} seconds."
            ),
        )
        embed.set_image(url=f"attachment://{filename}")
        embed.add_field(
            name="Original paper",
            value=f"[Open question {question_number} at page {page}]({pdf_url}#page={page})",
            inline=False,
        )
        view = MCQAnswerView(correct_option)
        message = await channel.send(
            embed=embed,
            file=discord.File(io.BytesIO(image_blob), filename=filename),
            view=view,
        )
        winner = await view.winner_future
        if winner is None:
            await message.edit(
                content=f"Time's up. The correct answer was **{correct_option}**.",
                view=view,
            )
        else:
            previous_score = scores.get(winner.id, (winner, 0))[1]
            scores[winner.id] = (winner, previous_score + 1)
        await asyncio.sleep(1.5)

    if scores:
        ranking = sorted(scores.values(), key=lambda item: (-item[1], item[0].display_name))
        scoreboard = "\n".join(
            f"**{place}.** {player.mention} — {score}"
            for place, (player, score) in enumerate(ranking, start=1)
        )
        result = f"🏁 **Race complete!**\n{scoreboard}"
    else:
        result = "🏁 **Race complete!** No one got an answer correct this time."
    final_message = await channel.send(result)
    return final_message.id


def _random_question(module: str | None = None, topic: str | None = None) -> tuple[
    int, str, str, str, int | None, int | None, str | None, str | None,
    bytes, str, str,
]:
    with sqlite3.connect(DB_PATH) as connection:
        rows = connection.execute(
            """SELECT q.year, q.reference, q.topic, q.module,
                      q.marks, q.pdf_page,
                      q.marking_guide_pages, p.source_page_url, p.pdf_url,
                      p.marking_pdf_url,
                      i.image_blob
               FROM questions AS q
               JOIN papers AS p ON p.year = q.year
               JOIN question_images AS i
                 ON i.year = q.year AND i.reference = q.reference
               WHERE q.year BETWEEN 2019 AND 2024
                 AND (? IS NULL OR q.module = ?)
                 AND (? IS NULL OR q.topic = ?)
               ORDER BY q.year, q.question_number""",
            (module, module, topic, topic),
        ).fetchall()
    if not rows:
        if module or topic:
            raise LookupError("No questions match that module/topic selection.")
        raise LookupError("There are no question images in the database yet.")
    (
        year, reference, topic, module_label, marks, page, guide_pages,
        source_page, pdf_url, marking_pdf_url, image_blob,
    ) = random.choice(rows)
    return (
        year, reference, topic, module_label, marks, page, guide_pages,
        marking_pdf_url, image_blob, source_page, pdf_url,
    )


async def post_question(
    channel: discord.TextChannel,
    module: str | None = None,
    topic: str | None = None,
) -> tuple[discord.Message, discord.Thread]:
    """Post an image question and start its public discussion thread."""
    (
        year, reference, topic, module_label, marks, page, guide_pages,
        marking_pdf_url, image_blob, source_page, pdf_url,
    ) = _random_question(module, topic)
    safe_reference = reference.replace("(", "").replace(")", "")
    filename = f"{year}_{safe_reference}.png"
    page_link = f"{pdf_url}#page={page}" if page else source_page

    embed = discord.Embed(
        title=f"HSC Chemistry practice — {year} {reference}",
        description=f"{marks} marks · Discuss your working in the thread below."
        if marks
        else "Discuss your working in the thread below.",
    )
    embed.set_image(url=f"attachment://{filename}")
    embed.add_field(name="Topic", value=topic, inline=True)
    embed.add_field(name="Module", value=module_label, inline=False)
    embed.add_field(
        name="Original paper",
        value=f"[Open at page {page}]({page_link})" if page else f"[Open paper]({source_page})",
        inline=True,
    )
    if guide_pages:
        first_guide_page = guide_pages.split(",")[0]
        guide_link = (
            f"{marking_pdf_url}#page={first_guide_page}"
            if marking_pdf_url
            else source_page
        )
        embed.add_field(
            name="Marking guidelines",
            value=f"[View guidelines at page {first_guide_page}]({guide_link})",
            inline=True,
        )

    image_file = discord.File(io.BytesIO(image_blob), filename=filename)
    message = await channel.send(embed=embed, file=image_file)
    try:
        thread = await message.create_thread(
            name=f"Chemistry question — {year} {reference}"[:100],
            auto_archive_duration=1440,
        )
    except Exception:
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        raise
    return message, thread


def _missing_bot_permissions(channel: discord.TextChannel) -> list[str]:
    me = channel.guild.me
    if me is None:
        return ["bot membership in this server"]
    permissions = channel.permissions_for(me)
    required = {
        "send_messages": "Send Messages",
        "embed_links": "Embed Links",
        "attach_files": "Attach Files",
        "create_public_threads": "Create Public Threads",
    }
    return [label for attribute, label in required.items() if not getattr(permissions, attribute)]


def register_chemistry_quiz(tree: app_commands.CommandTree) -> None:
    """Register chemistry practice and daily schedule commands."""
    ensure_daily_tables()

    @tree.command(
        name="chemquiz",
        description="Post a real HSC Chemistry question and open a public discussion thread",
    )
    @app_commands.describe(module="Limit the question to a syllabus module", topic="Limit the question to a syllabus topic")
    @app_commands.choices(
        module=[app_commands.Choice(name=value, value=value) for value in MODULE_CHOICES],
        topic=[app_commands.Choice(name=value, value=value) for value in TOPIC_CHOICES],
    )
    async def chemquiz(
        interaction: discord.Interaction,
        module: str | None = None,
        topic: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel = interaction.channel
        if isinstance(channel, discord.Thread):
            channel = channel.parent
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(
                "Use this command in a server text channel so I can open a public thread.",
                ephemeral=True,
            )
            return

        missing = _missing_bot_permissions(channel)
        if missing:
            await interaction.followup.send(
                "I need these permissions in that channel: " + ", ".join(missing) + ".",
                ephemeral=True,
            )
            return
        try:
            _message, thread = await post_question(channel, module, topic)
        except LookupError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except discord.Forbidden:
            await interaction.followup.send(
                "I couldn't open the public thread. Check that I have Create Public Threads permission.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Posted the question. Join the public discussion: {thread.mention}",
            ephemeral=True,
        )

    @tree.command(
        name="mcqrace",
        description="Race your server to answer official HSC Chemistry MCQs",
    )
    @app_commands.describe(rounds="Number of questions in the race (1–20)")
    async def mcq_race(
        interaction: discord.Interaction,
        rounds: app_commands.Range[int, 1, 20] = 10,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Run this command in a server channel.", ephemeral=True
            )
            return
        channel = interaction.channel
        if isinstance(channel, discord.Thread):
            channel = channel.parent
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Run this command in a server text channel.", ephemeral=True
            )
            return
        if channel.id in ACTIVE_MCQ_RACES:
            await interaction.response.send_message(
                "An MCQ race is already running in this channel.", ephemeral=True
            )
            return
        bot_member = interaction.guild.me
        if bot_member is None:
            await interaction.response.send_message(
                "I can't check my channel permissions right now.", ephemeral=True
            )
            return
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
            await interaction.response.send_message(
                "I need these channel permissions: " + ", ".join(missing) + ".",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        ACTIVE_MCQ_RACES.add(channel.id)
        try:
            await interaction.followup.send(
                f"Starting a {rounds}-question MCQ race in {channel.mention}. "
                "Each round has a 45-second answer window.",
                ephemeral=True,
            )
            await play_mcq_race(channel, rounds)
        except LookupError as error:
            await interaction.followup.send(str(error), ephemeral=True)
        finally:
            ACTIVE_MCQ_RACES.discard(channel.id)

    @tree.command(
        name="setdailychannel",
        description="Set this server's chemistry question channel and posting interval",
    )
    @app_commands.describe(
        channel="Text channel for questions (defaults to this channel)",
        interval_hours="Post every this many hours (choose a divisor of 24)",
        hour="Local 24-hour clock hour for daily posts (0–23)",
        minute="Minute past the hour for posts (0–59)",
        question_mode="Choose the scheduled question format",
        module="For short-answer posts, restrict questions to this module",
        topic="For short-answer posts, restrict questions to this topic",
    )
    @app_commands.choices(
        question_mode=[
            app_commands.Choice(name="Short-answer question", value="short_answer"),
            app_commands.Choice(name="MCQ race", value="mcq_race"),
        ],
        module=[app_commands.Choice(name=value, value=value) for value in MODULE_CHOICES],
        topic=[app_commands.Choice(name=value, value=value) for value in TOPIC_CHOICES],
    )
    async def set_daily_channel(
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        interval_hours: app_commands.Range[int, 1, 24] = 24,
        question_mode: str = "short_answer",
        module: str | None = None,
        topic: str | None = None,
        hour: app_commands.Range[int, 0, 23] | None = None,
        minute: app_commands.Range[int, 0, 59] | None = None,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use this command in a server.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "You need Manage Server permission to set the daily channel.", ephemeral=True
            )
            return
        if interval_hours not in SUPPORTED_INTERVALS:
            choices = ", ".join(str(value) for value in SUPPORTED_INTERVALS)
            await interaction.response.send_message(
                f"Choose an interval that divides a day: {choices} hours.",
                ephemeral=True,
            )
            return
        if question_mode == "mcq_race" and (module or topic):
            await interaction.response.send_message(
                "Module and topic filters are currently available for short-answer questions.",
                ephemeral=True,
            )
            return

        target = channel or interaction.channel
        if isinstance(target, discord.Thread):
            target = target.parent
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "Choose a server text channel.", ephemeral=True
            )
            return
        missing = _missing_bot_permissions(target)
        if missing:
            await interaction.response.send_message(
                "I need these permissions in that channel: " + ", ".join(missing) + ".",
                ephemeral=True,
            )
            return

        with sqlite3.connect(DB_PATH) as connection:
            existing = connection.execute(
                "SELECT hour, minute FROM daily_settings WHERE guild_id = ?",
                (interaction.guild.id,),
            ).fetchone()
            scheduled_hour = hour if hour is not None else (
                existing[0] if existing else DEFAULT_HOUR
            )
            scheduled_minute = minute if minute is not None else (
                existing[1] if existing else DEFAULT_MINUTE
            )
            connection.execute(
                """INSERT INTO daily_settings
                   (guild_id, channel_id, hour, minute, timezone, interval_hours,
                    question_mode, module, topic)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                     channel_id=excluded.channel_id,
                     hour=excluded.hour,
                     minute=excluded.minute,
                     interval_hours=excluded.interval_hours,
                     question_mode=excluded.question_mode,
                     module=excluded.module,
                     topic=excluded.topic""",
                (
                    interaction.guild.id,
                    target.id,
                    scheduled_hour,
                    scheduled_minute,
                    DEFAULT_TIMEZONE,
                    interval_hours,
                    question_mode,
                    module,
                    topic,
                ),
            )
        interval_label = "once daily" if interval_hours == 24 else f"every {interval_hours} hour(s)"
        mode_label = "a short-answer question" if question_mode == "short_answer" else "a 5-question MCQ race"
        post_note = (
            " Each short-answer post starts a public discussion thread."
            if question_mode == "short_answer"
            else " Players race using the answer buttons in the channel."
        )
        time_label = (
            f"at {scheduled_hour:02d}:{scheduled_minute:02d}"
            if interval_hours == 24
            else f"at minute {scheduled_minute:02d} of each interval"
        )
        await interaction.response.send_message(
            f"{mode_label.capitalize()} will be posted in {target.mention} {interval_label} "
            f"{time_label}. "
            f"The schedule uses Australia/Sydney time.{post_note}"
            + (f" Filter: {module or 'any module'} / {topic or 'any topic'}." if question_mode == "short_answer" else ""),
            ephemeral=True,
        )

    @tree.command(name="setdailytime", description="Change the scheduled question time")
    @app_commands.describe(hour="24-hour clock hour, 0–23", minute="Minute, 0–59")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_daily_time(
        interaction: discord.Interaction,
        hour: app_commands.Range[int, 0, 23],
        minute: app_commands.Range[int, 0, 59] = 0,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Use this command in a server.", ephemeral=True)
            return
        with sqlite3.connect(DB_PATH) as connection:
            cursor = connection.execute(
                "UPDATE daily_settings SET hour = ?, minute = ? WHERE guild_id = ?",
                (hour, minute, interaction.guild.id),
            )
            settings = connection.execute(
                "SELECT interval_hours FROM daily_settings WHERE guild_id = ?",
                (interaction.guild.id,),
            ).fetchone()
        if cursor.rowcount == 0:
            await interaction.response.send_message(
                "Run `/setdailychannel` first to enable daily questions.", ephemeral=True
            )
            return
        timezone = ZoneInfo(DEFAULT_TIMEZONE)
        if settings and settings[0] == 24:
            message = f"Daily questions are now scheduled for {hour:02d}:{minute:02d} ({timezone.key})."
        else:
            message = (
                f"Questions will post at {minute:02d} minutes past each interval "
                f"({timezone.key}); the hour setting is only used for daily posts."
            )
        await interaction.response.send_message(message, ephemeral=True)
