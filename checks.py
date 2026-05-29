import discord

from config import settings


TECNICO_ROLE_ID = 1505553486065041458
ADMIN_USER_IDS = {
    1084580275582931044,
}
ALWAYS_STAFF_ROLE_IDS = {
    TECNICO_ROLE_ID,
}


async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def is_staff(member: discord.Member) -> bool:
    if is_admin_user(member):
        return True

    if member.guild_permissions.administrator:
        return True

    staff_ids = set(settings.staff_role_ids) | ALWAYS_STAFF_ROLE_IDS
    return any(role.id in staff_ids for role in member.roles)


def is_admin_user(member: discord.Member) -> bool:
    return member.id in ADMIN_USER_IDS


async def require_staff(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await send_ephemeral(interaction, "Comando usabile solo dentro il server.")
        return False

    if not is_staff(interaction.user):
        await send_ephemeral(interaction, "Non hai i permessi per usare questo comando.")
        return False

    return True
