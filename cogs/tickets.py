from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from checks import is_admin_user, is_staff
from database import db


log = logging.getLogger("maggika.tickets")

OWNER_ROLE_ID = 1467908260316184777
MANAGER_ROLE_ID = 1467907829556969566
STAFF_DIRECTOR_ROLE_ID = 1476317246077796352
TECNICO_ROLE_ID = 1505553486065041458
ADMINISTRATOR_ROLE_ID = 1472188981197279264
STAFF_ROLE_ID = 1472188572789510330

TICKET_MANAGER_ROLE_IDS = {
    OWNER_ROLE_ID,
    MANAGER_ROLE_ID,
    STAFF_DIRECTOR_ROLE_ID,
    TECNICO_ROLE_ID,
    ADMINISTRATOR_ROLE_ID,
}


@dataclass(frozen=True)
class TicketType:
    key: str
    label: str
    slug: str
    description: str
    support_label: str
    default_support_role_ids: tuple[int, ...]
    default_category_id: int
    default_transcript_channel_id: int
    color: discord.Color
    button_style: discord.ButtonStyle


@dataclass(frozen=True)
class TicketConfig:
    ticket_type: TicketType
    support_role_ids: tuple[int, ...]
    category_id: int
    transcript_channel_id: int
    open_title: str
    open_message: str


TICKET_TYPES: dict[str, TicketType] = {
    "reports_utenti": TicketType(
        key="reports_utenti",
        label="Reports Utenti",
        slug="report-utenti",
        description="Segnalazioni verso altri utenti che violano il regolamento o i tos di discord.",
        support_label="Staff Generale",
        default_support_role_ids=(STAFF_ROLE_ID,),
        default_category_id=1507679389691805758,
        default_transcript_channel_id=1507679448168796302,
        color=discord.Color.red(),
        button_style=discord.ButtonStyle.danger,
    ),
    "reports_staff": TicketType(
        key="reports_staff",
        label="Reports Staff",
        slug="report-staff",
        description="Supporto verso i membri dello staff che violano il regolamento o la buona disciplina.",
        support_label="Intera Amministrazione",
        default_support_role_ids=(TECNICO_ROLE_ID,),
        default_category_id=1507680777561964695,
        default_transcript_channel_id=1507680912371089500,
        color=discord.Color.from_rgb(255, 0, 255),
        button_style=discord.ButtonStyle.primary,
    ),
    "supporto_generale": TicketType(
        key="supporto_generale",
        label="Supporto Generale",
        slug="supporto",
        description="Posto dove chiedere o chiarire dubbi, domande, perplessita e riscuotere vantaggi tratti da abbonamenti.",
        support_label="Staff Generale",
        default_support_role_ids=(STAFF_ROLE_ID,),
        default_category_id=1507679782459150506,
        default_transcript_channel_id=1507679817984643072,
        color=discord.Color.green(),
        button_style=discord.ButtonStyle.success,
    ),
    "partnership": TicketType(
        key="partnership",
        label="Partnership",
        slug="partnership",
        description='Posto dove inviare richieste di Partnership tra il server di proprieta/gestione e il Server dei "kings di CastaMaggic".',
        support_label="Alta Amministrazione",
        default_support_role_ids=(TECNICO_ROLE_ID,),
        default_category_id=1507679905582809218,
        default_transcript_channel_id=1507680087628054558,
        color=discord.Color.gold(),
        button_style=discord.ButtonStyle.secondary,
    ),
}

TICKET_CHOICES = [
    app_commands.Choice(name=ticket_type.label, value=ticket_type.key)
    for ticket_type in TICKET_TYPES.values()
]

DEFAULT_OPEN_TITLE = "Ticket #{ticket_id} - {type}"
DEFAULT_OPEN_MESSAGE = (
    "Ciao {user}, il tuo ticket e' stato aperto correttamente.\n\n"
    "**Oggetto:** {subject}\n\n"
    "{description}\n\n"
    "Un membro del supporto ti rispondera' appena possibile."
)

