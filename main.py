import logging
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from checks import ADMIN_USER_IDS, ALWAYS_STAFF_ROLE_IDS, is_admin_user, is_staff
from config import settings
from database import init_db


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.AutoShardedBot(command_prefix="!", intents=intents)

COGS = [
    "cogs.verification",
    "cogs.hours",
    "cogs.tickets",
    "cogs.disboard",
    "cogs.risposta_ping",
    "cogs.castamaggic_not",
    "cogs.spam_ping",
]


DB_FULL_MESSAGE = (
    "Database non scrivibile: il disco dell'hosting e pieno. "
    "Libera spazio o aumenta lo storage, poi riprova."
)


def is_storage_error(error: BaseException) -> bool:
    text = str(error).lower()
    return (
        isinstance(error, sqlite3.OperationalError)
        and ("database or disk is full" in text or "no space left" in text)
    )


@bot.event
async def setup_hook() -> None:
    init_db()

    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logging.info("Cog caricato: %s", cog)
        except commands.ExtensionNotFound:
            logging.warning("Cog non trovato, lo salto: %s", cog)
        except commands.NoEntryPointError:
            logging.warning("Cog senza setup(), lo salto: %s", cog)

    if settings.guild_id:
        try:
            guild = discord.Object(id=settings.guild_id)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            command_names = ", ".join(command.name for command in synced)
            print(
                f"Comandi slash sincronizzati nel server: {settings.guild_id} "
                f"({len(synced)}): {command_names}"
            )
        except discord.Forbidden:
            logging.warning(
                "Sync slash fallita: Missing Access. Controlla GUILD_ID e invita "
                "il bot con gli scope bot + applications.commands."
            )
            print(
                "Sync slash fallita: Missing Access. Controlla GUILD_ID e invita "
                "il bot con gli scope bot + applications.commands."
            )
        except discord.HTTPException as error:
            logging.warning("Sync slash fallita: %s", error)
            print(f"Sync slash fallita: {error}")
    else:
        try:
            synced = await bot.tree.sync()
            command_names = ", ".join(command.name for command in synced)
            print(
                f"Comandi slash sincronizzati globalmente "
                f"({len(synced)}): {command_names}"
            )
        except discord.HTTPException as error:
            logging.warning("Sync slash globale fallita: %s", error)
            print(f"Sync slash globale fallita: {error}")


