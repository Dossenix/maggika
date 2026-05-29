from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from checks import is_admin_user, is_staff
from config import settings
from database import db


log = logging.getLogger("maggika.disboard")

DISBOARD_BOT_ID = settings.disboard_bot_id or 302050872383242240
DEFAULT_REMINDER_MINUTES = settings.disboard_reminder_minutes or 120

DISBOARD_MANAGER_ROLE_IDS = {
    1467908260316184777,  # Owner
    1467907829556969566,  # Manager
    1476317246077796352,  # Staff Director
    1505553486065041458,  # Tecnico
    1472188981197279264,  # Administrator
    1472188572789510330,  # Staff generale
}


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_dt().isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def format_due_time(value: str) -> str:
    timestamp = int(parse_iso(value).timestamp())
    return f"<t:{timestamp}:R>"


def message_text(message: discord.Message) -> str:
    parts = [message.content or ""]
    for embed in message.embeds:
        parts.append(embed.title or "")
        parts.append(embed.description or "")
        if embed.footer:
            parts.append(embed.footer.text or "")
        if embed.author:
            parts.append(embed.author.name or "")
    return " ".join(parts).lower()


def is_successful_bump_message(message: discord.Message) -> bool:
    text = message_text(message)
    success_markers = (
        "bump done",
        "bumped",
        "server bumped",
        "successfully bumped",
        "bump effettuato",
        "bump completato",
    )
    cooldown_markers = (
        "wait",
        "cooldown",
        "try again",
        "riprov",
        "attendi",
        "already bumped",
    )

    if any(marker in text for marker in cooldown_markers):
        return False

    return any(marker in text for marker in success_markers)


def find_bumper_id(message: discord.Message) -> int | None:
    interaction_metadata = getattr(message, "interaction_metadata", None)
    if interaction_metadata:
        user = getattr(interaction_metadata, "user", None)
        if user:
            return user.id

    old_interaction = getattr(message, "interaction", None)
    if old_interaction:
        user = getattr(old_interaction, "user", None)
        if user:
            return user.id

    if message.mentions:
        return message.mentions[0].id

    return None


