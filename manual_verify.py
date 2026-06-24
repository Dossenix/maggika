import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

from checks import require_staff
from database import db

log = logging.getLogger("maggika.manual_verify")

STAFF_ROLE_ID = 1472188572789510330
VERIFY_ROLE_ID = 1518607627053961307


def init_manual_verification_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_verification_state (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role_ids TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )


def save_previous_roles(guild_id: int, user_id: int, role_ids: list[int]) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO manual_verification_state (guild_id, user_id, role_ids, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET role_ids = excluded.role_ids, created_at = excluded.created_at
            """,
            (guild_id, user_id, json.dumps(role_ids), discord.utils.utcnow().isoformat()),
        )


def get_saved_roles(guild_id: int, user_id: int) -> list[int] | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT role_ids
            FROM manual_verification_state
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ).fetchone()

    if row is None:
        return None

    try:
        return json.loads(row["role_ids"])
    except (TypeError, json.JSONDecodeError):
        return None


def clear_saved_roles(guild_id: int, user_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            DELETE FROM manual_verification_state
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )


def format_role_names(guild: discord.Guild, roles: list[discord.Role]) -> str:
    if not roles:
        return "Nessuno"

    return ", ".join(role.mention for role in roles if role is not None)


class ManualVerify(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="manual-verification",
        description="Assegna manualmente il ruolo di verifica a un utente.",
    )
    @app_commands.describe(
        member_id="ID dell'utente da mettere in verifica",
        reason="Motivazione della verifica manuale",
    )
    async def manual_verification(
        self,
        interaction: discord.Interaction,
        member_id: int,
        reason: str = "Nessuna motivazione specificata",
    ) -> None:
        log.info(
            "Manual verification invoked by %s (%s) in guild %s channel %s for member_id=%s reason=%r",
            interaction.user,
            getattr(interaction.user, "id", None),
            getattr(interaction.guild, "id", None),
            getattr(interaction.channel, "id", None),
            member_id,
            reason,
        )

        if not await require_staff(interaction):
            log.warning(
                "Manual verification denied: insufficient permissions for %s (%s)",
                interaction.user,
                getattr(interaction.user, "id", None),
            )
            return

        if interaction.guild is None or interaction.channel is None:
            log.warning(
                "Manual verification rejected: interaction missing guild or channel for %s (%s)",
                interaction.user,
                getattr(interaction.user, "id", None),
            )
            await interaction.response.send_message(
                "Comando usabile solo dentro il server.",
                ephemeral=True,
            )
            return

        try:
            member = await interaction.guild.fetch_member(member_id)
        except discord.NotFound:
            log.warning(
                "Manual verification failed: member_id=%s not found in guild %s",
                member_id,
                interaction.guild.id,
            )
            await interaction.response.send_message(
                "Utente non trovato.",
                ephemeral=True,
            )
            return
        except discord.Forbidden:
            log.warning(
                "Manual verification failed: cannot fetch members for guild %s",
                interaction.guild.id,
            )
            await interaction.response.send_message(
                "Non posso recuperare i membri del server.",
                ephemeral=True,
            )
            return

        verify_role = interaction.guild.get_role(VERIFY_ROLE_ID)
        if verify_role is None:
            log.warning(
                "Manual verification failed: verify role %s not found in guild %s",
                VERIFY_ROLE_ID,
                interaction.guild.id,
            )
            await interaction.response.send_message(
                "Ruolo di verifica non trovato.",
                ephemeral=True,
            )
            return

        if verify_role in member.roles:
            saved_roles = get_saved_roles(interaction.guild.id, member.id)
            if not saved_roles:
                log.info(
                    "Manual verification skipped: %s (%s) already has verify role without a saved snapshot",
                    member,
                    member.id,
                )
                await interaction.response.send_message(
                    "Il membro ha già il ruolo di verifica, ma non esiste uno stato salvato da ripristinare.",
                    ephemeral=True,
                )
                return

            try:
                await member.remove_roles(verify_role, reason="Ripristino ruoli precedenti")
            except discord.Forbidden:
                log.warning(
                    "Manual verification restore failed: bot cannot remove verify role from %s (%s)",
                    member,
                    member.id,
                )
                await interaction.response.send_message(
                    "Non posso rimuovere il ruolo di verifica.",
                    ephemeral=True,
                )
                return

            restored_roles: list[discord.Role] = []
            for role_id in saved_roles:
                role = interaction.guild.get_role(role_id)
                if role is None or role == verify_role or role.is_default():
                    continue
                restored_roles.append(role)

            for role in restored_roles:
                try:
                    await member.add_roles(role, reason="Ripristino ruoli precedenti")
                except discord.Forbidden:
                    log.warning(
                        "Manual verification restore failed: bot cannot restore role %s to %s (%s)",
                        role.id,
                        member,
                        member.id,
                    )

            clear_saved_roles(interaction.guild.id, member.id)

            timestamp = interaction.created_at.strftime("%d/%m/%Y %H:%M:%S")
            embed = discord.Embed(
                title="Ruoli precedenti ripristinati con successo",
                color=discord.Color.red(),
            )
            embed.set_author(
                name=f"{interaction.user.name} ({interaction.user.display_name})",
                icon_url=interaction.user.display_avatar.url,
            )
            embed.description = (
                f"{member.mention} ({member.id}) è stato riportato allo stato precedente per il comando eseguito."
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Motivazione", value=f"`{reason}`", inline=False)
            embed.add_field(name="Ruoli rimossi", value=verify_role.mention, inline=False)
            embed.add_field(name="Ruoli aggiunti", value=format_role_names(interaction.guild, restored_roles) or "Nessuno", inline=False)
            embed.set_footer(
                text=f"Kings di CastaMaggic - {timestamp}",
                icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
            )

            await interaction.channel.send(embed=embed)
            await interaction.response.send_message(
                f"Ruoli precedenti ripristinati per {member.mention}.",
                ephemeral=True,
            )
            log.info(
                "Manual verification restored for %s (%s) by %s (%s) in channel %s with reason=%r",
                member,
                member.id,
                interaction.user,
                interaction.user.id,
                interaction.channel.id,
                reason,
            )
            return

        if any(role.id == STAFF_ROLE_ID for role in member.roles):
            log.warning(
                "Manual verification blocked for staff member %s (%s) requested by %s (%s)",
                member,
                member.id,
                interaction.user,
                interaction.user.id,
            )
            await interaction.response.send_message(
                "Il membro non può essere messo in verifica per i ruoli staff",
                ephemeral=True,
            )
            return

        previous_role_ids = [
            role.id
            for role in member.roles
            if not role.is_default() and role.id != verify_role.id
        ]
        removed_roles: list[discord.Role] = []

        try:
            for role in member.roles:
                if role.is_default() or role.id == verify_role.id:
                    continue
                try:
                    await member.remove_roles(role, reason="Verifica manuale")
                    removed_roles.append(role)
                except discord.Forbidden:
                    log.warning(
                        "Manual verification failed: bot cannot remove role %s from %s (%s)",
                        role.id,
                        member,
                        member.id,
                    )

            await member.add_roles(verify_role, reason="Verifica manuale")
        except discord.Forbidden:
            log.warning(
                "Manual verification failed: bot cannot add verify role to %s (%s)",
                member,
                member.id,
            )
            await interaction.response.send_message(
                "Non posso assegnare il ruolo di verifica.",
                ephemeral=True,
            )
            return

        save_previous_roles(interaction.guild.id, member.id, previous_role_ids)

        timestamp = interaction.created_at.strftime("%d/%m/%Y %H:%M:%S")
        embed = discord.Embed(
            title="Ruolo di verifica manuale aggiunto con successo",
            color=discord.Color.red(),
        )
        embed.set_author(
            name=f"{interaction.user.name} ({interaction.user.display_name})",
            icon_url=interaction.user.display_avatar.url,
        )
        embed.description = (
            f"{member.mention} ({member.id}) è stato messo in verifica per il comando eseguito."
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Motivazione", value=f"`{reason}`", inline=False)
        embed.add_field(name="Ruoli rimossi", value=format_role_names(interaction.guild, removed_roles) or "Nessuno", inline=False)
        embed.add_field(name="Ruoli aggiunti", value=verify_role.mention, inline=False)
        embed.set_footer(
            text=f"Kings di CastaMaggic - {timestamp}",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
        )

        await interaction.channel.send(embed=embed)
        await interaction.response.send_message(
            f"Ruolo di verifica assegnato a {member.mention}.",
            ephemeral=True,
        )
        log.info(
            "Manual verification succeeded for %s (%s) by %s (%s) in channel %s with reason=%r",
            member,
            member.id,
            interaction.user,
            interaction.user.id,
            interaction.channel.id,
            reason,
        )


async def setup(bot: commands.Bot) -> None:
    init_manual_verification_db()
    await bot.add_cog(ManualVerify(bot))
