import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from checks import require_staff
from config import settings
from database import db


DB_FULL_MESSAGE = (
    "Database non scrivibile: il disco dell'hosting e pieno. "
    "Libera spazio o aumenta lo storage, poi riprova."
)


def is_storage_error(error: sqlite3.OperationalError) -> bool:
    text = str(error).lower()
    return "database or disk is full" in text or "no space left" in text


def init_verification_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_settings (
                guild_id INTEGER PRIMARY KEY,
                verified_role_id INTEGER
            )
            """
        )


def get_verified_role_id(guild_id: int) -> int | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT verified_role_id
            FROM verification_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        ).fetchone()

    if row and row["verified_role_id"]:
        return int(row["verified_role_id"])

    return settings.verified_role_id


def set_verified_role_id(guild_id: int, role_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO verification_settings (guild_id, verified_role_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET verified_role_id = excluded.verified_role_id
            """,
            (guild_id, role_id),
        )


class VerifyView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verificati!!",
        style=discord.ButtonStyle.success,
        custom_id="maggika_verify_button",
    )
    async def verify_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Puoi verificarti solo dentro al server.",
                ephemeral=True,
            )
            return

        try:
            verified_role_id = get_verified_role_id(interaction.guild.id)
        except sqlite3.OperationalError as error:
            if is_storage_error(error):
                await interaction.response.send_message(DB_FULL_MESSAGE, ephemeral=True)
                return
            raise

        if not verified_role_id:
            await interaction.response.send_message(
                "Ruolo della verifica non configurato o non esistente.",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(verified_role_id)
        if not role:
            await interaction.response.send_message(
                "Ruolo della verifica non trovato.",
                ephemeral=True,
            )
            return

        if role in interaction.user.roles:
            await interaction.response.send_message(
                "Sei gia verificato.",
                ephemeral=True,
            )
            return

        try:
            await interaction.user.add_roles(role, reason="Verifica tramite pulsante")
        except discord.Forbidden:
            await interaction.response.send_message(
                "Non posso assegnare questo ruolo. Metti il ruolo del bot sopra al ruolo verifica.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Verificato con successo! Ti e stato assegnato il ruolo {role.mention}.",
            ephemeral=True,
        )


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="setup_verification",
        description="Invia il pannello di verifica nel canale attuale.",
    )
    @app_commands.describe(
        ruolo="Ruolo da assegnare agli utenti verificati",
        titolo="Titolo del pannello",
        testo="Testo del pannello",
    )
    async def setup_verify(
        self,
        interaction: discord.Interaction,
        ruolo: discord.Role | None = None,
        titolo: str = "Verifica Membri del Server",
        testo: str = "Clicca sul pulsante qui sotto per verificarti.",
    ) -> None:
        if not await require_staff(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "Comando usabile solo dentro il server.",
                ephemeral=True,
            )
            return

        if interaction.channel is None:
            await interaction.response.send_message("Canale non valido.", ephemeral=True)
            return

        if ruolo:
            bot_member = interaction.guild.me
            if bot_member and (ruolo.managed or ruolo >= bot_member.top_role):
                await interaction.response.send_message(
                    "Non posso assegnare quel ruolo: metti il ruolo del bot sopra al ruolo verifica.",
                    ephemeral=True,
                )
                return

            try:
                set_verified_role_id(interaction.guild.id, ruolo.id)
            except sqlite3.OperationalError as error:
                if is_storage_error(error):
                    await interaction.response.send_message(DB_FULL_MESSAGE, ephemeral=True)
                    return
                raise

        try:
            verified_role_id = get_verified_role_id(interaction.guild.id)
        except sqlite3.OperationalError as error:
            if is_storage_error(error):
                await interaction.response.send_message(DB_FULL_MESSAGE, ephemeral=True)
                return
            raise

        verified_role = interaction.guild.get_role(verified_role_id) if verified_role_id else None
        if not verified_role:
            await interaction.response.send_message(
                "Prima scegli il ruolo verifica usando il parametro `ruolo` oppure `/verification_set_role`.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=titolo,
            description=testo,
            color=discord.Color.purple(),
        )
        embed.set_footer(text=f"Ruolo verifica: {verified_role.name}")

        await interaction.channel.send(embed=embed, view=VerifyView())
        await interaction.response.send_message(
            f"Pannello di verifica inviato con successo! Ruolo: {verified_role.mention}",
            ephemeral=True,
        )

    @app_commands.command(
        name="verification_set_role",
        description="Setta il ruolo assegnato dal pulsante verifica.",
    )
    @app_commands.describe(ruolo="Ruolo da assegnare agli utenti verificati")
    async def verification_set_role(
        self,
        interaction: discord.Interaction,
        ruolo: discord.Role,
    ) -> None:
        if not await require_staff(interaction):
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "Comando usabile solo dentro il server.",
                ephemeral=True,
            )
            return

        bot_member = interaction.guild.me
        if bot_member and (ruolo.managed or ruolo >= bot_member.top_role):
            await interaction.response.send_message(
                "Non posso assegnare quel ruolo: metti il ruolo del bot sopra al ruolo verifica.",
                ephemeral=True,
            )
            return

        try:
            set_verified_role_id(interaction.guild.id, ruolo.id)
        except sqlite3.OperationalError as error:
            if is_storage_error(error):
                await interaction.response.send_message(DB_FULL_MESSAGE, ephemeral=True)
                return
            raise

        await interaction.response.send_message(
            f"Ruolo verifica impostato su {ruolo.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    init_verification_db()
    bot.add_view(VerifyView())
    await bot.add_cog(Verification(bot))