async def require_disboard_manager(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Comando usabile solo nel server.", ephemeral=True)
        return False

    if (
        is_admin_user(interaction.user)
        or interaction.user.guild_permissions.administrator
        or interaction.user.guild_permissions.manage_guild
        or is_staff(interaction.user)
        or any(role.id in DISBOARD_MANAGER_ROLE_IDS for role in interaction.user.roles)
    ):
        return True

    await interaction.response.send_message("Non hai i permessi per gestire DISBOARD.", ephemeral=True)
    return False


class Disboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.reminder_tasks: dict[int, asyncio.Task[None]] = {}
        self.restore_started = False
        self.ensure_schema()

    def cog_unload(self) -> None:
        for task in self.reminder_tasks.values():
            task.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.restore_started:
            return

        self.restore_started = True
        await self.restore_pending_reminders()

    def ensure_schema(self) -> None:
        with db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS disboard_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    bumper_id INTEGER,
                    bump_message_id INTEGER,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sent_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS disboard_settings (
                    guild_id INTEGER PRIMARY KEY,
                    reminder_minutes INTEGER NOT NULL
                )
                """
            )

    def reminder_minutes(self, guild_id: int) -> int:
        with db() as conn:
            row = conn.execute(
                """
                SELECT reminder_minutes FROM disboard_settings
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()

        if row is None:
            return DEFAULT_REMINDER_MINUTES

        return int(row["reminder_minutes"])

    def set_reminder_minutes(self, guild_id: int, minutes: int) -> None:
        with db() as conn:
            conn.execute(
                """
                INSERT INTO disboard_settings (guild_id, reminder_minutes)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    reminder_minutes = excluded.reminder_minutes
                """,
                (guild_id, minutes),
            )

    def cancel_pending_channel_reminders(self, guild_id: int, channel_id: int) -> None:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT id FROM disboard_reminders
                WHERE guild_id = ? AND channel_id = ? AND status = 'pending'
                """,
                (guild_id, channel_id),
            ).fetchall()
            conn.execute(
                """
                UPDATE disboard_reminders
                SET status = 'cancelled'
                WHERE guild_id = ? AND channel_id = ? AND status = 'pending'
                """,
                (guild_id, channel_id),
            )

        for row in rows:
            task = self.reminder_tasks.pop(row["id"], None)
            if task:
                task.cancel()

    async def create_reminder(
        self,
        message: discord.Message,
        bumper_id: int | None,
    ) -> None:
        if message.guild is None:
            return

        self.cancel_pending_channel_reminders(message.guild.id, message.channel.id)

        minutes = self.reminder_minutes(message.guild.id)
        due_at = now_dt() + timedelta(minutes=minutes)
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO disboard_reminders (
                    guild_id,
                    channel_id,
                    bumper_id,
                    bump_message_id,
                    due_at,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    message.guild.id,
                    message.channel.id,
                    bumper_id,
                    message.id,
                    due_at.isoformat(),
                    now_iso(),
                ),
            )
            reminder_id = cursor.lastrowid

        self.reminder_tasks[reminder_id] = asyncio.create_task(
            self.run_reminder(reminder_id, due_at)
        )

        log.info(
            "DISBOARD reminder scheduled: guild=%s channel=%s bumper=%s due_at=%s",
            message.guild.id,
            message.channel.id,
            bumper_id,
            due_at.isoformat(),
        )

    async def run_reminder(self, reminder_id: int, due_at: datetime) -> None:
        try:
            delay = max(0, int((due_at - now_dt()).total_seconds()))
            await asyncio.sleep(delay)

            with db() as conn:
                row = conn.execute(
                    """
                    SELECT id, channel_id, bumper_id, status
                    FROM disboard_reminders
                    WHERE id = ?
                    """,
                    (reminder_id,),
                ).fetchone()

            if row is None or row["status"] != "pending":
                return

            channel = self.bot.get_channel(row["channel_id"])
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(row["channel_id"])
                except discord.DiscordException:
                    return

            if not isinstance(channel, discord.abc.Messageable):
                return

            bumper_id = row["bumper_id"]
            if bumper_id:
                content = f"<@{bumper_id}> puoi rifare bump su DISBOARD."
                mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)
            else:
                content = "Si puo rifare bump su DISBOARD."
                mentions = discord.AllowedMentions(users=False, roles=False, everyone=False)

            await channel.send(content, allowed_mentions=mentions)

            with db() as conn:
                conn.execute(
                    """
                    UPDATE disboard_reminders
                    SET status = 'sent', sent_at = ?
                    WHERE id = ?
                    """,
                    (now_iso(), reminder_id),
                )
        finally:
            self.reminder_tasks.pop(reminder_id, None)

    async def restore_pending_reminders(self) -> None:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT id, due_at FROM disboard_reminders
                WHERE status = 'pending'
                """
            ).fetchall()

        for row in rows:
            self.reminder_tasks[row["id"]] = asyncio.create_task(
                self.run_reminder(row["id"], parse_iso(row["due_at"]))
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.id != DISBOARD_BOT_ID:
            return

        if message.guild is None:
            return

        if not is_successful_bump_message(message):
            return

        bumper_id = find_bumper_id(message)
        if bumper_id is None:
            log.warning("DISBOARD bump detected, but bumper user was not available.")

        await self.create_reminder(message, bumper_id)

    @app_commands.command(name="disboard_set_timer", description="Setta dopo quanti minuti ricordare il bump.")
    @app_commands.describe(minuti="Minuti prima del reminder, di solito 120")
    async def disboard_set_timer(
        self,
        interaction: discord.Interaction,
        minuti: app_commands.Range[int, 1, 1440],
    ) -> None:
        if not await require_disboard_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        self.set_reminder_minutes(interaction.guild.id, int(minuti))
        await interaction.response.send_message(
            f"Timer DISBOARD impostato a `{minuti}` minuti.",
            ephemeral=True,
        )

    @app_commands.command(name="disboard_status", description="Mostra il prossimo reminder DISBOARD.")
    async def disboard_status(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        with db() as conn:
            row = conn.execute(
                """
                SELECT bumper_id, channel_id, due_at
                FROM disboard_reminders
                WHERE guild_id = ? AND status = 'pending'
                ORDER BY due_at ASC LIMIT 1
                """,
                (interaction.guild.id,),
            ).fetchone()

        if row is None:
            await interaction.response.send_message(
                "Non ci sono reminder DISBOARD in attesa.",
                ephemeral=True,
            )
            return

        bumper = f"<@{row['bumper_id']}>" if row["bumper_id"] else "utente non rilevato"
        await interaction.response.send_message(
            (
                f"Prossimo reminder: {format_due_time(row['due_at'])}\n"
                f"Canale: <#{row['channel_id']}>\n"
                f"Bumper: {bumper}"
            ),
            ephemeral=True,
        )

    @app_commands.command(name="disboard_cancel", description="Cancella i reminder DISBOARD del canale.")
    @app_commands.describe(canale="Canale da cui cancellare i reminder pendenti")
    async def disboard_cancel(
        self,
        interaction: discord.Interaction,
        canale: discord.TextChannel | None = None,
    ) -> None:
        if not await require_disboard_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        target_channel = canale or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("Canale non valido.", ephemeral=True)
            return

        self.cancel_pending_channel_reminders(interaction.guild.id, target_channel.id)
        await interaction.response.send_message(
            f"Reminder DISBOARD cancellati per {target_channel.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Disboard(bot))
