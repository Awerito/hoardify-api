from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne

from app.utils.logger import logger


def parse_iso_datetime(value: str | datetime) -> datetime:
    """Parse ISO datetime string to datetime object."""
    if isinstance(value, datetime):
        return value
    # Handle 'Z' suffix (UTC)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


async def upsert_play(db: AsyncIOMotorDatabase, play: dict) -> bool:
    """
    Upsert a single play to the database.
    Returns True if inserted, False if updated.
    """
    played_at = parse_iso_datetime(play.get("played_at"))

    played_at_rounded = play.get("played_at_rounded")
    if played_at_rounded is None and played_at:
        played_at_rounded = played_at.replace(second=0, microsecond=0)

    filter_doc = {
        "track_id": play["track_id"],
        "played_at_rounded": played_at_rounded,
    }

    update_doc = {
        "$set": {
            "name": play["name"],
            "artists": play["artists"],
            "artist_ids": play["artist_ids"],
            "album": play["album"],
            "album_art": play.get("album_art"),
            "duration_ms": play["duration_ms"],
            "played_at": played_at,
            "played_at_rounded": played_at_rounded,
        },
        "$setOnInsert": {
            "track_id": play["track_id"],
            "created_at": datetime.now(timezone.utc),
        },
    }

    if play.get("device_name") is not None:
        update_doc["$set"]["device_name"] = play["device_name"]
    if play.get("device_type") is not None:
        update_doc["$set"]["device_type"] = play["device_type"]
    if play.get("context_type") is not None:
        update_doc["$set"]["context_type"] = play["context_type"]
    if play.get("context_uri") is not None:
        update_doc["$set"]["context_uri"] = play["context_uri"]
    if play.get("shuffle_state") is not None:
        update_doc["$set"]["shuffle_state"] = play["shuffle_state"]

    result = await db.plays.update_one(filter_doc, update_doc, upsert=True)
    return result.upserted_id is not None


async def upsert_plays(db: AsyncIOMotorDatabase, plays: list[dict]) -> dict:
    """
    Bulk upsert plays to the database.
    Returns counts of inserted and updated.
    """
    if not plays:
        return {"inserted": 0, "updated": 0}

    operations = []
    for play in plays:
        played_at = parse_iso_datetime(play.get("played_at"))

        played_at_rounded = play.get("played_at_rounded")
        if played_at_rounded is None and played_at:
            played_at_rounded = played_at.replace(second=0, microsecond=0)

        filter_doc = {
            "track_id": play["track_id"],
            "played_at_rounded": played_at_rounded,
        }

        update_doc = {
            "$set": {
                "name": play["name"],
                "artists": play["artists"],
                "artist_ids": play["artist_ids"],
                "album": play["album"],
                "album_art": play.get("album_art"),
                "duration_ms": play["duration_ms"],
                "played_at": played_at,
                "played_at_rounded": played_at_rounded,
            },
            "$setOnInsert": {
                "track_id": play["track_id"],
                "created_at": datetime.now(timezone.utc),
            },
        }

        if play.get("device_name") is not None:
            update_doc["$set"]["device_name"] = play["device_name"]
        if play.get("device_type") is not None:
            update_doc["$set"]["device_type"] = play["device_type"]
        if play.get("context_type") is not None:
            update_doc["$set"]["context_type"] = play["context_type"]
        if play.get("context_uri") is not None:
            update_doc["$set"]["context_uri"] = play["context_uri"]
        if play.get("shuffle_state") is not None:
            update_doc["$set"]["shuffle_state"] = play["shuffle_state"]

        operations.append(UpdateOne(filter_doc, update_doc, upsert=True))

    result = await db.plays.bulk_write(operations)
    return {
        "inserted": result.upserted_count,
        "updated": result.modified_count,
    }


async def ensure_plays_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create indexes for the plays and artists collections."""
    # Plays collection
    await db.plays.create_index(
        [("track_id", 1), ("played_at_rounded", 1)],
        unique=True,
        name="track_played_unique",
    )
    await db.plays.create_index("played_at", name="played_at_idx")
    await db.plays.create_index("artist_ids", name="artist_ids_idx")

    # Artists collection
    await db.artists.create_index("artist_id", unique=True, name="artist_id_unique")
    await db.artists.create_index("genres", name="genres_idx")

    logger.info("Database indexes ensured")
