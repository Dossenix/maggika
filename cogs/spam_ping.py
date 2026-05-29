from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from checks import require_staff


class SpamPing(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="spam_ping", description="Ping staff controllato verso un utente o ruolo.")
    @app_commands.describe(
        membro="Utente da pingare",
        ruolo="Ruolo da pingare",
        volte="Numero ping, massimo 5",
        messaggio="Messaggio opzionale",
    )
    @app_commands.checks.cooldown(1, 90)
    async def spam_ping(
        self,
        interaction: discord.Interaction,
        membro: discord.Member | None = None,
        ruolo: discord.Role | None = None,
        volte: app_commands.Range[int, 1, 5] = 3,
        messaggio: str = "ti stanno cercando",
    ) -> None:
        if not await require_staff(interaction):
            return

        if (membro is None and ruolo is None) or (membro is not None and ruolo is not None):
            await interaction.response.send_message(
                "Devi scegliere solo un target: `membro` oppure `ruolo`.",
                ephemeral=True,
            )
            return

        if interaction.channel is None:
            await interaction.response.send_message("Canale non valido.", ephemeral=True)
            return

        if membro is not None:
            if membro.bot:
                await interaction.response.send_message("Non pingo altri bot.", ephemeral=True)
                return

            target_mention = membro.mention
            target_label = membro.mention
            allowed_mentions = discord.AllowedMentions(
                users=[membro],
                roles=False,
                everyone=False,
            )
        else:
            assert ruolo is not None
            if ruolo.is_default():
                await interaction.response.send_message("Non puoi pingare @everyone.", ephemeral=True)
                return

            if ruolo.managed:
                await interaction.response.send_message(
                    "Non puoi pingare un ruolo gestito automaticamente.",
                    ephemeral=True,
                )
                return

            target_mention = ruolo.mention
            target_label = ruolo.mention
            allowed_mentions = discord.AllowedMentions(
                users=False,
                roles=[ruolo],
                everyone=False,
            )

        await interaction.response.send_message(
            f"Spam ping avviato verso {target_label}: `{volte}` ping.",
            ephemeral=True,
        )

        for _ in range(volte):
            await interaction.channel.send(
                f"{target_mention} {messaggio}",
                allowed_mentions=allowed_mentions,
            )
            await asyncio.sleep(1)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SpamPing(bot))
