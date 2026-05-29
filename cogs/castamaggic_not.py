from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from checks import is_admin_user, is_staff
from config import settings
from database import db


log = logging.getLogger("maggika.castamaggic_not")

YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
DEFAULT_YOUTUBE_CHANNEL_ID = "UCbfdov_Cbl6VY_Fmrp8FkDg"
DEFAULT_CHECK_MINUTES = 30
DEFAULT_ANNOUNCE_MESSAGE = "Castamaggic ha pubblicato un nuovo video."
ATOM_NS = "{http://www.w3.org/2005/Atom}"
YT_NS = "{http://www.youtube.com/xml/schemas/2015}"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"

CASTAMAGGIC_MANAGER_ROLE_IDS = {
    1467908260316184777,  # Owner
    1467907829556969566,  # Manager
    1476317246077796352,  # Staff Director
    1505553486065041458,  # Tecnico
    1472188981197279264,  # Administrator
    1472188572789510330,  # Staff generale
}


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    title: str
    url: str
    published: str
    thumbnail: str | None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_announce_message(template: str, video: VideoInfo) -> str:
    try:
        return template.format(
            title=video.title,
            url=video.url,
            published=video.published,
        )
    except (KeyError, ValueError):
        return DEFAULT_ANNOUNCE_MESSAGE


def announce_content(role_id: int | None, description: str, video: VideoInfo) -> str:
    lines = []
    if role_id:
        lines.append(f"<@&{role_id}>")
    if description:
        lines.append(description)
    if video.url not in description:
        lines.append(video.url)

    content = "\n".join(lines).strip()
    return content[:2000] if len(content) > 2000 else content


