import re
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import EMOJI
from database import (
    add_warn, get_warns, delete_warn,
    add_note, delete_note,
    set_lock, get_lock, clear_lock,
    get_guild_config, set_admin_roles, set_mod_roles
)


# ─── TIME PARSER ─────────────────────────────────────────────────────────────

TIME_REGEX = re.compile(r"(\d+)([smhd])", re.IGNORECASE)

def parse_time(time_str: str) -> Optional[timedelta]:
    match = TIME_REGEX.fullmatch(time_str.strip())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2).lower()
    mapping = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
    return timedelta(**{mapping[unit]: value})


# ─── PERMISSION HELPERS ──────────────────────────────────────────────────────

async def is_admin(member: discord.Member) -> bool:
    if member.guild.owner_id == member.id or member.guild_permissions.administrator:
        return True
    cfg = await get_guild_config(member.guild.id)
    admin_roles = set(cfg.get("admin_roles", []))
    return any(r.id in admin_roles for r in member.roles)


async def is_mod(member: discord.Member) -> bool:
    if await is_admin(member):
        return True
    cfg = await get_guild_config(member.guild.id)
    mod_roles = set(cfg.get("mod_roles", []))
    return any(r.id in mod_roles for r in member.roles)


async def require_mod(ctx: commands.Context) -> bool:
    if await is_mod(ctx.author):
        return True
    await safe_reply(ctx, f"{EMOJI['deny']} No tienes el rol de moderador/administrador configurado.")
    return False


async def safe_reply(ctx: commands.Context, content: str, embed: discord.Embed = None):
    try:
        if embed:
            await ctx.reply(content if content else None, embed=embed, mention_author=False)
        else:
            await ctx.reply(content, mention_author=False)
    except discord.HTTPException:
        pass


# ─── SETUP VIEW ──────────────────────────────────────────────────────────────

class SetupView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Selecciona rol(es) de Administrador",
        min_values=0,
        max_values=10,
        custom_id="setup_admin_roles"
    )
    async def admin_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        if not await is_admin(interaction.user):
            return await interaction.response.send_message(
                f"{EMOJI['deny']} Solo administradores pueden modificar esto.", ephemeral=True
            )
        role_ids = [r.id for r in select.values]
        await set_admin_roles(self.guild_id, role_ids)
        roles_txt = ", ".join(r.mention for r in select.values) if select.values else "*Ninguno*"
        await interaction.response.send_message(
            f"{EMOJI['accept']} Roles de **Administrador** actualizados:\n{roles_txt}",
            ephemeral=True
        )

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Selecciona rol(es) de Moderador",
        min_values=0,
        max_values=10,
        custom_id="setup_mod_roles"
    )
    async def mod_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        if not await is_admin(interaction.user):
            return await interaction.response.send_message(
                f"{EMOJI['deny']} Solo administradores pueden modificar esto.", ephemeral=True
            )
        role_ids = [r.id for r in select.values]
        await set_mod_roles(self.guild_id, role_ids)
        roles_txt = ", ".join(r.mention for r in select.values) if select.values else "*Ninguno*"
        await interaction.response.send_message(
            f"{EMOJI['accept']} Roles de **Moderador** actualizados:\n{roles_txt}",
            ephemeral=True
        )


# ─── COG ─────────────────────────────────────────────────────────────────────

class ModCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /setup ────────────────────────────────────────────────────────────────

    @app_commands.command(name="setup", description="Panel de configuración de roles de staff")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction):
        cfg = await get_guild_config(interaction.guild.id)
        admin_mentions = [f"<@&{rid}>" for rid in cfg.get("admin_roles", [])]
        mod_mentions = [f"<@&{rid}>" for rid in cfg.get("mod_roles", [])]

        embed = discord.Embed(
            title=f"{EMOJI['pen']} Panel de Configuración — TopBot",
            description=(
                "Configura los roles que tendrán acceso a los comandos de moderación.\n\n"
                f"**Admin roles actuales:** {', '.join(admin_mentions) if admin_mentions else '*Sin configurar*'}\n"
                f"**Mod roles actuales:** {', '.join(mod_mentions) if mod_mentions else '*Sin configurar*'}\n\n"
                "Usa los selectores de abajo para asignar uno o varios roles."
            ),
            color=0x5865F2
        )
        embed.set_footer(text="Los cambios se aplican al instante • Solo administradores")
        view = SetupView(interaction.guild.id)
        await interaction.response.send_message(embed=embed, view=view)

    @setup.error
    async def setup_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                f"{EMOJI['deny']} Necesitas permiso de Administrador de Discord.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{EMOJI['deny']} Error: {error}", ephemeral=True
            )

    # ── ?cmds ─────────────────────────────────────────────────────────────────

    @commands.command(name="cmds")
    async def cmds(self, ctx: commands.Context):
        if not await is_mod(ctx.author):
            return await safe_reply(
                ctx,
                f"{EMOJI['deny']} Este comando solo está disponible para staff configurado."
            )

        embed = discord.Embed(
            title=f"{EMOJI['search']}  Comandos de Moderación",
            description="Lista de comandos disponibles para el staff.",
            color=0x2B2D31
        )

        embed.add_field(
            name=f"{EMOJI['clock']}  Canales",
            value=(
                "```\n"
                "?lock [canal] [tiempo]   Bloquear canal\n"
                "?unlock [canal]          Desbloquear canal\n"
                "```"
            ),
            inline=False
        )
        embed.add_field(
            name=f"{EMOJI['deny']}  Sanciones",
            value=(
                "```\n"
                "?ban <usuario> [motivo]      Banear\n"
                "?unban <user-id> [motivo]    Desbanear\n"
                "?kick <usuario> [motivo]     Expulsar\n"
                "?mute <usuario> <tiempo>     Timeout\n"
                "?unmute <usuario>            Quitar timeout\n"
                "```"
            ),
            inline=False
        )
        embed.add_field(
            name=f"{EMOJI['warn']}  Warns",
            value=(
                "```\n"
                "?warn <usuario> [motivo]     Añadir warn\n"
                "?warnings <usuario>          Ver warns\n"
                "?delwarn <usuario> <id>      Eliminar warn\n"
                "```"
            ),
            inline=False
        )
        embed.add_field(
            name=f"{EMOJI['pen']}  Notas",
            value=(
                "```\n"
                "?addnote <usuario> <nota>    Añadir nota\n"
                "?removenote <usuario> <id>   Eliminar nota\n"
                "```"
            ),
            inline=False
        )
        embed.add_field(
            name=f"{EMOJI['search']}  Utilidad",
            value="```\n?cmds    Ver esta lista\n/setup   Configurar roles de staff\n```",
            inline=False
        )
        embed.set_footer(text="Tiempo: 10s · 5m · 1h · 2d  |  Prefijo: ?")
        await safe_reply(ctx, "", embed)

    # ── LOCK / UNLOCK ─────────────────────────────────────────────────────────

    @commands.command(name="lock")
    async def lock(self, ctx: commands.Context, channel: discord.TextChannel = None, time_str: str = None):
        if not await require_mod(ctx):
            return
        channel = channel or ctx.channel

        if not ctx.guild.me.guild_permissions.manage_channels:
            return await safe_reply(ctx, f"{EMOJI['deny']} No tengo permiso `Manage Channels`.")

        unlock_at = None
        delta = None
        if time_str:
            delta = parse_time(time_str)
            if not delta:
                return await safe_reply(ctx, f"{EMOJI['deny']} Formato de tiempo inválido. Usa: `10m`, `1h`, `2d`.")
            unlock_at = datetime.utcnow() + delta

        everyone = ctx.guild.default_role
        current = channel.overwrites_for(everyone)
        original = {
            "send_messages": current.send_messages,
            "add_reactions": current.add_reactions,
            "create_public_threads": current.create_public_threads,
            "send_messages_in_threads": current.send_messages_in_threads,
        }

        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = False
        overwrite.add_reactions = False
        overwrite.create_public_threads = False
        overwrite.send_messages_in_threads = False
        await channel.set_permissions(everyone, overwrite=overwrite, reason=f"Lock by {ctx.author}")

        await set_lock(ctx.guild.id, channel.id, unlock_at, original)

        msg = f"{EMOJI['accept']} Canal {channel.mention} bloqueado."
        if unlock_at and delta:
            msg += f" Se desbloqueará en `{time_str}` {EMOJI['hourglass']}"

            async def auto_unlock():
                await asyncio.sleep(delta.total_seconds())
                lock_data = await get_lock(ctx.guild.id, channel.id)
                if lock_data and lock_data.get("locked"):
                    await self._restore_channel(channel, lock_data.get("original_overwrites", {}))
                    await clear_lock(ctx.guild.id, channel.id)
            self.bot.loop.create_task(auto_unlock())

        await safe_reply(ctx, msg)

    @commands.command(name="unlock")
    async def unlock(self, ctx: commands.Context, channel: discord.TextChannel = None):
        if not await require_mod(ctx):
            return
        channel = channel or ctx.channel
        lock_data = await get_lock(ctx.guild.id, channel.id)

        if not lock_data or not lock_data.get("locked"):
            return await safe_reply(ctx, f"{EMOJI['deny']} Este canal no está bloqueado.")

        await self._restore_channel(channel, lock_data.get("original_overwrites", {}))
        await clear_lock(ctx.guild.id, channel.id)
        await safe_reply(ctx, f"{EMOJI['accept']} Canal {channel.mention} desbloqueado.")

    async def _restore_channel(self, channel: discord.TextChannel, original: dict):
        everyone = channel.guild.default_role
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = original.get("send_messages")
        overwrite.add_reactions = original.get("add_reactions")
        overwrite.create_public_threads = original.get("create_public_threads")
        overwrite.send_messages_in_threads = original.get("send_messages_in_threads")
        await channel.set_permissions(everyone, overwrite=overwrite, reason="Unlock")

    # ── BAN / UNBAN ───────────────────────────────────────────────────────────

    @commands.command(name="ban")
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sin motivo"):
        if not await require_mod(ctx):
            return
        if member.id == ctx.author.id:
            return await safe_reply(ctx, f"{EMOJI['deny']} No puedes banearte a ti mismo.")
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await safe_reply(ctx, f"{EMOJI['deny']} No puedes banear a alguien con rol igual o superior.")
        if not ctx.guild.me.guild_permissions.ban_members:
            return await safe_reply(ctx, f"{EMOJI['deny']} No tengo permiso `Ban Members`.")

        try:
            await member.ban(reason=f"{reason} | Por: {ctx.author}")
            await safe_reply(ctx, f"{EMOJI['accept']} **{member}** baneado.\nMotivo: `{reason}`")
        except discord.Forbidden:
            await safe_reply(ctx, f"{EMOJI['deny']} No puedo banear a este usuario (jerarquía).")

    @commands.command(name="unban")
    async def unban(self, ctx: commands.Context, user_id: int, *, reason: str = "Sin motivo"):
        if not await require_mod(ctx):
            return
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=f"{reason} | Por: {ctx.author}")
            await safe_reply(ctx, f"{EMOJI['accept']} **{user}** (`{user_id}`) desbaneado.\nMotivo: `{reason}`")
        except discord.NotFound:
            await safe_reply(ctx, f"{EMOJI['deny']} Usuario no encontrado o no está baneado.")
        except discord.Forbidden:
            await safe_reply(ctx, f"{EMOJI['deny']} No tengo permiso para desbanear.")

    # ── KICK ──────────────────────────────────────────────────────────────────

    @commands.command(name="kick")
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sin motivo"):
        if not await require_mod(ctx):
            return
        if member.id == ctx.author.id:
            return await safe_reply(ctx, f"{EMOJI['deny']} No puedes expulsarte a ti mismo.")
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await safe_reply(ctx, f"{EMOJI['deny']} No puedes expulsar a alguien con rol igual o superior.")

        try:
            await member.kick(reason=f"{reason} | Por: {ctx.author}")
            await safe_reply(ctx, f"{EMOJI['accept']} **{member}** expulsado.\nMotivo: `{reason}`")
        except discord.Forbidden:
            await safe_reply(ctx, f"{EMOJI['deny']} No puedo expulsar a este usuario (jerarquía).")

    # ── MUTE / UNMUTE ─────────────────────────────────────────────────────────

    @commands.command(name="mute")
    async def mute(self, ctx: commands.Context, member: discord.Member, time_str: str, *, reason: str = "Sin motivo"):
        if not await require_mod(ctx):
            return
        delta = parse_time(time_str)
        if not delta:
            return await safe_reply(ctx, f"{EMOJI['deny']} Formato de tiempo inválido. Usa: `10m`, `1h`, `2d`.")
        if delta.total_seconds() > 2419200:
            return await safe_reply(ctx, f"{EMOJI['deny']} El máximo de timeout es 28 días.")

        if member.id == ctx.author.id:
            return await safe_reply(ctx, f"{EMOJI['deny']} No puedes silenciarte a ti mismo.")
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await safe_reply(ctx, f"{EMOJI['deny']} No puedes silenciar a alguien con rol igual o superior.")

        try:
            await member.timeout(delta, reason=f"{reason} | Por: {ctx.author}")
            await safe_reply(
                ctx,
                f"{EMOJI['accept']} **{member}** silenciado por `{time_str}` {EMOJI['clock']}\nMotivo: `{reason}`"
            )
        except discord.Forbidden:
            await safe_reply(ctx, f"{EMOJI['deny']} No puedo silenciar a este usuario (jerarquía o permisos).")

    @commands.command(name="unmute")
    async def unmute(self, ctx: commands.Context, member: discord.Member):
        if not await require_mod(ctx):
            return
        try:
            await member.timeout(None, reason=f"Unmute por {ctx.author}")
            await safe_reply(ctx, f"{EMOJI['accept']} **{member}** ya no está silenciado.")
        except discord.Forbidden:
            await safe_reply(ctx, f"{EMOJI['deny']} No puedo quitar el silencio a este usuario.")

    # ── WARN SYSTEM ───────────────────────────────────────────────────────────

    @commands.command(name="warn")
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sin motivo"):
        if not await require_mod(ctx):
            return
        warn_id = await add_warn(ctx.guild.id, member.id, ctx.author.id, reason)
        total = len(await get_warns(ctx.guild.id, member.id))

        embed = discord.Embed(
            description=(
                f"{EMOJI['warn']} **{member}** ha recibido un warn.\n"
                f"**ID:** `{warn_id}` · **Total:** `{total}`\n"
                f"**Motivo:** {reason}"
            ),
            color=0xF1C40F
        )
        await safe_reply(ctx, "", embed)

        try:
            await member.send(
                f"{EMOJI['warn']} Has recibido un warn en **{ctx.guild.name}**.\n"
                f"Motivo: `{reason}` · ID: `{warn_id}`"
            )
        except discord.Forbidden:
            pass

    @commands.command(name="warnings")
    async def warnings(self, ctx: commands.Context, member: discord.Member):
        if not await require_mod(ctx):
            return
        warns_list = await get_warns(ctx.guild.id, member.id)
        if not warns_list:
            return await safe_reply(ctx, f"{EMOJI['search']} **{member}** no tiene warns.")

        embed = discord.Embed(
            title=f"{EMOJI['search']} Warns de {member}",
            color=0xF1C40F
        )
        for w in sorted(warns_list, key=lambda x: x["id"]):
            ts = w["timestamp"].strftime("%d/%m/%Y %H:%M") if isinstance(w["timestamp"], datetime) else "—"
            embed.add_field(
                name=f"ID `{w['id']}` — {ts}",
                value=f"Motivo: {w['reason']}\nMod: <@{w['moderator_id']}>",
                inline=False
            )
        await safe_reply(ctx, "", embed)

    @commands.command(name="delwarn")
    async def delwarn(self, ctx: commands.Context, member: discord.Member, warn_id: int):
        if not await require_mod(ctx):
            return
        deleted = await delete_warn(ctx.guild.id, member.id, warn_id)
        if deleted:
            await safe_reply(ctx, f"{EMOJI['accept']} Warn `{warn_id}` de **{member}** eliminado.")
        else:
            await safe_reply(ctx, f"{EMOJI['deny']} No se encontró el warn `{warn_id}` para **{member}**.")

    # ── NOTES ─────────────────────────────────────────────────────────────────

    @commands.command(name="addnote")
    async def addnote(self, ctx: commands.Context, member: discord.Member, *, content: str):
        if not await require_mod(ctx):
            return
        note_id = await add_note(ctx.guild.id, member.id, ctx.author.id, content)
        await safe_reply(
            ctx,
            f"{EMOJI['pen']} Nota añadida a **{member}**.\n**ID:** `{note_id}`\n**Contenido:** {content}"
        )

    @commands.command(name="removenote")
    async def removenote(self, ctx: commands.Context, member: discord.Member, note_id: int):
        if not await require_mod(ctx):
            return
        deleted = await delete_note(ctx.guild.id, member.id, note_id)
        if deleted:
            await safe_reply(ctx, f"{EMOJI['accept']} Nota `{note_id}` de **{member}** eliminada.")
        else:
            await safe_reply(ctx, f"{EMOJI['deny']} No se encontró la nota `{note_id}` para **{member}**.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ModCommands(bot))
