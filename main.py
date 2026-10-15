import re
import asyncio
from datetime import timedelta

import discord
from discord.ext import commands

from config import TOKEN, PREFIX, CREATOR_ID, EMOJI, INVITE_REGEX, AUTO_MUTE_SECONDS
from database import ensure_indexes
from keep_alive import keep_alive
import commands as cmds_module  # noqa: F401
from commands import is_mod, NO_PERMS_MSG


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
    try:
        synced = await bot.tree.sync()
        print(f"[TOPBOT] Slash commands synced: {len(synced)}")
    except Exception as e:
        print(f"[TOPBOT] Slash sync error: {e}")
    print(f"[TOPBOT] Online as {bot.user} | ID: {bot.user.id}")
    print(f"[TOPBOT] Guilds: {len(bot.guilds)}")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="dev: Imchahinne")
    )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # ── PING RESPONSE (solo creador) ──────────────────────────────────────────
    if bot.user in message.mentions and message.author.id == CREATOR_ID:
        content_clean = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if not content_clean:
            await message.reply("hello, como estas?", mention_author=False)
            return

    # ── AUTO-MOD: Discord invites ─────────────────────────────────────────────
    if INVITE_PATTERN.search(message.content):
        perms = message.author.guild_permissions
        if not (perms.administrator or perms.manage_messages or perms.manage_guild):
            try:
                await message.delete()
            except discord.Forbidden:
                pass

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
    # Si no es staff → siempre denegar por permisos (incluso en args incompletos)
    if isinstance(error, (
        commands.MissingRequiredArgument,
        commands.BadArgument,
        commands.MissingPermissions,
        commands.CheckFailure,
    )):
        if not await is_mod(ctx.author):
            return await ctx.reply(NO_PERMS_MSG, mention_author=False)

    if isinstance(error, commands.MissingPermissions):
        await ctx.reply(NO_PERMS_MSG, mention_author=False)
    elif isinstance(error, commands.MissingRequiredArgument):
        param = error.param.name if error.param else "requerido"
        await ctx.reply(
            f"{EMOJI['deny']} Falta el argumento `{param}`.\n"
            f"{EMOJI['search']} Usa `?cmds` para ver la sintaxis correcta.",
            mention_author=False
        )
    elif isinstance(error, commands.BadArgument):
        await ctx.reply(
            f"{EMOJI['deny']} Argumento inválido.\n"
            f"{EMOJI['search']} Verifica el usuario, canal o ID e inténtalo de nuevo.",
            mention_author=False
        )
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.BotMissingPermissions):
        missing = ", ".join(error.missing_permissions) if hasattr(error, "missing_permissions") else "desconocido"
        await ctx.reply(
            f"{EMOJI['deny']} Me faltan permisos para ejecutar este comando (`{missing}`).",
            mention_author=False
        )
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(
            f"{EMOJI['hourglass']} Espera `{error.retry_after:.1f}s` antes de usar este comando de nuevo.",
            mention_author=False
        )
    else:
        print(f"[ERROR] {type(error).__name__}: {error}")


async def main():
    keep_alive()
    async with bot:
        await bot.add_cog(cmds_module.ModCommands(bot))
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