async def require_castamaggic_manager(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Comando usabile solo nel server.", ephemeral=True)
        return False

    if (
        is_admin_user(interaction.user)
        or interaction.user.guild_permissions.administrator
        or interaction.user.guild_permissions.manage_guild
        or is_staff(interaction.user)
        or any(role.id in CASTAMAGGIC_MANAGER_ROLE_IDS for role in interaction.user.roles)
    ):
        return True

    await interaction.response.send_message(
        "Non hai i permessi per gestire Castamaggic.",
        ephemeral=True,
    )
    return False


def parse_video_entry(entry: ET.Element) -> VideoInfo | None:
    video_id = entry.findtext(f"{YT_NS}videoId")
    title = entry.findtext(f"{ATOM_NS}title") or "Nuovo video"
    published = entry.findtext(f"{ATOM_NS}published") or now_iso()
    link = entry.find(f"{ATOM_NS}link")
    url = link.attrib.get("href") if link is not None else ""

    thumbnail = None
    media_group = entry.find(f"{MEDIA_NS}group")
    if media_group is not None:
        media_thumbnail = media_group.find(f"{MEDIA_NS}thumbnail")
        if media_thumbnail is not None:
            thumbnail = media_thumbnail.attrib.get("url")

    if not video_id:
        return None

    if not url:
        url = f"https://www.youtube.com/watch?v={video_id}"

    return VideoInfo(
        video_id=video_id,
        title=title,
        url=url,
        published=published,
        thumbnail=thumbnail,
    )


def parse_feed_videos(xml_text: str) -> list[VideoInfo]:
    root = ET.fromstring(xml_text)
    videos = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        video = parse_video_entry(entry)
        if video is not None:
            videos.append(video)
    return videos


def parse_latest_video(xml_text: str) -> VideoInfo | None:
    videos = parse_feed_videos(xml_text)
    return videos[0] if videos else None


class CastamaggicNotif(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.poll_task: asyncio.Task[None] | None = None
        self.ensure_schema()

    def cog_unload(self) -> None:
        if self.poll_task:
            self.poll_task.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bootstrap_env_settings()
        if self.poll_task is None or self.poll_task.done():
            self.poll_task = asyncio.create_task(self.poll_loop())

    def ensure_schema(self) -> None:
        with db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS castamaggic_settings (
                    guild_id INTEGER PRIMARY KEY,
                    youtube_channel_id TEXT NOT NULL,
                    announce_channel_id INTEGER NOT NULL,
                    ping_role_id INTEGER,
                    check_minutes INTEGER NOT NULL,
                    last_video_id TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(castamaggic_settings)").fetchall()
            }
            if "message_template" not in columns:
                conn.execute("ALTER TABLE castamaggic_settings ADD COLUMN message_template TEXT")
            if "enabled" not in columns:
                conn.execute("ALTER TABLE castamaggic_settings ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")

    def bootstrap_env_settings(self) -> None:
        if settings.castamagic_channel_id is None:
            return

        guild_id = settings.guild_id
        if guild_id is None and len(self.bot.guilds) == 1:
            guild_id = self.bot.guilds[0].id

        if guild_id is None:
            log.warning(
                "CASTAMAGIC_CHANNEL_ID is set but GUILD_ID is missing; "
                "run /castamaggic_setup or set GUILD_ID."
            )
            return

        if self.settings_row(guild_id) is not None:
            return

        self.upsert_settings(
            guild_id,
            youtube_channel_id=DEFAULT_YOUTUBE_CHANNEL_ID,
            announce_channel_id=settings.castamagic_channel_id,
            ping_role_id=settings.castamagic_role_id,
            check_minutes=DEFAULT_CHECK_MINUTES,
            message_template=DEFAULT_ANNOUNCE_MESSAGE,
            enabled=True,
            last_video_id=None,
        )
        log.info("Castamaggic settings created from .env for guild %s", guild_id)

    def settings_row(self, guild_id: int) -> object:
        with db() as conn:
            return conn.execute(
                """
                SELECT guild_id, youtube_channel_id, announce_channel_id, ping_role_id,
                       check_minutes, last_video_id, updated_at, message_template, enabled
                FROM castamaggic_settings
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()

    def upsert_settings(
        self,
        guild_id: int,
        *,
        youtube_channel_id: str | None = None,
        announce_channel_id: int | None = None,
        ping_role_id: int | None = None,
        clear_role: bool = False,
        check_minutes: int | None = None,
        message_template: str | None = None,
        enabled: bool | None = None,
        last_video_id: str | None = None,
    ) -> None:
        current = self.settings_row(guild_id)
        resolved_youtube = youtube_channel_id or (
            current["youtube_channel_id"] if current else DEFAULT_YOUTUBE_CHANNEL_ID
        )
        resolved_channel = announce_channel_id or (
            current["announce_channel_id"] if current else None
        )
        if resolved_channel is None:
            raise ValueError("announce_channel_missing")

        if clear_role:
            resolved_role = None
        elif ping_role_id is not None:
            resolved_role = ping_role_id
        else:
            resolved_role = current["ping_role_id"] if current else None

        resolved_minutes = check_minutes or (
            current["check_minutes"] if current else DEFAULT_CHECK_MINUTES
        )
        resolved_message = message_template if message_template is not None else (
            current["message_template"] if current else DEFAULT_ANNOUNCE_MESSAGE
        )
        resolved_enabled = int(enabled) if enabled is not None else (
            int(current["enabled"]) if current else 1
        )
        resolved_last_video_id = last_video_id if last_video_id is not None else (
            current["last_video_id"] if current else None
        )

        with db() as conn:
            conn.execute(
                """
                INSERT INTO castamaggic_settings (
                    guild_id,
                    youtube_channel_id,
                    announce_channel_id,
                    ping_role_id,
                    check_minutes,
                    last_video_id,
                    updated_at,
                    message_template,
                    enabled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    youtube_channel_id = excluded.youtube_channel_id,
                    announce_channel_id = excluded.announce_channel_id,
                    ping_role_id = excluded.ping_role_id,
                    check_minutes = excluded.check_minutes,
                    last_video_id = excluded.last_video_id,
                    updated_at = excluded.updated_at,
                    message_template = excluded.message_template,
                    enabled = excluded.enabled
                """,
                (
                    guild_id,
                    resolved_youtube,
                    resolved_channel,
                    resolved_role,
                    int(resolved_minutes),
                    resolved_last_video_id,
                    now_iso(),
                    resolved_message,
                    resolved_enabled,
                ),
            )

    async def fetch_latest_videos(self, youtube_channel_id: str) -> list[VideoInfo]:
        url = YOUTUBE_FEED_URL.format(channel_id=youtube_channel_id)
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    log.warning("YouTube feed returned %s for %s", response.status, youtube_channel_id)
                    return []

                return parse_feed_videos(await response.text())

    async def fetch_latest_video(self, youtube_channel_id: str) -> VideoInfo | None:
        videos = await self.fetch_latest_videos(youtube_channel_id)
        return videos[0] if videos else None

    async def announce_video(
        self,
        guild: discord.Guild,
        channel_id: int,
        role_id: int | None,
        video: VideoInfo,
        message_template: str | None = None,
    ) -> bool:
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                log.warning("Castamaggic announce channel %s not found", channel_id)
                return False

        if not isinstance(channel, discord.TextChannel):
            log.warning("Castamaggic announce channel %s is not a text channel", channel_id)
            return False

        description = format_announce_message(
            message_template or DEFAULT_ANNOUNCE_MESSAGE,
            video,
        )
        content = announce_content(role_id, description, video)
        embed = discord.Embed(
            title=video.title,
            url=video.url,
            description=description,
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Link", value=video.url, inline=False)
        if video.thumbnail:
            embed.set_image(url=video.thumbnail)

        mentions = discord.AllowedMentions(roles=True, users=False, everyone=False)
        try:
            await channel.send(content, embed=embed, allowed_mentions=mentions)
            return True
        except discord.Forbidden:
            log.warning("Missing permissions to send Castamaggic embed in channel %s", channel_id)
        except discord.HTTPException:
            log.exception("Could not send Castamaggic embed in channel %s", channel_id)

        try:
            await channel.send(content, allowed_mentions=mentions)
            return True
        except discord.HTTPException:
            log.exception("Could not send Castamaggic text fallback in channel %s", channel_id)
            return False

    def mark_last_video(self, guild_id: int, video_id: str) -> None:
        with db() as conn:
            conn.execute(
                """
                UPDATE castamaggic_settings
                SET last_video_id = ?, updated_at = ?
                WHERE guild_id = ?
                """,
                (video_id, now_iso(), guild_id),
            )

    async def check_guild(self, row: object, *, force_announce: bool = False) -> bool | None:
        guild = self.bot.get_guild(row["guild_id"])
        if guild is None:
            return False

        videos = await self.fetch_latest_videos(row["youtube_channel_id"])
        if not videos:
            return False

        last_video_id = row["last_video_id"]
        if force_announce:
            videos_to_announce = [videos[0]]
        elif last_video_id is None:
            videos_to_announce = [videos[0]]
        else:
            videos_to_announce = []
            for video in videos:
                if video.video_id == last_video_id:
                    break
                videos_to_announce.append(video)
            else:
                log.info(
                    "Last Castamaggic video %s is outside the current feed; announcing latest only",
                    last_video_id,
                )
                videos_to_announce = [videos[0]]

        if not videos_to_announce:
            return False

        announced = False
        for video in reversed(videos_to_announce):
            sent = await self.announce_video(
                guild,
                row["announce_channel_id"],
                row["ping_role_id"],
                video,
                row["message_template"] or DEFAULT_ANNOUNCE_MESSAGE,
            )
            if not sent:
                log.warning(
                    "Castamaggic video %s was not announced; keeping last_video_id unchanged",
                    video.video_id,
                )
                if not announced:
                    return None
                return announced

            self.mark_last_video(row["guild_id"], video.video_id)
            announced = True

        return announced

    async def poll_loop(self) -> None:
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            min_sleep = 300
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT guild_id, youtube_channel_id, announce_channel_id, ping_role_id,
                           check_minutes, last_video_id, message_template, enabled
                    FROM castamaggic_settings
                    WHERE enabled = 1
                    """
                ).fetchall()

            for row in rows:
                try:
                    await self.check_guild(row)
                    min_sleep = min(min_sleep, max(60, int(row["check_minutes"]) * 60))
                except Exception:
                    log.exception("Castamaggic video check failed for guild %s", row["guild_id"])

            await asyncio.sleep(min_sleep)

    @app_commands.command(name="castamaggic_setup", description="Configura ping nuovo video Castamaggic.")
    @app_commands.describe(
        youtube_channel_id="ID canale YouTube, non il nome",
        canale="Canale dove annunciare i video",
        ruolo="Ruolo da pingare",
        intervallo_minuti="Ogni quanti minuti controllare",
        annuncia_ultimo="Se true annuncia subito l'ultimo video trovato",
    )
    async def castamaggic_setup(
        self,
        interaction: discord.Interaction,
        youtube_channel_id: str,
        canale: discord.TextChannel,
        ruolo: discord.Role | None = None,
        intervallo_minuti: app_commands.Range[int, 5, 1440] = DEFAULT_CHECK_MINUTES,
        annuncia_ultimo: bool = False,
        messaggio: str = DEFAULT_ANNOUNCE_MESSAGE,
    ) -> None:
        if not await require_castamaggic_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        latest = None
        try:
            latest = await self.fetch_latest_video(youtube_channel_id)
        except Exception:
            log.exception("Could not fetch YouTube feed during setup")

        last_video_id = None if annuncia_ultimo else (latest.video_id if latest else None)
        self.upsert_settings(
            interaction.guild.id,
            youtube_channel_id=youtube_channel_id,
            announce_channel_id=canale.id,
            ping_role_id=ruolo.id if ruolo else None,
            clear_role=ruolo is None,
            check_minutes=int(intervallo_minuti),
            message_template=messaggio,
            enabled=True,
            last_video_id=last_video_id,
        )

        if annuncia_ultimo and latest:
            await self.announce_video(
                interaction.guild,
                canale.id,
                ruolo.id if ruolo else None,
                latest,
                messaggio,
            )
            with db() as conn:
                conn.execute(
                    """
                    UPDATE castamaggic_settings
                    SET last_video_id = ?, updated_at = ?
                    WHERE guild_id = ?
                    """,
                    (latest.video_id, now_iso(), interaction.guild.id),
                )

        await interaction.followup.send(
            (
                f"Ping Castamaggic configurato in {canale.mention}.\n"
                f"Ruolo: {ruolo.mention if ruolo else 'nessuno'}\n"
                f"Controllo ogni `{intervallo_minuti}` minuti."
            ),
            ephemeral=True,
        )

    @app_commands.command(name="castamaggic_check", description="Controlla subito se c'e' un nuovo video.")
    @app_commands.describe(annuncia_anche_se_gia_visto="Forza l'annuncio dell'ultimo video")
    async def castamaggic_check(
        self,
        interaction: discord.Interaction,
        annuncia_anche_se_gia_visto: bool = False,
    ) -> None:
        if not await require_castamaggic_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        with db() as conn:
            row = conn.execute(
                """
                SELECT guild_id, youtube_channel_id, announce_channel_id, ping_role_id,
                       check_minutes, last_video_id, message_template, enabled
                FROM castamaggic_settings
                WHERE guild_id = ?
                """,
                (interaction.guild.id,),
            ).fetchone()

        if row is None:
            await interaction.followup.send("Configura prima `/castamaggic_setup`.", ephemeral=True)
            return

        announced = await self.check_guild(row, force_announce=annuncia_anche_se_gia_visto)
        if announced is None:
            message = (
                "Video trovato, ma non riesco a inviarlo nel canale configurato. "
                "Controlla canale e permessi del bot."
            )
        else:
            message = "Video annunciato." if announced else "Nessun nuovo video trovato."

        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(name="castamaggic_status", description="Mostra la configurazione Castamaggic.")
    async def castamaggic_status(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        with db() as conn:
            row = conn.execute(
                """
                SELECT youtube_channel_id, announce_channel_id, ping_role_id,
                       check_minutes, last_video_id, updated_at, message_template, enabled
                FROM castamaggic_settings
                WHERE guild_id = ?
                """,
                (interaction.guild.id,),
            ).fetchone()

        if row is None:
            await interaction.response.send_message("Castamaggic non configurato.", ephemeral=True)
            return

        embed = discord.Embed(title="Castamaggic Ping", color=discord.Color.red())
        embed.add_field(name="YouTube Channel ID", value=f"`{row['youtube_channel_id']}`", inline=False)
        embed.add_field(name="Canale", value=f"<#{row['announce_channel_id']}>", inline=True)
        embed.add_field(
            name="Ruolo",
            value=f"<@&{row['ping_role_id']}>" if row["ping_role_id"] else "Nessuno",
            inline=True,
        )
        embed.add_field(name="Intervallo", value=f"{row['check_minutes']} min", inline=True)
        embed.add_field(name="Stato", value="Attivo" if row["enabled"] else "Disattivato", inline=True)
        embed.add_field(name="Ultimo video", value=row["last_video_id"] or "Nessuno", inline=False)
        embed.add_field(
            name="Messaggio",
            value=row["message_template"] or DEFAULT_ANNOUNCE_MESSAGE,
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="castamaggic_set_channel", description="Setta il canale notifiche Castamaggic.")
    @app_commands.describe(canale="Canale dove inviare le notifiche video")
    async def castamaggic_set_channel(
        self,
        interaction: discord.Interaction,
        canale: discord.TextChannel,
    ) -> None:
        if not await require_castamaggic_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        self.upsert_settings(interaction.guild.id, announce_channel_id=canale.id)
        await interaction.response.send_message(
            f"Canale notifiche Castamaggic impostato su {canale.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="castamaggic_set_role", description="Setta il ruolo da pingare per i video.")
    @app_commands.describe(ruolo="Ruolo da pingare quando esce un video")
    async def castamaggic_set_role(
        self,
        interaction: discord.Interaction,
        ruolo: discord.Role,
    ) -> None:
        if not await require_castamaggic_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        try:
            self.upsert_settings(interaction.guild.id, ping_role_id=ruolo.id)
        except ValueError:
            await interaction.response.send_message(
                "Prima imposta il canale con `/castamaggic_set_channel`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Ruolo ping Castamaggic impostato su {ruolo.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="castamaggic_clear_role", description="Toglie il ping ruolo dai video.")
    async def castamaggic_clear_role(self, interaction: discord.Interaction) -> None:
        if not await require_castamaggic_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        try:
            self.upsert_settings(interaction.guild.id, clear_role=True)
        except ValueError:
            await interaction.response.send_message(
                "Prima imposta il canale con `/castamaggic_set_channel`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Ping ruolo Castamaggic rimosso.", ephemeral=True)

    @app_commands.command(name="castamaggic_set_youtube", description="Setta l'ID canale YouTube Castamaggic.")
    @app_commands.describe(youtube_channel_id="ID canale YouTube che inizia con UC")
    async def castamaggic_set_youtube(
        self,
        interaction: discord.Interaction,
        youtube_channel_id: str = DEFAULT_YOUTUBE_CHANNEL_ID,
    ) -> None:
        if not await require_castamaggic_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        latest = None
        try:
            latest = await self.fetch_latest_video(youtube_channel_id)
        except Exception:
            log.exception("Could not fetch YouTube feed during set_youtube")

        try:
            self.upsert_settings(
                interaction.guild.id,
                youtube_channel_id=youtube_channel_id,
                last_video_id=latest.video_id if latest else None,
            )
        except ValueError:
            await interaction.followup.send(
                "Prima imposta il canale notifiche con `/castamaggic_set_channel`.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"Canale YouTube Castamaggic impostato su `{youtube_channel_id}`.",
            ephemeral=True,
        )

    @app_commands.command(name="castamaggic_set_interval", description="Setta ogni quanto controllare i video.")
    @app_commands.describe(minuti="Minuti tra un controllo e l'altro")
    async def castamaggic_set_interval(
        self,
        interaction: discord.Interaction,
        minuti: app_commands.Range[int, 5, 1440],
    ) -> None:
        if not await require_castamaggic_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        try:
            self.upsert_settings(interaction.guild.id, check_minutes=int(minuti))
        except ValueError:
            await interaction.response.send_message(
                "Prima imposta il canale con `/castamaggic_set_channel`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Intervallo controllo Castamaggic impostato a `{minuti}` minuti.",
            ephemeral=True,
        )

    @app_commands.command(name="castamaggic_set_message", description="Personalizza il messaggio video.")
    @app_commands.describe(
        messaggio="Placeholder disponibili: {title}, {url}, {published}"
    )
    async def castamaggic_set_message(
        self,
        interaction: discord.Interaction,
        messaggio: str,
    ) -> None:
        if not await require_castamaggic_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        try:
            self.upsert_settings(interaction.guild.id, message_template=messaggio)
        except ValueError:
            await interaction.response.send_message(
                "Prima imposta il canale con `/castamaggic_set_channel`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Messaggio Castamaggic aggiornato.", ephemeral=True)

    @app_commands.command(name="castamaggic_toggle", description="Attiva o disattiva le notifiche Castamaggic.")
    @app_commands.describe(attivo="True per attivare, False per disattivare")
    async def castamaggic_toggle(
        self,
        interaction: discord.Interaction,
        attivo: bool,
    ) -> None:
        if not await require_castamaggic_manager(interaction):
            return

        if not interaction.guild:
            await interaction.response.send_message("Usa il comando nel server.", ephemeral=True)
            return

        try:
            self.upsert_settings(interaction.guild.id, enabled=attivo)
        except ValueError:
            await interaction.response.send_message(
                "Prima imposta il canale con `/castamaggic_set_channel`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Notifiche Castamaggic {'attivate' if attivo else 'disattivate'}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CastamaggicNotif(bot))
