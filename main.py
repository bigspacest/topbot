import re
import asyncio
from datetime import timedelta

import discord
from discord.ext import commands

from config import TOKEN, PREFIX, CREATOR_ID, EMOJI, INVITE_REGEX, AUTO_MUTE_SECONDS
from database import ensure_indexes
from keep_alive import keep_alive
import commands as cmds_module  # noqa: F401


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    case_insensitive=True
)

INVITE_PATTERN = re.compile(INVITE_REGEX, re.IGNORECASE)


@bot.event
async def on_ready():
    await ensure_indexes()
    print(f"[TOPBOT] Online as {bot.user} | ID: {bot.user.id}")
    print(f"[TOPBOT] Guilds: {len(bot.guilds)}")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="?cmds")
    )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # ── PING RESPONSE (solo creador) ──────────────────────────────────────────
    if bot.user in message.mentions and message.author.id == CREATOR_ID:
        # Solo responder si el mensaje es esencialmente solo el mention
        content_clean = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if not content_clean:
            await message.reply("hello, como estas?", mention_author=False)
            return

    # ── AUTO-MOD: Discord invites ─────────────────────────────────────────────
    if INVITE_PATTERN.search(message.content):
        # Ignorar si el autor tiene permisos de moderación
        perms = message.author.guild_permissions
        if not (perms.administrator or perms.manage_messages or perms.manage_guild):
            try:
                await message.delete()
            except discord.Forbidden:
                pass

            # Mute 2 minutos
            try:
                await message.author.timeout(
                    timedelta(seconds=AUTO_MUTE_SECONDS),
                    reason="Auto-mod: Discord invite link"
                )
                warn_msg = await message.channel.send(
                    f"{EMOJI['deny']} {message.author.mention} — Links de invitaciones no permitidos. "
                    f"Muteado {AUTO_MUTE_SECONDS // 60} minutos {EMOJI['clock']}"
                )
                await asyncio.sleep(8)
                await warn_msg.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass
            return

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply(f"{EMOJI['deny']} No tienes permisos suficientes.", mention_author=False)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(f"{EMOJI['deny']} Faltan argumentos. Usa `?cmds` para ver la sintaxis.", mention_author=False)
    elif isinstance(error, commands.BadArgument):
        await ctx.reply(f"{EMOJI['deny']} Argumento inválido. Verifica el usuario/canal/ID.", mention_author=False)
    elif isinstance(error, commands.CommandNotFound):
        pass  # silencioso
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.reply(f"{EMOJI['deny']} Me faltan permisos para ejecutar este comando.", mention_author=False)
    else:
        print(f"[ERROR] {type(error).__name__}: {error}")


async def main():
    keep_alive()
    async with bot:
        await bot.add_cog(cmds_module.ModCommands(bot))
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
