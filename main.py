import logging

import discord
from discord import app_commands
from discord.ext import commands

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

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = [
    "cogs.verification",
    "cogs.notifications",
    "cogs.hours",
    "cogs.reports",
    "cogs.tickets",
    "cogs.disboard",
    "cogs.fun",
]


@bot.event
async def setup_hook() -> None:
    init_db()

    for cog in COGS:
        await bot.load_extension(cog)

    if settings.guild_id:
        guild = discord.Object(id=settings.guild_id)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"Comandi slash sincronizzati nel server: {settings.guild_id}")
    else:
        await bot.tree.sync()
        print("Comandi slash sincronizzati globalmente.")


@bot.event
async def on_ready() -> None:
    print(f"Bot online: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="/help_base"))


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"Comando in cooldown. Riprova tra {error.retry_after:.0f}s."
    else:
        logging.exception("Errore comando slash", exc_info=error)
        message = "Errore interno del bot. Controlla la console."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="help_base", description="Lista comandi base.")
async def help_base(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        """
**Maggika Bot**

`/setup_verify` crea pannello verifica con pulsante
`/ping` controlla il bot
`/castamagic_ping` notifica Castamagic
`/clock_in` inizia turno
`/clock_out` chiudi turno
`/my_hours` vedi le tue ore
`/hours` vedi ore membro, staff
`/report` invia report
`/ticket` apri ticket
`/close_ticket` chiudi ticket
`/spam_ping` ping limitato
`/friend_ping` alias ping amico
        """,
        ephemeral=True,
    )


if not settings.token:
    raise RuntimeError("Metti DISCORD_TOKEN nel file .env")

bot.run(settings.token)
