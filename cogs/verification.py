import discord
from discord import app_commands
from discord.ext import commands

from checks import require_staff
from config import settings

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
        button: discord.ui.button,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Puoi verificarti solo dentro al server.",
                ephemeral=True,
            )
            return
        
        if not settings.verified_role_id:
            await interaction.response.send_message(
                "Ruolo della verifica non configurato o non esistente.",
                ephemeral=True,
            )
            return
        
        role = interaction.guild.get_role(settings.verified_role_id)
        if not role:
            await interaction.response.send_message(
                "Ruolo della verifica non trovato.",
                ephemeral=True,
            )
            return
        
        if role in interaction.user.roles:
            await interaction.response.send_message(
                "Sei già verificato.",
                ephemeral=True,
            )
            return
        
        try:
            await interaction.user.add_roles(role, reason="Verifica tramite pulsante")
        except discord.Forbidden:
            await interaction.response.send_message(
                "Non posso assegnare questo ruolo. Contatta l'amministrazione per sistemare la gerarchizzazione dei ruoli.",
                ephemeral=True,
            )
            return
        
        await interaction.response.send_message(
            f"Verificato con successo! Ti è stato assegnato il ruolo {role.mention}.",
            ephemeral=True,
        )

class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
    
    @app_commands.command(
        name="setup_verification",
        description="Invia il pannello di verifica nel canale attuale (richiede permessi di gestione messaggi).",
    )
    @app_commands.describe(
        titolo="Titolo del pannello",
        testo="Testo del pannello",
    )
    async def setup_verify(
        self,
        interaction: discord.Interaction,
        titolo: str = "Verifica Membri del Server",
        testo: str = "Clicca sul pulsante qui sotto per verificarti.",
    ) -> None:
        if not await require_staff(interaction):
            return
        
        if interaction.channel is None:
            await interaction.response.send_message("Canale non Valido", ephemeral=True)
            return
        
        embed = discord.Embed(
            title=titolo,
            description=testo,
            color=discord.Color.purple(),
        )

        await interaction.channel.send(embed=embed, view=VerifyView())
        await interaction.response.send_message("Pannello di verifica inviato con successo!", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    bot.add_view(VerifyView())
    await bot.add_cog(Verification(bot))