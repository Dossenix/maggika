from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from checks import is_admin_user, is_staff
from database import db


log = logging.getLogger("maggika.hours")

OWNER_ROLE_ID = 1467908260316184777
MANAGER_ROLE_ID = 1467907829556969566
STAFF_DIRECTOR_ROLE_ID = 1476317246077796352
TECNICO_ROLE_ID = 1505553486065041458
ADMINISTRATOR_ROLE_ID = 1472188981197279264
MODERATOR_ROLE_ID = 1472188854084698265
HELPER_ROLE_ID = 1472188802226192507
TRIAL_ROLE_ID = 1472188720831791287
AUSILIARIO_ROLE_ID = 1472653631680548938
STAFF_ROLE_ID = 1472188572789510330

STAFF_TIME_ROLE_IDS = {
    OWNER_ROLE_ID,
    MANAGER_ROLE_ID,
    STAFF_DIRECTOR_ROLE_ID,
    TECNICO_ROLE_ID,
    ADMINISTRATOR_ROLE_ID,
    MODERATOR_ROLE_ID,
    HELPER_ROLE_ID,
    TRIAL_ROLE_ID,
    AUSILIARIO_ROLE_ID,
    STAFF_ROLE_ID,
}

HOURS_MANAGER_ROLE_IDS = {
    OWNER_ROLE_ID,
    MANAGER_ROLE_ID,
    STAFF_DIRECTOR_ROLE_ID,
    TECNICO_ROLE_ID,
    ADMINISTRATOR_ROLE_ID,
}
DEFAULT_WARNING_MANAGER_ROLE_IDS = HOURS_MANAGER_ROLE_IDS

DEFAULT_PANEL_TITLE = "Cartellino Staff"
DEFAULT_PANEL_DESCRIPTION = (
    "Gestisci il tuo turno staff dai pulsanti qui sotto.\n"
    "Apri quando inizi servizio e chiudi appena finisci."
)


@dataclass(frozen=True)
class ActiveShift:
    user_id: int
    clock_in: datetime


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_dt().isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def format_duration(seconds: int) -> str:
    if seconds < 0:
        seconds = 0

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    pieces: list[str] = []
    if days:
        pieces.append(f"{days}d")
    if hours:
        pieces.append(f"{hours}h")
    pieces.append(f"{minutes}m")
    return " ".join(pieces)


