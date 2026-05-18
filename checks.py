import discord
from config import settings


def is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True

    staff_ids = set(settings.staff_role_ids)
    return any(role.id in staff_ids for role in member.roles)


async def require_staff(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Il comando è utilizzabile unicamente nel server.", ephemeral=True)
        return False

    if not is_staff(interaction.user):
        await interaction.response.send_message("Non hai i permessi necessari per eseguire tale comando.", ephemeral=True)
        return False

    return True
