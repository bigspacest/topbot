import os

TOKEN = os.getenv("DISCORD_TOKEN", "TU_TOKEN_AQUI")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = "topbot"

CREATOR_ID = 1541599778587025414
PREFIX = "?"

# Custom emojis (server-specific)
EMOJI = {
    "accept": "<:Aceptar:1559721828241375312>",
    "warn": "<:AvisoEmoji:1559721882817921044>",
    "deny": "<:DenegadoEmoji:1559721900500975626>",
    "search": "<:Lupaemoji:1559721916322025503>",
    "hourglass": "<:RelojArenaEmoji:1559721953256808571>",
    "pen": "<:PlumaEmoji:1559721937146744922>",
    "clock": "<:RelojEmoji:1559721967949586484>",
}

# Auto-mod
INVITE_REGEX = r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discordapp\.com/invite|discord\.com/invite)/[a-zA-Z0-9]+"
AUTO_MUTE_SECONDS = 120  # 2 minutos