DEFAULT_PANEL_TITLE = "Centro Supporto Maggiko"
DEFAULT_PANEL_DESCRIPTION = (
    "Scegli la sezione piu adatta usando i pulsanti qui sotto.\n"
    "Dopo il click potrai scrivere oggetto e descrizione del ticket.\n\n"
    "**Reports Utenti**\n"
    "Segnalazioni verso altri utenti che violano il regolamento o i tos di discord.\n"
    "Supporto: Staff Generale\n\n"
    "**Reports Staff**\n"
    "Supporto verso i membri dello staff che violano il regolamento o la buona disciplina.\n"
    "Supporto: Intera Amministrazione\n\n"
    "**Supporto Generale**\n"
    "Posto dove chiedere o chiarire dubbi, domande, perplessita e riscuotere vantaggi tratti da abbonamenti.\n"
    "Supporto: Staff Generale\n\n"
    "**Partnership**\n"
    'Posto dove inviare richieste di Partnership tra il server di proprieta/gestione e il Server dei "kings di CastaMaggic".\n'
    "Supporto: Alta Amministrazione"
)


class SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", value.lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned[:24] or "utente"


def trim_embed_text(value: str, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value

    return value[: limit - 20] + "\n\n[Messaggio tagliato]"


def parse_ids(raw: str | None, fallback: tuple[int, ...]) -> tuple[int, ...]:
    if raw is None:
        return fallback

    ids: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            ids.append(int(item))

    return tuple(dict.fromkeys(ids))


def serialize_ids(ids: tuple[int, ...]) -> str:
    return ",".join(str(role_id) for role_id in ids)


def get_row_value(row: object, key: str, default: object = None) -> object:
    if row is None:
        return default

    try:
        return row[key]  # type: ignore[index]
    except (KeyError, IndexError):
        return default


def is_ticket_manager(member: discord.Member) -> bool:
    if is_admin_user(member):
        return True

    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True

    return any(role.id in TICKET_MANAGER_ROLE_IDS for role in member.roles)


async def require_ticket_manager(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Comando usabile solo nel server.", ephemeral=True)
        return False

    if not is_ticket_manager(interaction.user):
        await interaction.response.send_message(
            "Solo gestione server / admin possono configurare i ticket.",
            ephemeral=True,
        )
        return False

    return True


def can_handle_ticket(member: discord.Member, config: TicketConfig) -> bool:
    if is_admin_user(member):
        return True

    if member.guild_permissions.administrator or member.guild_permissions.manage_channels:
        return True

    support_ids = set(config.support_role_ids)
    return any(role.id in support_ids for role in member.roles)


def section_from_topic(topic: str | None) -> str | None:
    if not topic:
        return None

    match = re.search(r"ticket_type=([a-z_]+)", topic)
    if not match:
        return None

    return match.group(1)


def format_ticket_text(
    template: str,
    *,
    ticket_id: int | str,
    ticket_type: TicketType,
    user: discord.abc.User,
    subject: str,
    description: str,
    support_mentions: str,
) -> str:
    values = SafeFormatDict(
        ticket_id=str(ticket_id),
        type=ticket_type.label,
        user=user.mention,
        user_name=str(user),
        subject=subject,
        description=description,
        support=support_mentions,
    )
    return template.format_map(values)


class TicketReasonModal(discord.ui.Modal):
    def __init__(self, cog: Tickets, ticket_type: TicketType) -> None:
        super().__init__(title=f"Apri ticket: {ticket_type.label}")
        self.cog = cog
        self.ticket_type = ticket_type

        self.subject = discord.ui.TextInput(
            label="Oggetto",
            placeholder="Scrivi un titolo breve",
            max_length=80,
        )
        self.description = discord.ui.TextInput(
            label="Descrizione",
            placeholder="Spiega il problema o la richiesta con qualche dettaglio",
            style=discord.TextStyle.paragraph,
            max_length=1200,
        )
        self.add_item(self.subject)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.create_ticket(
            interaction=interaction,
            ticket_type=self.ticket_type,
            subject=str(self.subject.value),
            description=str(self.description.value),
        )


class TicketOpenButton(discord.ui.Button):
    def __init__(self, cog: Tickets, ticket_type: TicketType) -> None:
        super().__init__(
            label=ticket_type.label,
            style=ticket_type.button_style,
            custom_id=f"maggika_ticket_open:{ticket_type.key}",
        )
        self.cog = cog
        self.ticket_type = ticket_type

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TicketReasonModal(self.cog, self.ticket_type))


class TicketPanelView(discord.ui.View):
    def __init__(self, cog: Tickets) -> None:
        super().__init__(timeout=None)
        for ticket_type in TICKET_TYPES.values():
            self.add_item(TicketOpenButton(cog, ticket_type))


class CloseTicketView(discord.ui.View):
    def __init__(self, cog: Tickets) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Chiudi ticket",
        style=discord.ButtonStyle.danger,
        custom_id="maggika_close_ticket_button",
    )
    async def close_ticket_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.cog.close_current_ticket(interaction, "Chiuso dal pulsante")


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    owner_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    closed_at TEXT
                )
                """
            )

            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tickets)").fetchall()
            }

            if "ticket_type" not in columns:
                conn.execute("ALTER TABLE tickets ADD COLUMN ticket_type TEXT")

            if "subject" not in columns:
                conn.execute("ALTER TABLE tickets ADD COLUMN subject TEXT")

            if "transcript_channel_id" not in columns:
                conn.execute("ALTER TABLE tickets ADD COLUMN transcript_channel_id INTEGER")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_settings (
                    guild_id INTEGER NOT NULL,
                    ticket_type TEXT NOT NULL,
                    support_role_ids TEXT,
                    category_id INTEGER,
                    transcript_channel_id INTEGER,
                    PRIMARY KEY (guild_id, ticket_type)
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_messages (
                    guild_id INTEGER NOT NULL,
                    ticket_type TEXT NOT NULL,
                    open_title TEXT,
                    open_message TEXT,
                    PRIMARY KEY (guild_id, ticket_type)
                )
                """
            )

    def get_config(self, guild_id: int, ticket_type: TicketType) -> TicketConfig:
        with db() as conn:
            settings_row = conn.execute(
                """
                SELECT support_role_ids, category_id, transcript_channel_id
                FROM ticket_settings
                WHERE guild_id = ? AND ticket_type = ?
                """,
                (guild_id, ticket_type.key),
            ).fetchone()
            message_row = conn.execute(
                """
                SELECT open_title, open_message
                FROM ticket_messages
                WHERE guild_id = ? AND ticket_type = ?
                """,
                (guild_id, ticket_type.key),
            ).fetchone()

        support_role_ids = parse_ids(
            get_row_value(settings_row, "support_role_ids"),
            ticket_type.default_support_role_ids,
        )
        category_id = int(
            get_row_value(settings_row, "category_id", ticket_type.default_category_id)
            or ticket_type.default_category_id
        )
        transcript_channel_id = int(
            get_row_value(
                settings_row,
                "transcript_channel_id",
                ticket_type.default_transcript_channel_id,
            )
            or ticket_type.default_transcript_channel_id
        )
        open_title = str(
            get_row_value(message_row, "open_title", DEFAULT_OPEN_TITLE)
            or DEFAULT_OPEN_TITLE
        )
        open_message = str(
            get_row_value(message_row, "open_message", DEFAULT_OPEN_MESSAGE)
            or DEFAULT_OPEN_MESSAGE
        )

        return TicketConfig(
            ticket_type=ticket_type,
            support_role_ids=support_role_ids,
            category_id=category_id,
            transcript_channel_id=transcript_channel_id,
            open_title=open_title,
            open_message=open_message,
        )

    def upsert_ticket_setting(
        self,
        guild_id: int,
        ticket_type_key: str,
        *,
        support_role_ids: tuple[int, ...] | None = None,
        category_id: int | None = None,
        transcript_channel_id: int | None = None,
    ) -> None:
        with db() as conn:
            conn.execute(
                """
                INSERT INTO ticket_settings (
                    guild_id,
                    ticket_type,
                    support_role_ids,
                    category_id,
                    transcript_channel_id
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, ticket_type) DO UPDATE SET
                    support_role_ids = COALESCE(excluded.support_role_ids, support_role_ids),
                    category_id = COALESCE(excluded.category_id, category_id),
                    transcript_channel_id = COALESCE(excluded.transcript_channel_id, transcript_channel_id)
                """,
                (
                    guild_id,
                    ticket_type_key,
                    serialize_ids(support_role_ids) if support_role_ids is not None else None,
                    category_id,
                    transcript_channel_id,
                ),
            )

    @app_commands.command(name="ticket_panel", description="Invia il pannello ticket in un canale.")
    @app_commands.describe(
        canale="Canale dove inviare il pannello",
        titolo="Titolo embed del pannello",
        descrizione="Descrizione embed del pannello",
    )
    async def ticket_panel(
        self,
        interaction: discord.Interaction,
        canale: discord.TextChannel | None = None,
        titolo: str = DEFAULT_PANEL_TITLE,
        descrizione: str = DEFAULT_PANEL_DESCRIPTION,
    ) -> None:
        if not await require_ticket_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        target_channel = canale or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("Canale pannello non valido.", ephemeral=True)
            return

        embed = discord.Embed(
            title=titolo,
            description=descrizione,
            color=discord.Color.gold(),
        )

        await target_channel.send(embed=embed, view=TicketPanelView(self))
        await interaction.response.send_message(
            f"Pannello ticket inviato in {target_channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="ticket_set_roles", description="Setta i ruoli supporto per un tipo ticket.")
    @app_commands.describe(
        tipo="Tipo di ticket",
        ruolo_1="Primo ruolo supporto",
        ruolo_2="Secondo ruolo supporto opzionale",
        ruolo_3="Terzo ruolo supporto opzionale",
    )
    @app_commands.choices(tipo=TICKET_CHOICES)
    async def ticket_set_roles(
        self,
        interaction: discord.Interaction,
        tipo: app_commands.Choice[str],
        ruolo_1: discord.Role,
        ruolo_2: discord.Role | None = None,
        ruolo_3: discord.Role | None = None,
    ) -> None:
        if not await require_ticket_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        roles = tuple(dict.fromkeys(role.id for role in (ruolo_1, ruolo_2, ruolo_3) if role))
        self.upsert_ticket_setting(
            interaction.guild.id,
            tipo.value,
            support_role_ids=roles,
        )
        mentions = " ".join(f"<@&{role_id}>" for role_id in roles)
        await interaction.response.send_message(
            f"Ruoli supporto per **{tipo.name}** aggiornati: {mentions}",
            ephemeral=True,
        )

    @app_commands.command(name="ticket_set_category", description="Setta la categoria per un tipo ticket.")
    @app_commands.describe(tipo="Tipo di ticket", categoria="Categoria dove creare i ticket")
    @app_commands.choices(tipo=TICKET_CHOICES)
    async def ticket_set_category(
        self,
        interaction: discord.Interaction,
        tipo: app_commands.Choice[str],
        categoria: discord.CategoryChannel,
    ) -> None:
        if not await require_ticket_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        self.upsert_ticket_setting(
            interaction.guild.id,
            tipo.value,
            category_id=categoria.id,
        )
        await interaction.response.send_message(
            f"Categoria per **{tipo.name}** aggiornata: `{categoria.name}`",
            ephemeral=True,
        )

    @app_commands.command(name="ticket_set_transcript", description="Setta il canale transcript per un tipo ticket.")
    @app_commands.describe(tipo="Tipo di ticket", canale="Canale dove inviare i transcript")
    @app_commands.choices(tipo=TICKET_CHOICES)
    async def ticket_set_transcript(
        self,
        interaction: discord.Interaction,
        tipo: app_commands.Choice[str],
        canale: discord.TextChannel,
    ) -> None:
        if not await require_ticket_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        self.upsert_ticket_setting(
            interaction.guild.id,
            tipo.value,
            transcript_channel_id=canale.id,
        )
        await interaction.response.send_message(
            f"Canale transcript per **{tipo.name}** aggiornato: {canale.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="ticket_set_open_message",
        description="Personalizza il messaggio standard di apertura ticket.",
    )
    @app_commands.describe(
        tipo="Tipo di ticket",
        titolo="Titolo embed. Placeholder: {ticket_id}, {type}, {user}, {subject}",
        messaggio="Descrizione embed. Placeholder: {user}, {subject}, {description}, {support}",
    )
    @app_commands.choices(tipo=TICKET_CHOICES)
    async def ticket_set_open_message(
        self,
        interaction: discord.Interaction,
        tipo: app_commands.Choice[str],
        titolo: str,
        messaggio: str,
    ) -> None:
        if not await require_ticket_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        with db() as conn:
            conn.execute(
                """
                INSERT INTO ticket_messages (guild_id, ticket_type, open_title, open_message)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, ticket_type) DO UPDATE SET
                    open_title = excluded.open_title,
                    open_message = excluded.open_message
                """,
                (interaction.guild.id, tipo.value, titolo, messaggio),
            )

        await interaction.response.send_message(
            f"Messaggio apertura per **{tipo.name}** aggiornato.",
            ephemeral=True,
        )

    @app_commands.command(name="ticket_reset_open_message", description="Resetta il messaggio apertura ticket.")
    @app_commands.describe(tipo="Tipo di ticket")
    @app_commands.choices(tipo=TICKET_CHOICES)
    async def ticket_reset_open_message(
        self,
        interaction: discord.Interaction,
        tipo: app_commands.Choice[str],
    ) -> None:
        if not await require_ticket_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        with db() as conn:
            conn.execute(
                """
                DELETE FROM ticket_messages
                WHERE guild_id = ? AND ticket_type = ?
                """,
                (interaction.guild.id, tipo.value),
            )

        await interaction.response.send_message(
            f"Messaggio apertura per **{tipo.name}** resettato ai default.",
            ephemeral=True,
        )

    @app_commands.command(name="ticket_settings", description="Mostra la configurazione ticket.")
    async def ticket_settings(self, interaction: discord.Interaction) -> None:
        if not await require_ticket_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Configurazione ticket",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )

        for ticket_type in TICKET_TYPES.values():
            config = self.get_config(interaction.guild.id, ticket_type)
            roles = " ".join(f"<@&{role_id}>" for role_id in config.support_role_ids) or "Nessuno"
            category = f"<#{config.category_id}>"
            transcript = f"<#{config.transcript_channel_id}>"
            embed.add_field(
                name=ticket_type.label,
                value=(
                    f"Ruoli: {roles}\n"
                    f"Categoria: {category}\n"
                    f"Transcript: {transcript}"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def create_ticket(
        self,
        interaction: discord.Interaction,
        ticket_type: TicketType,
        subject: str,
        description: str,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Usa il ticket dentro il server.", ephemeral=True)
            return

        config = self.get_config(interaction.guild.id, ticket_type)
        with db() as conn:
            active = conn.execute(
                """
                SELECT channel_id FROM tickets
                WHERE guild_id = ? AND owner_id = ? AND ticket_type = ? AND status = 'open'
                """,
                (interaction.guild.id, interaction.user.id, ticket_type.key),
            ).fetchone()

        if active:
            existing = interaction.guild.get_channel(active["channel_id"])
            if existing:
                await interaction.response.send_message(
                    f"Hai gia un ticket aperto in **{ticket_type.label}**: {existing.mention}",
                    ephemeral=True,
                )
                return

        category = interaction.guild.get_channel(config.category_id)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                f"Categoria per **{ticket_type.label}** non trovata.",
                ephemeral=True,
            )
            return

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }

        if interaction.guild.me:
            overwrites[interaction.guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
            )

        support_mentions_list: list[str] = []
        for role_id in config.support_role_ids:
            role = interaction.guild.get_role(role_id)
            if not role:
                continue

            support_mentions_list.append(role.mention)
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                manage_messages=True,
            )

        support_mentions = " ".join(support_mentions_list)
        topic = (
            f"ticket_owner={interaction.user.id};"
            f"ticket_type={ticket_type.key};"
            f"transcript_channel={config.transcript_channel_id}"
        )

        try:
            channel = await interaction.guild.create_text_channel(
                name=f"{ticket_type.slug}-{clean_name(interaction.user.display_name)}",
                category=category,
                topic=topic,
                overwrites=overwrites,
                reason=f"Ticket {ticket_type.label} aperto da {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Non posso creare il canale ticket. Controlla i permessi del bot.",
                ephemeral=True,
            )
            return

        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tickets (
                    guild_id,
                    owner_id,
                    channel_id,
                    reason,
                    status,
                    created_at,
                    ticket_type,
                    subject,
                    transcript_channel_id
                )
                VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)
                """,
                (
                    interaction.guild.id,
                    interaction.user.id,
                    channel.id,
                    description,
                    now_iso(),
                    ticket_type.key,
                    subject,
                    config.transcript_channel_id,
                ),
            )
            ticket_id = cursor.lastrowid

        embed_title = format_ticket_text(
            config.open_title,
            ticket_id=ticket_id,
            ticket_type=ticket_type,
            user=interaction.user,
            subject=subject,
            description=description,
            support_mentions=support_mentions,
        )
        embed_description = format_ticket_text(
            config.open_message,
            ticket_id=ticket_id,
            ticket_type=ticket_type,
            user=interaction.user,
            subject=subject,
            description=description,
            support_mentions=support_mentions,
        )

        embed = discord.Embed(
            title=trim_embed_text(embed_title, 256),
            description=trim_embed_text(embed_description),
            color=ticket_type.color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Usa il pulsante qui sotto per chiudere il ticket.")

        await channel.send(
            f"{interaction.user.mention} {support_mentions}".strip(),
            embed=embed,
            view=CloseTicketView(self),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False),
        )

        await interaction.response.send_message(
            f"Ticket creato: {channel.mention}",
            ephemeral=True,
        )

    async def fetch_ticket_row(self, guild_id: int, channel_id: int) -> object:
        with db() as conn:
            return conn.execute(
                """
                SELECT * FROM tickets
                WHERE guild_id = ? AND channel_id = ? AND status = 'open'
                """,
                (guild_id, channel_id),
            ).fetchone()

    async def build_transcript(self, channel: discord.TextChannel) -> discord.File:
        lines = [
            f"Transcript canale: #{channel.name}",
            f"Canale ID: {channel.id}",
            f"Creato il: {datetime.now(timezone.utc).isoformat()}",
            "",
        ]

        async for message in channel.history(limit=1000, oldest_first=True):
            created = message.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            content = message.content or ""
            lines.append(f"[{created}] {message.author} ({message.author.id}): {content}")

            for embed in message.embeds:
                if embed.title:
                    lines.append(f"  Embed title: {embed.title}")
                if embed.description:
                    lines.append(f"  Embed description: {embed.description}")

            for attachment in message.attachments:
                lines.append(f"  Attachment: {attachment.url}")

            lines.append("")

        data = "\n".join(lines).encode("utf-8")
        return discord.File(io.BytesIO(data), filename=f"transcript-{channel.id}.txt")

    async def send_transcript(
        self,
        interaction: discord.Interaction,
        row: object,
        config: TicketConfig,
        reason: str,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return

        transcript_channel = interaction.guild.get_channel(config.transcript_channel_id)
        if not isinstance(transcript_channel, discord.TextChannel):
            log.warning("Transcript channel not found: %s", config.transcript_channel_id)
            return

        owner_id = int(get_row_value(row, "owner_id", 0) or 0)
        subject = str(get_row_value(row, "subject", "Nessun oggetto") or "Nessun oggetto")
        file = await self.build_transcript(interaction.channel)

        embed = discord.Embed(
            title=f"Transcript - {config.ticket_type.label}",
            color=config.ticket_type.color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Ticket", value=interaction.channel.mention, inline=True)
        embed.add_field(name="Aperto da", value=f"<@{owner_id}>", inline=True)
        embed.add_field(name="Chiuso da", value=interaction.user.mention, inline=True)
        embed.add_field(name="Oggetto", value=subject, inline=False)
        embed.add_field(name="Motivo chiusura", value=reason, inline=False)

        await transcript_channel.send(embed=embed, file=file)

    async def close_current_ticket(
        self,
        interaction: discord.Interaction,
        reason: str,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Questo comando si usa dentro un ticket.", ephemeral=True)
            return

        row = await self.fetch_ticket_row(interaction.guild.id, interaction.channel.id)
        if row is None:
            await interaction.response.send_message("Questo canale non sembra un ticket aperto.", ephemeral=True)
            return

        ticket_type_key = str(get_row_value(row, "ticket_type", "") or "")
        if not ticket_type_key:
            ticket_type_key = section_from_topic(interaction.channel.topic) or ""

        ticket_type = TICKET_TYPES.get(ticket_type_key)
        if ticket_type is None:
            await interaction.response.send_message("Tipo ticket non riconosciuto.", ephemeral=True)
            return

        config = self.get_config(interaction.guild.id, ticket_type)
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        owner_id = int(get_row_value(row, "owner_id", 0) or 0)
        can_close = bool(
            member
            and (
                member.id == owner_id
                or can_handle_ticket(member, config)
                or is_staff(member)
            )
        )

        if not can_close:
            await interaction.response.send_message("Non puoi chiudere questo ticket.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Ticket in chiusura. Salvo il transcript e cancello il canale tra 5 secondi.",
        )

        try:
            await self.send_transcript(interaction, row, config, reason)
        except discord.DiscordException:
            log.exception("Could not send ticket transcript")

        with db() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = 'closed', closed_at = ?
                WHERE id = ?
                """,
                (now_iso(), get_row_value(row, "id")),
            )

        await asyncio.sleep(5)
        await interaction.channel.delete(reason=reason)

    @app_commands.command(name="close_ticket", description="Chiudi il ticket corrente.")
    @app_commands.describe(motivo="Motivo chiusura")
    async def close_ticket(
        self,
        interaction: discord.Interaction,
        motivo: str = "Ticket chiuso",
    ) -> None:
        await self.close_current_ticket(interaction, motivo)


async def setup(bot: commands.Bot) -> None:
    cog = Tickets(bot)
    bot.add_view(TicketPanelView(cog))
    bot.add_view(CloseTicketView(cog))
    await bot.add_cog(cog)