def minutes_from_seconds(seconds: int) -> int:
    if seconds <= 0:
        return 0

    return max(1, (seconds + 59) // 60)


def format_minutes(minutes: int) -> str:
    return f"{minutes} min"


def parse_duration(value: str) -> int | None:
    text = value.strip().lower().replace(" ", "")
    if text.isdigit():
        return int(text) * 60

    matches = list(re.finditer(r"(\d+)([dhmg])", text))
    if not matches:
        return None

    consumed = "".join(match.group(0) for match in matches)
    if consumed != text:
        return None

    total = 0
    for match in matches:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "d" or unit == "g":
            total += amount * 86400
        elif unit == "h":
            total += amount * 3600
        elif unit == "m":
            total += amount * 60

    return total if total > 0 else None


def parse_role_ids(value: str | None, fallback: set[int]) -> set[int]:
    if value is None:
        return set(fallback)

    role_ids: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if item.isdigit():
            role_ids.add(int(item))

    return role_ids or set(fallback)


def serialize_role_ids(role_ids: set[int]) -> str:
    return ",".join(str(role_id) for role_id in sorted(role_ids))


def is_time_staff(member: discord.Member) -> bool:
    if is_staff(member):
        return True

    return any(role.id in STAFF_TIME_ROLE_IDS for role in member.roles)


def is_hours_manager(member: discord.Member) -> bool:
    if is_admin_user(member):
        return True

    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True

    return any(role.id in HOURS_MANAGER_ROLE_IDS for role in member.roles)


async def require_time_staff(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Comando usabile solo nel server.", ephemeral=True)
        return False

    if not is_time_staff(interaction.user):
        await interaction.response.send_message("Solo lo staff puo usare il cartellino.", ephemeral=True)
        return False

    return True


async def require_hours_manager(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Comando usabile solo nel server.", ephemeral=True)
        return False

    if not is_hours_manager(interaction.user):
        await interaction.response.send_message(
            "Solo admin/gestione staff possono usare questo comando.",
            ephemeral=True,
        )
        return False

    return True


class TimecardView(discord.ui.View):
    def __init__(self, cog: Hours) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Apri cartellino",
        style=discord.ButtonStyle.success,
        custom_id="maggika_timecard_open",
    )
    async def open_timecard(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.cog.open_shift_from_interaction(interaction)

    @discord.ui.button(
        label="Chiudi cartellino",
        style=discord.ButtonStyle.danger,
        custom_id="maggika_timecard_close",
    )
    async def close_timecard(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.cog.close_shift_from_interaction(interaction)

    @discord.ui.button(
        label="Aperti ora",
        style=discord.ButtonStyle.secondary,
        custom_id="maggika_timecard_active",
    )
    async def active_timecards(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.cog.show_active_timecards(interaction)


class Hours(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.temprole_tasks: dict[int, asyncio.Task[None]] = {}
        self.restore_started = False
        self.ensure_schema()

    def cog_unload(self) -> None:
        for task in self.temprole_tasks.values():
            task.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self.restore_started:
            return

        self.restore_started = True
        await self.restore_pending_temproles()

    def ensure_schema(self) -> None:
        with db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS time_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    clock_in TEXT NOT NULL,
                    clock_out TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hours_settings (
                    guild_id INTEGER PRIMARY KEY,
                    panel_channel_id INTEGER,
                    panel_message_id INTEGER
                )
                """
            )
            time_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(time_entries)").fetchall()
            }
            if "duration_minutes" not in time_columns:
                conn.execute("ALTER TABLE time_entries ADD COLUMN duration_minutes INTEGER")

            settings_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(hours_settings)").fetchall()
            }
            if "logs_channel_id" not in settings_columns:
                conn.execute("ALTER TABLE hours_settings ADD COLUMN logs_channel_id INTEGER")
            if "warning_role_ids" not in settings_columns:
                conn.execute("ALTER TABLE hours_settings ADD COLUMN warning_role_ids TEXT")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hours_resets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    reset_by INTEGER NOT NULL,
                    total_seconds INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hours_voids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    voided_by INTEGER NOT NULL,
                    entry_id INTEGER NOT NULL,
                    clock_in TEXT NOT NULL,
                    clock_out TEXT,
                    duration_minutes INTEGER,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS staff_warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    removed_at TEXT
                )
                """
            )

    def active_shift_row(self, guild_id: int, user_id: int) -> object:
        with db() as conn:
            return conn.execute(
                """
                SELECT id, clock_in FROM time_entries
                WHERE guild_id = ? AND user_id = ? AND clock_out IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id, user_id),
            ).fetchone()

    def hours_settings_row(self, guild_id: int) -> object:
        with db() as conn:
            return conn.execute(
                """
                SELECT panel_channel_id, panel_message_id, logs_channel_id, warning_role_ids
                FROM hours_settings
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()

    def logs_channel_id(self, guild_id: int) -> int | None:
        row = self.hours_settings_row(guild_id)
        if row is None or row["logs_channel_id"] is None:
            return None

        return int(row["logs_channel_id"])

    def warning_manager_role_ids(self, guild_id: int) -> set[int]:
        row = self.hours_settings_row(guild_id)
        raw = None if row is None else row["warning_role_ids"]
        return parse_role_ids(raw, DEFAULT_WARNING_MANAGER_ROLE_IDS)

    def is_warning_manager(self, member: discord.Member) -> bool:
        if is_admin_user(member):
            return True

        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True

        warning_role_ids = self.warning_manager_role_ids(member.guild.id)
        return any(role.id in warning_role_ids for role in member.roles)

    async def require_warning_manager(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Comando usabile solo nel server.", ephemeral=True)
            return False

        if not self.is_warning_manager(interaction.user):
            await interaction.response.send_message(
                "Non puoi mettere richiami staff.",
                ephemeral=True,
            )
            return False

        return True

    def total_seconds(self, guild_id: int, user_id: int) -> int:
        total = 0
        with db() as conn:
            rows = conn.execute(
                """
                SELECT clock_in, clock_out FROM time_entries
                WHERE guild_id = ? AND user_id = ? AND clock_out IS NOT NULL
                """,
                (guild_id, user_id),
            ).fetchall()

        for row in rows:
            total += int((parse_iso(row["clock_out"]) - parse_iso(row["clock_in"])).total_seconds())

        return total

    def total_minutes(self, guild_id: int, user_id: int) -> int:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT clock_in, clock_out, duration_minutes FROM time_entries
                WHERE guild_id = ? AND user_id = ? AND clock_out IS NOT NULL
                """,
                (guild_id, user_id),
            ).fetchall()

        total = 0
        for row in rows:
            if row["duration_minutes"] is not None:
                total += int(row["duration_minutes"])
            else:
                seconds = int((parse_iso(row["clock_out"]) - parse_iso(row["clock_in"])).total_seconds())
                total += minutes_from_seconds(seconds)

        return total

    def active_shifts(self, guild_id: int) -> list[ActiveShift]:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT user_id, clock_in FROM time_entries
                WHERE guild_id = ? AND clock_out IS NULL
                ORDER BY clock_in ASC
                """,
                (guild_id,),
            ).fetchall()

        return [
            ActiveShift(user_id=row["user_id"], clock_in=parse_iso(row["clock_in"]))
            for row in rows
        ]

    def create_panel_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=DEFAULT_PANEL_TITLE,
            description=DEFAULT_PANEL_DESCRIPTION,
            color=discord.Color.blurple(),
            timestamp=now_dt(),
        )
        embed.add_field(
            name="Apri cartellino",
            value="Usalo quando inizi il turno staff.",
            inline=False,
        )
        embed.add_field(
            name="Chiudi cartellino",
            value="Usalo quando finisci il turno staff.",
            inline=False,
        )
        embed.add_field(
            name="Aperti ora",
            value="Mostra chi ha un turno attivo in questo momento.",
            inline=False,
        )
        return embed

    async def send_time_log(
        self,
        guild: discord.Guild,
        *,
        title: str,
        member: discord.abc.User,
        color: discord.Color,
        fields: list[tuple[str, str, bool]],
    ) -> None:
        channel_id = self.logs_channel_id(guild.id)
        if channel_id is None:
            return

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title=title,
            color=color,
            timestamp=now_dt(),
        )
        embed.add_field(name="Staff", value=member.mention, inline=True)
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)

        await channel.send(embed=embed)

    async def open_shift_from_interaction(self, interaction: discord.Interaction) -> None:
        if not await require_time_staff(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il cartellino nel server.", ephemeral=True)
            return

        active = self.active_shift_row(interaction.guild.id, interaction.user.id)
        if active:
            started = parse_iso(active["clock_in"])
            elapsed = int((now_dt() - started).total_seconds())
            await interaction.response.send_message(
                f"Hai gia il cartellino aperto da `{format_duration(elapsed)}`.",
                ephemeral=True,
            )
            return

        opened_at = now_iso()
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO time_entries (guild_id, user_id, clock_in)
                VALUES (?, ?, ?)
                """,
                (interaction.guild.id, interaction.user.id, opened_at),
            )
            entry_id = cursor.lastrowid

        await self.send_time_log(
            interaction.guild,
            title="Cartellino aperto",
            member=interaction.user,
            color=discord.Color.green(),
            fields=[
                ("Timbro", f"#{entry_id}", True),
                ("Ora", f"<t:{int(parse_iso(opened_at).timestamp())}:F>", False),
            ],
        )

        await interaction.response.send_message("Cartellino aperto. Buon turno.", ephemeral=True)

    async def close_shift_from_interaction(self, interaction: discord.Interaction) -> None:
        if not await require_time_staff(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il cartellino nel server.", ephemeral=True)
            return

        active = self.active_shift_row(interaction.guild.id, interaction.user.id)
        if not active:
            await interaction.response.send_message("Non hai cartellini aperti.", ephemeral=True)
            return

        ended = now_iso()
        seconds = int((parse_iso(ended) - parse_iso(active["clock_in"])).total_seconds())
        minutes = minutes_from_seconds(seconds)
        with db() as conn:
            conn.execute(
                "UPDATE time_entries SET clock_out = ?, duration_minutes = ? WHERE id = ?",
                (ended, minutes, active["id"]),
            )

        await self.send_time_log(
            interaction.guild,
            title="Cartellino chiuso",
            member=interaction.user,
            color=discord.Color.red(),
            fields=[
                ("Timbro", f"#{active['id']}", True),
                ("Durata", f"`{format_duration(seconds)}`", True),
                ("Servizio registrato", f"`{format_minutes(minutes)}`", True),
            ],
        )

        await interaction.response.send_message(
            (
                f"Cartellino chiuso. Durata turno: `{format_duration(seconds)}`.\n"
                f"Servizio registrato: `{format_minutes(minutes)}`."
            ),
            ephemeral=True,
        )

    async def show_active_timecards(self, interaction: discord.Interaction) -> None:
        if not await require_time_staff(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il cartellino nel server.", ephemeral=True)
            return

        shifts = self.active_shifts(interaction.guild.id)
        embed = discord.Embed(
            title="Cartellini aperti",
            color=discord.Color.green() if shifts else discord.Color.dark_grey(),
            timestamp=now_dt(),
        )

        if not shifts:
            embed.description = "Nessun cartellino aperto in questo momento."
        else:
            lines = []
            for shift in shifts:
                elapsed = int((now_dt() - shift.clock_in).total_seconds())
                lines.append(f"<@{shift.user_id}> aperto da `{format_duration(elapsed)}`")
            embed.description = "\n".join(lines)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="cartellino_panel", description="Invia il pannello cartellino staff.")
    @app_commands.describe(
        canale="Canale dove inviare il cartellino",
        logs="Canale dove mandare i log apertura/chiusura",
    )
    async def cartellino_panel(
        self,
        interaction: discord.Interaction,
        canale: discord.TextChannel | None = None,
        logs: discord.TextChannel | None = None,
    ) -> None:
        if not await require_hours_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        target_channel = canale or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("Canale non valido.", ephemeral=True)
            return

        message = await target_channel.send(embed=self.create_panel_embed(), view=TimecardView(self))
        old_settings = self.hours_settings_row(interaction.guild.id)
        logs_channel_id = logs.id if logs else (None if old_settings is None else old_settings["logs_channel_id"])
        with db() as conn:
            conn.execute(
                """
                INSERT INTO hours_settings (guild_id, panel_channel_id, panel_message_id, logs_channel_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    panel_channel_id = excluded.panel_channel_id,
                    panel_message_id = excluded.panel_message_id,
                    logs_channel_id = excluded.logs_channel_id
                """,
                (interaction.guild.id, target_channel.id, message.id, logs_channel_id),
            )

        logs_text = f"\nLog cartellino: {logs.mention}" if logs else ""
        await interaction.response.send_message(
            f"Cartellino inviato in {target_channel.mention}.{logs_text}",
            ephemeral=True,
        )

    @app_commands.command(name="cartellino_set_logs", description="Setta il canale log del cartellino.")
    @app_commands.describe(canale="Canale dove mandare log apertura/chiusura cartellino")
    async def cartellino_set_logs(
        self,
        interaction: discord.Interaction,
        canale: discord.TextChannel,
    ) -> None:
        if not await require_hours_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        old_settings = self.hours_settings_row(interaction.guild.id)
        panel_channel_id = None if old_settings is None else old_settings["panel_channel_id"]
        panel_message_id = None if old_settings is None else old_settings["panel_message_id"]
        with db() as conn:
            conn.execute(
                """
                INSERT INTO hours_settings (guild_id, panel_channel_id, panel_message_id, logs_channel_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    logs_channel_id = excluded.logs_channel_id
                """,
                (interaction.guild.id, panel_channel_id, panel_message_id, canale.id),
            )

        await interaction.response.send_message(
            f"Log cartellino impostati in {canale.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="clock_in", description="Apri il tuo cartellino staff.")
    async def clock_in(self, interaction: discord.Interaction) -> None:
        await self.open_shift_from_interaction(interaction)

    @app_commands.command(name="clock_out", description="Chiudi il tuo cartellino staff.")
    async def clock_out(self, interaction: discord.Interaction) -> None:
        await self.close_shift_from_interaction(interaction)

    @app_commands.command(name="my_hours", description="Vedi le tue ore staff.")
    async def my_hours(self, interaction: discord.Interaction) -> None:
        if not await require_time_staff(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        total = self.total_seconds(interaction.guild.id, interaction.user.id)
        total_minutes = self.total_minutes(interaction.guild.id, interaction.user.id)
        active = self.active_shift_row(interaction.guild.id, interaction.user.id)
        active_text = "No"
        if active:
            elapsed = int((now_dt() - parse_iso(active["clock_in"])).total_seconds())
            active_text = f"Si, da `{format_duration(elapsed)}`"

        embed = discord.Embed(
            title="Le tue ore staff",
            color=discord.Color.blurple(),
            timestamp=now_dt(),
        )
        embed.add_field(name="Totale registrato", value=f"`{format_duration(total)}`", inline=True)
        embed.add_field(name="Servizio", value=f"`{format_minutes(total_minutes)}`", inline=True)
        embed.add_field(name="Cartellino aperto", value=active_text, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="hours", description="Vedi le ore di uno staff.")
    @app_commands.describe(staff="Staff da controllare")
    async def hours(self, interaction: discord.Interaction, staff: discord.Member) -> None:
        if not await require_hours_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        total = self.total_seconds(interaction.guild.id, staff.id)
        total_minutes = self.total_minutes(interaction.guild.id, staff.id)
        active = self.active_shift_row(interaction.guild.id, staff.id)
        active_text = "No"
        if active:
            elapsed = int((now_dt() - parse_iso(active["clock_in"])).total_seconds())
            active_text = f"Si, da `{format_duration(elapsed)}`"

        embed = discord.Embed(
            title=f"Ore staff - {staff.display_name}",
            color=discord.Color.blurple(),
            timestamp=now_dt(),
        )
        embed.add_field(name="Totale registrato", value=f"`{format_duration(total)}`", inline=True)
        embed.add_field(name="Servizio", value=f"`{format_minutes(total_minutes)}`", inline=True)
        embed.add_field(name="Cartellino aperto", value=active_text, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="hours_reset", description="Resetta le ore di uno staff.")
    @app_commands.describe(staff="Staff da resettare", motivo="Motivo del reset")
    async def hours_reset(
        self,
        interaction: discord.Interaction,
        staff: discord.Member,
        motivo: str = "Reset ore staff",
    ) -> None:
        if not await require_hours_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        total = self.total_seconds(interaction.guild.id, staff.id)
        total_minutes = self.total_minutes(interaction.guild.id, staff.id)
        active = self.active_shift_row(interaction.guild.id, staff.id)
        if active:
            active_seconds = int((now_dt() - parse_iso(active["clock_in"])).total_seconds())
            total += active_seconds
            total_minutes += minutes_from_seconds(active_seconds)

        with db() as conn:
            conn.execute(
                """
                INSERT INTO hours_resets (guild_id, user_id, reset_by, total_seconds, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (interaction.guild.id, staff.id, interaction.user.id, total, motivo, now_iso()),
            )
            conn.execute(
                "DELETE FROM time_entries WHERE guild_id = ? AND user_id = ?",
                (interaction.guild.id, staff.id),
            )

        await interaction.response.send_message(
            (
                f"Ore di {staff.mention} resettate.\n"
                f"Totale archiviato: `{format_duration(total)}` (`{format_minutes(total_minutes)}`)."
            ),
            ephemeral=True,
        )

    @app_commands.command(name="cartellino_annulla", description="Annulla un timbro/cartellino registrato.")
    @app_commands.describe(
        staff="Staff a cui annullare il timbro",
        tipo="Quale timbro annullare",
        motivo="Motivo dell'annullamento",
    )
    @app_commands.choices(
        tipo=[
            app_commands.Choice(name="Cartellino aperto", value="active"),
            app_commands.Choice(name="Ultimo timbro", value="latest"),
        ]
    )
    async def cartellino_annulla(
        self,
        interaction: discord.Interaction,
        staff: discord.Member,
        tipo: app_commands.Choice[str],
        motivo: str = "Timbro annullato",
    ) -> None:
        if not await require_hours_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        if tipo.value == "active":
            query = """
                SELECT id, clock_in, clock_out, duration_minutes FROM time_entries
                WHERE guild_id = ? AND user_id = ? AND clock_out IS NULL
                ORDER BY id DESC LIMIT 1
                """
        else:
            query = """
                SELECT id, clock_in, clock_out, duration_minutes FROM time_entries
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT 1
                """

        with db() as conn:
            row = conn.execute(query, (interaction.guild.id, staff.id)).fetchone()

        if row is None:
            await interaction.response.send_message(
                "Nessun timbro trovato da annullare.",
                ephemeral=True,
            )
            return

        duration_minutes = row["duration_minutes"]
        if duration_minutes is None and row["clock_out"] is not None:
            seconds = int((parse_iso(row["clock_out"]) - parse_iso(row["clock_in"])).total_seconds())
            duration_minutes = minutes_from_seconds(seconds)

        with db() as conn:
            conn.execute(
                """
                INSERT INTO hours_voids (
                    guild_id,
                    user_id,
                    voided_by,
                    entry_id,
                    clock_in,
                    clock_out,
                    duration_minutes,
                    reason,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction.guild.id,
                    staff.id,
                    interaction.user.id,
                    row["id"],
                    row["clock_in"],
                    row["clock_out"],
                    duration_minutes,
                    motivo,
                    now_iso(),
                ),
            )
            conn.execute(
                "DELETE FROM time_entries WHERE id = ?",
                (row["id"],),
            )

        await self.send_time_log(
            interaction.guild,
            title="Timbro annullato",
            member=staff,
            color=discord.Color.orange(),
            fields=[
                ("Timbro", f"#{row['id']}", True),
                ("Annullato da", interaction.user.mention, True),
                ("Minuti rimossi", f"`{duration_minutes or 0} min`", True),
                ("Motivo", motivo, False),
            ],
        )

        await interaction.response.send_message(
            (
                f"Timbro #{row['id']} annullato per {staff.mention}.\n"
                f"Minuti rimossi: `{duration_minutes or 0} min`."
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="staff_richiamo_roles",
        description="Decidi quali ruoli possono mettere richiami staff.",
    )
    @app_commands.describe(
        ruolo_1="Primo ruolo autorizzato",
        ruolo_2="Secondo ruolo autorizzato opzionale",
        ruolo_3="Terzo ruolo autorizzato opzionale",
    )
    async def staff_richiamo_roles(
        self,
        interaction: discord.Interaction,
        ruolo_1: discord.Role,
        ruolo_2: discord.Role | None = None,
        ruolo_3: discord.Role | None = None,
    ) -> None:
        if not await require_hours_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        role_ids = {role.id for role in (ruolo_1, ruolo_2, ruolo_3) if role is not None}
        old_settings = self.hours_settings_row(interaction.guild.id)
        panel_channel_id = None if old_settings is None else old_settings["panel_channel_id"]
        panel_message_id = None if old_settings is None else old_settings["panel_message_id"]
        logs_channel_id = None if old_settings is None else old_settings["logs_channel_id"]

        with db() as conn:
            conn.execute(
                """
                INSERT INTO hours_settings (
                    guild_id,
                    panel_channel_id,
                    panel_message_id,
                    logs_channel_id,
                    warning_role_ids
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    warning_role_ids = excluded.warning_role_ids
                """,
                (
                    interaction.guild.id,
                    panel_channel_id,
                    panel_message_id,
                    logs_channel_id,
                    serialize_role_ids(role_ids),
                ),
            )

        mentions = " ".join(f"<@&{role_id}>" for role_id in sorted(role_ids))
        await interaction.response.send_message(
            f"Ruoli autorizzati ai richiami aggiornati: {mentions}",
            ephemeral=True,
        )

    @app_commands.command(name="staff_richiamo", description="Dai un richiamo staff con ruolo temporaneo.")
    @app_commands.describe(
        staff="Staff da richiamare",
        ruolo="Ruolo temporaneo da assegnare",
        durata="Durata tipo 30m, 2h, 1d, 3d, 1d2h",
        motivo="Motivo del richiamo",
    )
    async def staff_richiamo(
        self,
        interaction: discord.Interaction,
        staff: discord.Member,
        ruolo: discord.Role,
        durata: str,
        motivo: str,
    ) -> None:
        if not await self.require_warning_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        seconds = parse_duration(durata)
        if seconds is None:
            await interaction.response.send_message(
                "Durata non valida. Usa formati tipo `30m`, `2h`, `1d`, `3d`, `1d2h`.",
                ephemeral=True,
            )
            return

        if interaction.guild.me and ruolo >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "Non posso assegnare quel ruolo: e' sopra o pari al ruolo del bot.",
                ephemeral=True,
            )
            return

        expires_at = now_dt() + timedelta(seconds=seconds)
        try:
            await staff.add_roles(ruolo, reason=f"Richiamo staff: {motivo}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "Non posso assegnare questo ruolo. Controlla gerarchia e permessi.",
                ephemeral=True,
            )
            return

        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO staff_warnings (
                    guild_id,
                    target_id,
                    moderator_id,
                    role_id,
                    reason,
                    duration_seconds,
                    created_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction.guild.id,
                    staff.id,
                    interaction.user.id,
                    ruolo.id,
                    motivo,
                    seconds,
                    now_iso(),
                    expires_at.isoformat(),
                ),
            )
            warning_id = cursor.lastrowid

        self.temprole_tasks[warning_id] = asyncio.create_task(
            self.remove_temprole_later(warning_id, interaction.guild.id, staff.id, ruolo.id, seconds)
        )

        await interaction.response.send_message(
            (
                f"Richiamo registrato per {staff.mention}.\n"
                f"Ruolo temporaneo: {ruolo.mention}\n"
                f"Durata: `{format_duration(seconds)}`\n"
                f"Motivo: {motivo}"
            ),
            ephemeral=True,
        )

    @app_commands.command(name="staff_archive", description="Vedi archivio ore/richiami di uno staff.")
    @app_commands.describe(staff="Staff da controllare")
    async def staff_archive(self, interaction: discord.Interaction, staff: discord.Member) -> None:
        if not await require_hours_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        total = self.total_seconds(interaction.guild.id, staff.id)
        total_minutes = self.total_minutes(interaction.guild.id, staff.id)
        active = self.active_shift_row(interaction.guild.id, staff.id)

        with db() as conn:
            warnings = conn.execute(
                """
                SELECT id, moderator_id, role_id, reason, duration_seconds, created_at, expires_at, removed_at
                FROM staff_warnings
                WHERE guild_id = ? AND target_id = ?
                ORDER BY id DESC LIMIT 8
                """,
                (interaction.guild.id, staff.id),
            ).fetchall()
            resets = conn.execute(
                """
                SELECT reset_by, total_seconds, reason, created_at
                FROM hours_resets
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT 5
                """,
                (interaction.guild.id, staff.id),
            ).fetchall()
            voids = conn.execute(
                """
                SELECT voided_by, entry_id, duration_minutes, reason, created_at
                FROM hours_voids
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT 5
                """,
                (interaction.guild.id, staff.id),
            ).fetchall()

        embed = discord.Embed(
            title=f"Archivio staff - {staff.display_name}",
            color=discord.Color.blurple(),
            timestamp=now_dt(),
        )
        embed.add_field(
            name="Ore attuali",
            value=f"`{format_duration(total)}` (`{format_minutes(total_minutes)}`)",
            inline=True,
        )

        if active:
            elapsed = int((now_dt() - parse_iso(active["clock_in"])).total_seconds())
            active_text = f"Aperto da `{format_duration(elapsed)}`"
        else:
            active_text = "Nessun cartellino aperto"
        embed.add_field(name="Stato cartellino", value=active_text, inline=True)

        if warnings:
            lines = []
            for row in warnings:
                status = "attivo" if row["removed_at"] is None else "chiuso"
                lines.append(
                    f"#{row['id']} <@&{row['role_id']}> `{status}` - "
                    f"{row['reason']} ({format_duration(row['duration_seconds'])}) "
                    f"da <@{row['moderator_id']}>"
                )
            embed.add_field(name="Ultimi richiami", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Ultimi richiami", value="Nessun richiamo registrato.", inline=False)

        if resets:
            lines = []
            for row in resets:
                created = parse_iso(row["created_at"]).strftime("%Y-%m-%d")
                lines.append(
                    f"`{created}` reset di `{format_duration(row['total_seconds'])}` "
                    f"da <@{row['reset_by']}> - {row['reason']}"
                )
            embed.add_field(name="Reset ore", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Reset ore", value="Nessun reset registrato.", inline=False)

        if voids:
            lines = []
            for row in voids:
                created = parse_iso(row["created_at"]).strftime("%Y-%m-%d")
                minutes = row["duration_minutes"] or 0
                lines.append(
                    f"`{created}` timbro #{row['entry_id']} annullato "
                    f"da <@{row['voided_by']}> - `{minutes} min` - {row['reason']}"
                )
            embed.add_field(name="Timbri annullati", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Timbri annullati", value="Nessun timbro annullato.", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def restore_pending_temproles(self) -> None:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT id, guild_id, target_id, role_id, expires_at
                FROM staff_warnings
                WHERE removed_at IS NULL
                """
            ).fetchall()

        for row in rows:
            remaining = int((parse_iso(row["expires_at"]) - now_dt()).total_seconds())
            self.temprole_tasks[row["id"]] = asyncio.create_task(
                self.remove_temprole_later(
                    row["id"],
                    row["guild_id"],
                    row["target_id"],
                    row["role_id"],
                    max(0, remaining),
                )
            )

    async def remove_temprole_later(
        self,
        warning_id: int,
        guild_id: int,
        member_id: int,
        role_id: int,
        delay_seconds: int,
    ) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return

            member = guild.get_member(member_id)
            if member is None:
                try:
                    member = await guild.fetch_member(member_id)
                except discord.DiscordException:
                    member = None

            role = guild.get_role(role_id)
            if member is not None and role is not None and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Richiamo staff scaduto")
                except discord.Forbidden:
                    log.warning("Could not remove expired staff warning role %s from %s", role_id, member_id)

            with db() as conn:
                conn.execute(
                    "UPDATE staff_warnings SET removed_at = ? WHERE id = ?",
                    (now_iso(), warning_id),
                )
        finally:
            self.temprole_tasks.pop(warning_id, None)


async def setup(bot: commands.Bot) -> None:
    cog = Hours(bot)
    bot.add_view(TimecardView(cog))
    await bot.add_cog(cog)
