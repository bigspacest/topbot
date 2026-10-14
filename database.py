from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from config import MONGO_URI, DB_NAME

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

warns = db.warns
notes = db.notes
locks = db.locks  # channel lock state


async def ensure_indexes():
    await warns.create_index([("guild_id", 1), ("user_id", 1)])
    await notes.create_index([("guild_id", 1), ("user_id", 1)])
    await locks.create_index([("guild_id", 1), ("channel_id", 1)], unique=True)


# ─── WARNS ───────────────────────────────────────────────────────────────────

async def add_warn(guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
    doc = await warns.find_one({"guild_id": guild_id, "user_id": user_id})
    if not doc:
        doc = {
            "guild_id": guild_id,
            "user_id": user_id,
            "warns": [],
            "next_id": 1
        }
        await warns.insert_one(doc)

    warn_id = doc.get("next_id", 1)
    warn_entry = {
        "id": warn_id,
        "reason": reason,
        "moderator_id": moderator_id,
        "timestamp": datetime.utcnow()
    }

    await warns.update_one(
        {"guild_id": guild_id, "user_id": user_id},
        {
            "$push": {"warns": warn_entry},
            "$inc": {"next_id": 1}
        }
    )
    return warn_id


async def get_warns(guild_id: int, user_id: int) -> list:
    doc = await warns.find_one({"guild_id": guild_id, "user_id": user_id})
    return doc.get("warns", []) if doc else []


async def delete_warn(guild_id: int, user_id: int, warn_id: int) -> bool:
    result = await warns.update_one(
        {"guild_id": guild_id, "user_id": user_id},
        {"$pull": {"warns": {"id": warn_id}}}
    )
    return result.modified_count > 0


# ─── NOTES ───────────────────────────────────────────────────────────────────

async def add_note(guild_id: int, user_id: int, moderator_id: int, content: str) -> int:
    doc = await notes.find_one({"guild_id": guild_id, "user_id": user_id})
    if not doc:
        doc = {
            "guild_id": guild_id,
            "user_id": user_id,
            "notes": [],
            "next_id": 1
        }
        await notes.insert_one(doc)

    note_id = doc.get("next_id", 1)
    note_entry = {
        "id": note_id,
        "content": content,
        "moderator_id": moderator_id,
        "timestamp": datetime.utcnow()
    }

    await notes.update_one(
        {"guild_id": guild_id, "user_id": user_id},
        {
            "$push": {"notes": note_entry},
            "$inc": {"next_id": 1}
        }
    )
    return note_id


async def get_notes(guild_id: int, user_id: int) -> list:
    doc = await notes.find_one({"guild_id": guild_id, "user_id": user_id})
    return doc.get("notes", []) if doc else []


async def delete_note(guild_id: int, user_id: int, note_id: int) -> bool:
    result = await notes.update_one(
        {"guild_id": guild_id, "user_id": user_id},
        {"$pull": {"notes": {"id": note_id}}}
    )
    return result.modified_count > 0


# ─── LOCKS ───────────────────────────────────────────────────────────────────

async def set_lock(guild_id: int, channel_id: int, unlock_at: datetime | None, original_overwrites: dict):
    await locks.update_one(
        {"guild_id": guild_id, "channel_id": channel_id},
        {
            "$set": {
                "unlock_at": unlock_at,
                "original_overwrites": original_overwrites,
                "locked": True
            }
        },
        upsert=True
    )


async def get_lock(guild_id: int, channel_id: int):
    return await locks.find_one({"guild_id": guild_id, "channel_id": channel_id})


async def clear_lock(guild_id: int, channel_id: int):
    await locks.delete_one({"guild_id": guild_id, "channel_id": channel_id})
