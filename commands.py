import re
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord.ext import commands

from config import EMOJI, CREATOR_ID
from database import (
    add_warn, get_warns, delete_warn,
    add_note, get_notes, delete_note,
    set_lock, get_lock, clear_lock
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


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def has_mod_perms(ctx: commands.Context) -> bool:
    perms = ctx.author.guild_permissions
    return perms.administrator or perms.manage_guild or perms.ban_members or perms.moderate_members


async def safe_reply(ctx: commands.Context, content: str, embed: discord.Embed = None):
    try:
        if embed:
            await ctx.reply(content, embed=embed, mention_author=False)
        else:
            await ctx.reply(content, mention_author=False)
    except discord.HTTPException:
        pass


# ─── COMMANDS ────────────────────────────────────────────────────────────────

class ModCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── CMDS ──────────────────────────────────────────────────────────────────

    @commands.command(name="cmds")
    async def cmds(self, ctx: commands.Context):
        embed = discord.Embed(
            title=f"{EMOJI['search']} Lista de Comandos — TopBot",
            color=0x2B2D31
        )
        embed.add_field(
            name="Moderación",
            value=(
                "`?lock <canal> <tiempo>` — Bloquea un canal temporalmente\n"
                "`?unlock` — Desbloquea el canal actual\n"
                "`?ban <usuario> <motivo>` — Banea a un usuario\n"
                "`?unban <user-id> <motivo>` — Desbanea por ID\n"
                "`?kick <usuario> <motivo>` — Expulsa a un usuario\n"
                "`?mute <usuario> <tiempo>` — Silencia (timeout)\n"
                "`?unmute <usuario>` — Quita el silencio"
            ),
            inline=False
        )
        embed.add_field(
            name="Warns & Notes",
            value=(
                "`?warn <usuario> <motivo>` — Añade un warn\n"
                "`?warnings <usuario>` — Lista warns de un usuario\n"
                "`?delwarn <usuario> <warn-id>` — Elimina un warn\n"
                "`?addnote <usuario> <nota>` — Añade una nota\n"
                "`?removenote <usuario> <note-id>` — Elimina una nota"
            ),
            inline=False
        )
        embed.set_footer(text="Prefijo: ? | Solo staff con permisos")
        await safe_reply(ctx, "", embed)

    # ── LOCK / UNLOCK ─────────────────────────────────────────────────────────

    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context, channel: discord.TextChannel = None, time_str: str = None):
        channel = channel or ctx.channel

        if not ctx.guild.me.guild_permissions.manage_channels:
            return await safe_reply(ctx, f"{EMOJI['deny']} No tengo permiso `Manage Channels`.")

        unlock_at = None
        if time_str:
            delta = parse_time(time_str)
            if not delta:
                return await safe_reply(ctx, f"{EMOJI['deny']} Formato de tiempo inválido. Usa: `10m`, `1h`, `2d`.")
            unlock_at = datetime.utcnow() + delta

        # Guardar overwrites actuales de @everyone
        everyone = ctx.guild.default_role
        current = channel.overwrites_for(everyone)
        original = {
            "send_messages": current.send_messages,
            "add_reactions": current.add_reactions,
            "create_public_threads": current.create_public_threads,
            "send_messages_in_threads": current.send_messages_in_threads,
        }

        # Aplicar lock
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = False
        overwrite.add_reactions = False
        overwrite.create_public_threads = False
        overwrite.send_messages_in_threads = False
        await channel.set_permissions(everyone, overwrite=overwrite, reason=f"Lock by {ctx.author}")

        await set_lock(ctx.guild.id, channel.id, unlock_at, original)

        msg = f"{EMOJI['accept']} Canal {channel.mention} bloqueado."
        if unlock_at:
            msg += f" Se desbloqueará en `{time_str}` {EMOJI['hourglass']}"
            # Schedule unlock
            async def auto_unlock():
                await asyncio.sleep(delta.total_seconds())
                lock_data = await get_lock(ctx.guild.id, channel.id)
                if lock_data and lock_data.get("locked"):
                    await self._restore_channel(channel, lock_data.get("original_overwrites", {}))
                    await clear_lock(ctx.guild.id, channel.id)
            self.bot.loop.create_task(auto_unlock())

        await safe_reply(ctx, msg)

    @commands.command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context, channel: discord.TextChannel = None):
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
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sin motivo"):
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
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, user_id: int, *, reason: str = "Sin motivo"):
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
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sin motivo"):
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
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx: commands.Context, member: discord.Member, time_str: str, *, reason: str = "Sin motivo"):
        delta = parse_time(time_str)
        if not delta:
            return await safe_reply(ctx, f"{EMOJI['deny']} Formato de tiempo inválido. Usa: `10m`, `1h`, `2d`.")
        if delta.total_seconds() > 2419200:  # 28 días max Discord
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
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx: commands.Context, member: discord.Member):
        try:
            await member.timeout(None, reason=f"Unmute por {ctx.author}")
            await safe_reply(ctx, f"{EMOJI['accept']} **{member}** ya no está silenciado.")
        except discord.Forbidden:
            await safe_reply(ctx, f"{EMOJI['deny']} No puedo quitar el silencio a este usuario.")

    # ── WARN SYSTEM ───────────────────────────────────────────────────────────

    @commands.command(name="warn")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Sin motivo"):
        warn_id = await add_warn(ctx.guild.id, member.id, ctx.author.id, reason)
        total = len(await get_warns(ctx.guild.id, member.id))

        embed = discord.Embed(
            description=f"{EMOJI['warn']} **{member}** ha recibido un warn.\n"
                        f"**ID:** `{warn_id}` | **Total:** `{total}`\n"
                        f"**Motivo:** {reason}",
            color=0xF1C40F
        )
        await safe_reply(ctx, "", embed)

        try:
            await member.send(
                f"{EMOJI['warn']} Has recibido un warn en **{ctx.guild.name}**.\n"
                f"Motivo: `{reason}` | ID: `{warn_id}`"
            )
        except discord.Forbidden:
            pass

    @commands.command(name="warnings")
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member):
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
    @commands.has_permissions(moderate_members=True)
    async def delwarn(self, ctx: commands.Context, member: discord.Member, warn_id: int):
        deleted = await delete_warn(ctx.guild.id, member.id, warn_id)
        if deleted:
            await safe_reply(ctx, f"{EMOJI['accept']} Warn `{warn_id}` de **{member}** eliminado.")
        else:
            await safe_reply(ctx, f"{EMOJI['deny']} No se encontró el warn `{warn_id}` para **{member}**.")

    # ── NOTES ─────────────────────────────────────────────────────────────────

    @commands.command(name="addnote")
    @commands.has_permissions(moderate_members=True)
    async def addnote(self, ctx: commands.Context, member: discord.Member, *, content: str):
        note_id = await add_note(ctx.guild.id, member.id, ctx.author.id, content)
        await safe_reply(
            ctx,
            f"{EMOJI['pen']} Nota añadida a **{member}**.\n**ID:** `{note_id}`\n**Contenido:** {content}"
        )

    @commands.command(name="removenote")
    @commands.has_permissions(moderate_members=True)
    async def removenote(self, ctx: commands.Context, member: discord.Member, note_id: int):
        deleted = await delete_note(ctx.guild.id, member.id, note_id)
        if deleted:
            await safe_reply(ctx, f"{EMOJI['accept']} Nota `{note_id}` de **{member}** eliminada.")
        else:
            await safe_reply(ctx, f"{EMOJI['deny']} No se encontró la nota `{note_id}` para **{member}**.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ModCommands(bot))