@bot.event
async def on_ready() -> None:
    print(f"Bot online: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="/help_base"))


@bot.event
async def on_shard_ready(shard_id: int) -> None:
    print(f"Shard pronta: {shard_id}")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"Comando in cooldown. Riprova tra {error.retry_after:.0f}s."
    elif isinstance(error, app_commands.CommandInvokeError) and is_storage_error(error.original):
        logging.warning("Comando slash bloccato: database o disco pieno.")
        message = DB_FULL_MESSAGE
    else:
        logging.exception("Errore comando slash", exc_info=error)
        message = "Errore interno del bot. Controlla la console."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("Comando usabile solo dentro un server.")
        return

    if isinstance(error, commands.CommandInvokeError) and is_storage_error(error.original):
        await ctx.send(DB_FULL_MESSAGE)
        return

    logging.exception("Errore comando testuale", exc_info=error)
    await ctx.send("Errore interno del comando. Controlla la console.")


@bot.command(name="syncslash", aliases=["sync_slash"])
@commands.guild_only()
async def syncslash(ctx: commands.Context) -> None:
    if ctx.guild is None:
        await ctx.send("Comando usabile solo dentro un server.")
        return

    if not isinstance(ctx.author, discord.Member) or not is_staff(ctx.author):
        await ctx.send("Non hai i permessi per usare questo comando.")
        return

    guild = discord.Object(id=ctx.guild.id)
    bot.tree.copy_global_to(guild=guild)

    try:
        synced = await bot.tree.sync(guild=guild)
    except discord.Forbidden:
        await ctx.send(
            "Sync fallita: Missing Access. Reinvita il bot con gli scope `bot` e `applications.commands`."
        )
        return
    except discord.HTTPException as error:
        await ctx.send(f"Sync fallita: `{error}`")
        return

    command_names = ", ".join(command.name for command in synced)
    await ctx.send(f"Sync completata: `{len(synced)}` comandi.\n{command_names}")


@bot.command(name="resetslash", aliases=["resetslsh", "resetsslash", "reset_slash"])
@commands.guild_only()
async def resetslash(ctx: commands.Context) -> None:
    if ctx.guild is None:
        await ctx.send("Comando usabile solo dentro un server.")
        return

    if not isinstance(ctx.author, discord.Member) or not is_staff(ctx.author):
        await ctx.send("Non hai i permessi per usare questo comando.")
        return

    guild = discord.Object(id=ctx.guild.id)

    try:
        bot.tree.clear_commands(guild=guild)
        await bot.tree.sync(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
    except discord.Forbidden:
        await ctx.send(
            "Reset sync fallito: Missing Access. Reinvita il bot con gli scope `bot` e `applications.commands`."
        )
        return
    except discord.HTTPException as error:
        await ctx.send(f"Reset sync fallito: `{error}`")
        return

    command_names = ", ".join(command.name for command in synced)
    await ctx.send(f"Reset slash completato: `{len(synced)}` comandi.\n{command_names}")


@bot.command(name="permcheck", aliases=["permscheck", "perm_check"])
@commands.guild_only()
async def permcheck(ctx: commands.Context) -> None:
    if not isinstance(ctx.author, discord.Member):
        await ctx.send("Comando usabile solo dentro un server.")
        return

    member = ctx.author
    role_ids = ", ".join(str(role.id) for role in member.roles if role.name != "@everyone")
    staff_ids = set(settings.staff_role_ids) | ALWAYS_STAFF_ROLE_IDS
    has_staff_role = any(role.id in staff_ids for role in member.roles)

    hours_manager_ids = {
        1467908260316184777,
        1467907829556969566,
        1476317246077796352,
        1505553486065041458,
        1472188981197279264,
    }
    ticket_manager_ids = hours_manager_ids
    disboard_manager_ids = {
        1467908260316184777,
        1467907829556969566,
        1476317246077796352,
        1505553486065041458,
        1472188981197279264,
        1472188572789510330,
    }
    castamaggic_manager_ids = disboard_manager_ids

    is_hours_manager = (
        is_admin_user(member)
        or member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
        or any(role.id in hours_manager_ids for role in member.roles)
    )
    is_ticket_manager = (
        is_admin_user(member)
        or member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
        or any(role.id in ticket_manager_ids for role in member.roles)
    )
    is_disboard_manager = (
        is_admin_user(member)
        or member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
        or is_staff(member)
        or any(role.id in disboard_manager_ids for role in member.roles)
    )
    is_castamaggic_manager = (
        is_admin_user(member)
        or member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
        or is_staff(member)
        or any(role.id in castamaggic_manager_ids for role in member.roles)
    )

    message = (
        f"Permessi per {member.mention}\n"
        f"Staff generale: `{is_staff(member)}`\n"
        f"Ruolo staff in .env: `{has_staff_role}`\n"
        f"Manager ore: `{is_hours_manager}`\n"
        f"Manager ticket: `{is_ticket_manager}`\n"
        f"Manager DISBOARD: `{is_disboard_manager}`\n"
        f"Manager Castamaggic: `{is_castamaggic_manager}`\n"
        f"Admin interno bot: `{member.id in ADMIN_USER_IDS}`\n"
        f"Administrator: `{member.guild_permissions.administrator}`\n"
        f"Manage Guild: `{member.guild_permissions.manage_guild}`\n"
        f"Ruoli ID: `{role_ids or 'nessun ruolo'}`"
    )
    await ctx.send(message)


@bot.tree.command(name="help_base", description="Lista comandi base.")
async def help_base(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        """
**Maggika Bot**

`/setup_verification` crea pannello verifica con pulsante
`/verification_set_role` setta il ruolo dato dal pulsante verifica
`/clock_in` inizia turno
`/clock_out` chiudi turno
`/my_hours` vedi le tue ore
`/hours` vedi ore membro, staff
`/cartellino_panel` invia pannello cartellino
`/hours_reset` resetta ore staff
`/cartellino_annulla` annulla un timbro
`/cartellino_set_logs` setta log cartellino
`/staff_richiamo` richiamo staff con ruolo temporaneo
`/staff_richiamo_roles` ruoli autorizzati ai richiami
`/staff_archive` archivio staff
`/disboard_set_timer` setta timer bump
`/disboard_status` prossimo reminder bump
`/disboard_cancel` cancella reminder bump
`/castamaggic_setup` ping nuovo video Castamaggic
`/castamaggic_set_channel` setta canale notifiche
`/castamaggic_set_role` setta ruolo ping
`/castamaggic_clear_role` toglie il ruolo ping
`/castamaggic_set_youtube` setta canale YouTube
`/castamaggic_set_interval` setta intervallo
`/castamaggic_set_message` setta messaggio
`/castamaggic_toggle` attiva/disattiva notifiche
`/castamaggic_check` controlla video Castamaggic
`/castamaggic_status` config video Castamaggic
`/ticket_panel` invia pannello ticket
`/ticket_set_roles` setta ruoli supporto ticket
`/ticket_set_category` setta categoria ticket
`/ticket_set_transcript` setta canale transcript
`/ticket_set_open_message` personalizza messaggio apertura
`/ticket_reset_open_message` resetta messaggio apertura
`/ticket_settings` mostra config ticket
`/close_ticket` chiudi ticket
`/spam_ping` ping limitato
        """,
        ephemeral=True,
    )


if not settings.token:
    raise RuntimeError("Metti DISCORD_TOKEN nel file .env")

bot.run(settings.token)
