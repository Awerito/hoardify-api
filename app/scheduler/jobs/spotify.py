from app.database import MongoDBConnectionManager
from app.services.spotify import (
    get_auth_manager,
    get_spotify_client,
    get_redis_client,
    get_current_playback,
    get_recently_played,
    cache_now_playing,
)
from app.services.plays import upsert_play, upsert_plays
from app.utils.logger import logger


async def poll_current_playback():
    """Poll current playback every 30 seconds, save to DB and cache to Redis."""
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        return {"status": "skipped", "reason": "not authenticated"}

    sp = get_spotify_client()
    redis_client = get_redis_client()

    data = get_current_playback(sp)

    if not data:
        cache_now_playing(redis_client, None)
        return {"status": "ok", "playing": False}

    cache_now_playing(redis_client, data["now_playing"])

    async with MongoDBConnectionManager() as db:
        is_new = await upsert_play(db, data["play"])

    return {"status": "ok", "playing": True, "inserted": is_new}


async def poll_recently_played():
    """Poll recently played every hour, save to DB with exact played_at."""
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        return {"status": "skipped", "reason": "not authenticated"}

    sp = get_spotify_client()
    plays = get_recently_played(sp, limit=50)

    if not plays:
        return {"status": "ok", "plays": 0}

    async with MongoDBConnectionManager() as db:
        result = await upsert_plays(db, plays)

    logger.info(
        f"poll_recently_played: {result['inserted']} inserted, "
        f"{result['updated']} updated"
    )
    return {"status": "ok", **result}


async def sync_artists():
    """Sync artist genres for artists without genre data (2x per day)."""
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        return {"status": "skipped", "reason": "not authenticated"}

    sp = get_spotify_client()

    async with MongoDBConnectionManager() as db:
        # Find artist_ids from plays that aren't in artists collection
        pipeline = [
            {"$unwind": "$artist_ids"},
            {"$group": {"_id": "$artist_ids"}},
            {
                "$lookup": {
                    "from": "artists",
                    "localField": "_id",
                    "foreignField": "artist_id",
                    "as": "artist",
                }
            },
            {"$match": {"artist": {"$size": 0}}},
            {"$limit": 50},
        ]
        missing = await db.plays.aggregate(pipeline).to_list(length=50)
        missing_ids = [doc["_id"] for doc in missing]

        if not missing_ids:
            return {"status": "ok", "synced": 0}

        # Fetch artists from Spotify (max 50 per request)
        artists_data = sp.artists(missing_ids)
        artists = artists_data.get("artists", [])

        # Insert into artists collection
        docs = []
        for artist in artists:
            if artist:
                docs.append(
                    {
                        "artist_id": artist["id"],
                        "name": artist["name"],
                        "genres": artist.get("genres", []),
                        "popularity": artist.get("popularity"),
                        "image": (
                            artist["images"][0]["url"]
                            if artist.get("images")
                            else None
                        ),
                    }
                )

        if docs:
            await db.artists.insert_many(docs)
            logger.info(f"sync_artists: synced {len(docs)} artists")

    return {"status": "ok", "synced": len(docs)}
