import discord

from config import settings


async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True

    staff_ids = set(settings.staff_role_ids)
    return any(role.id in staff_ids for role in member.roles)


async def require_staff(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await send_ephemeral(interaction, "Comando usabile solo dentro il server.")
        return False

    if not is_staff(interaction.user):
        await send_ephemeral(interaction, "Non hai i permessi per usare questo comando.")
        return False

    return True
