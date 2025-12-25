from datetime import datetime, timezone

import spotipy
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services.rate_limiter import spotify_rate_limiter
from app.utils.logger import logger


def parse_iso_datetime(value: str | datetime) -> datetime:
    """Parse ISO datetime string to datetime object."""
    if isinstance(value, datetime):
        return value
    # Handle 'Z' suffix (UTC)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


async def upsert_track(
    db: AsyncIOMotorDatabase, track: dict, increment_count: bool = True
) -> bool:
    """
    Upsert a track to the tracks collection.

    Args:
        db: Database connection
        track: Track data from Spotify
        increment_count: If True, increment listen_count. Set False for backfill.

    Returns True if inserted (new track), False if updated.
    """
    now = datetime.now(timezone.utc)

    filter_doc = {"track_id": track["track_id"]}

    update_doc = {
        "$set": {
            "name": track["name"],
            "artists": track["artists"],
            "artist_ids": track["artist_ids"],
            "album": track["album"],
            "album_id": track.get("album_id"),
            "album_art": track.get("album_art"),
            "duration_ms": track["duration_ms"],
            "explicit": track.get("explicit"),
            "popularity": track.get("popularity"),
            "disc_number": track.get("disc_number"),
            "track_number": track.get("track_number"),
            "isrc": track.get("isrc"),
            "last_listened": now,
        },
        "$setOnInsert": {
            "track_id": track["track_id"],
            "first_listened": now,
            "listen_count": 0,
        },
    }

    if increment_count:
        update_doc["$inc"] = {"listen_count": 1}

    result = await db.tracks.update_one(filter_doc, update_doc, upsert=True)
    return result.upserted_id is not None


async def insert_play(db: AsyncIOMotorDatabase, play: dict) -> bool:
    """
    Insert a play entry to the plays log.

    Returns True if inserted, False if duplicate (already exists).
    """
    listened_at = parse_iso_datetime(play.get("played_at") or play.get("listened_at"))

    doc = {
        "track_id": play["track_id"],
        "listened_at": listened_at,
    }

    # Add optional fields if present
    if play.get("device_name") is not None:
        doc["device_name"] = play["device_name"]
    if play.get("device_type") is not None:
        doc["device_type"] = play["device_type"]
    if play.get("context_type") is not None:
        doc["context_type"] = play["context_type"]
    if play.get("context_uri") is not None:
        doc["context_uri"] = play["context_uri"]
    if play.get("shuffle_state") is not None:
        doc["shuffle_state"] = play["shuffle_state"]

    try:
        await db.plays.insert_one(doc)
        return True
    except Exception:
        # Duplicate key error - play already logged
        return False


async def insert_plays_bulk(db: AsyncIOMotorDatabase, plays: list[dict]) -> dict:
    """
    Bulk insert plays to the log. Skips duplicates.

    Returns counts of inserted and skipped.
    """
    if not plays:
        return {"inserted": 0, "skipped": 0}

    docs = []
    for play in plays:
        listened_at = parse_iso_datetime(
            play.get("played_at") or play.get("listened_at")
        )

        doc = {
            "track_id": play["track_id"],
            "listened_at": listened_at,
        }

        if play.get("device_name") is not None:
            doc["device_name"] = play["device_name"]
        if play.get("device_type") is not None:
            doc["device_type"] = play["device_type"]
        if play.get("context_type") is not None:
            doc["context_type"] = play["context_type"]
        if play.get("context_uri") is not None:
            doc["context_uri"] = play["context_uri"]
        if play.get("shuffle_state") is not None:
            doc["shuffle_state"] = play["shuffle_state"]

        docs.append(doc)

    try:
        result = await db.plays.insert_many(docs, ordered=False)
        inserted = len(result.inserted_ids)
    except Exception as e:
        # BulkWriteError - some duplicates
        inserted = getattr(e, "details", {}).get("nInserted", 0)

    return {"inserted": inserted, "skipped": len(docs) - inserted}


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create indexes for all collections."""
    # Tracks collection
    await db.tracks.create_index("track_id", unique=True, name="track_id_unique")
    await db.tracks.create_index("artist_ids", name="artist_ids_idx")
    await db.tracks.create_index("album_id", name="album_id_idx")
    await db.tracks.create_index("listen_count", name="listen_count_idx")

    # Plays collection (log)
    await db.plays.create_index("track_id", name="track_id_idx")
    await db.plays.create_index("listened_at", name="listened_at_idx")
    await db.plays.create_index(
        [("track_id", 1), ("listened_at", 1)],
        unique=True,
        name="track_listened_unique",
    )

    # Artists collection
    await db.artists.create_index("artist_id", unique=True, name="artist_id_unique")
    await db.artists.create_index("genres", name="genres_idx")

    # Albums collection
    await db.albums.create_index("album_id", unique=True, name="album_id_unique")

    logger.info("Database indexes ensured")


async def sync_missing_artists(
    db: AsyncIOMotorDatabase, sp: spotipy.Spotify, artist_ids: list[str]
) -> int:
    """Fetch and store artists that don't exist in DB. Returns count synced."""
    if not artist_ids:
        return 0

    # Check which artists already exist
    existing = await db.artists.find(
        {"artist_id": {"$in": artist_ids}}, {"artist_id": 1}
    ).to_list(length=len(artist_ids))
    existing_ids = {doc["artist_id"] for doc in existing}

    missing_ids = [aid for aid in artist_ids if aid not in existing_ids]
    if not missing_ids:
        return 0

    # Fetch from Spotify
    artists_data = sp.artists(missing_ids)
    spotify_rate_limiter.record_requests(1)
    artists = artists_data.get("artists", [])

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
                        artist["images"][0]["url"] if artist.get("images") else None
                    ),
                }
            )

    if docs:
        await db.artists.insert_many(docs)
        logger.info(f"Synced {len(docs)} artists")

    return len(docs)


async def sync_missing_album(
    db: AsyncIOMotorDatabase, sp: spotipy.Spotify, album_id: str | None
) -> int:
    """Fetch and store album if it doesn't exist. Returns 1 if synced, 0 otherwise."""
    if not album_id:
        return 0

    # Check if album exists
    existing = await db.albums.find_one({"album_id": album_id}, {"_id": 1})
    if existing:
        return 0

    # Fetch from Spotify
    album = sp.album(album_id)
    spotify_rate_limiter.record_requests(1)
    if not album:
        return 0

    doc = {
        "album_id": album["id"],
        "name": album["name"],
        "album_type": album.get("album_type"),
        "total_tracks": album.get("total_tracks"),
        "release_date": album.get("release_date"),
        "release_date_precision": album.get("release_date_precision"),
        "label": album.get("label"),
        "popularity": album.get("popularity"),
        "image": album["images"][0]["url"] if album.get("images") else None,
        "artist_ids": [a["id"] for a in album.get("artists", [])],
    }

    await db.albums.insert_one(doc)
    logger.info(f"Synced album: {album['name']}")

    return 1


async def sync_all_missing_metadata(
    db: AsyncIOMotorDatabase, sp: spotipy.Spotify
) -> dict:
    """
    Scan all tracks and sync any missing artists/albums.
    Returns counts of synced artists and albums.
    """
    artists_synced = 0
    albums_synced = 0

    # Get all unique artist_ids from tracks
    artist_ids_cursor = db.tracks.aggregate(
        [
            {"$unwind": "$artist_ids"},
            {"$group": {"_id": "$artist_ids"}},
        ]
    )
    all_artist_ids = [doc["_id"] async for doc in artist_ids_cursor]

    # Check which exist in DB
    existing_artists = await db.artists.find(
        {"artist_id": {"$in": all_artist_ids}}, {"artist_id": 1}
    ).to_list(length=len(all_artist_ids))
    existing_artist_ids = {doc["artist_id"] for doc in existing_artists}

    missing_artist_ids = [
        aid for aid in all_artist_ids if aid not in existing_artist_ids
    ]

    # Fetch missing artists in batches of 50
    for i in range(0, len(missing_artist_ids), 50):
        await spotify_rate_limiter.wait_if_needed()
        batch = missing_artist_ids[i : i + 50]
        artists_data = sp.artists(batch)
        spotify_rate_limiter.record_requests(1)
        artists = artists_data.get("artists", [])

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
            artists_synced += len(docs)

    # Get all unique album_ids from tracks
    album_ids_cursor = db.tracks.aggregate(
        [
            {"$match": {"album_id": {"$ne": None}}},
            {"$group": {"_id": "$album_id"}},
        ]
    )
    all_album_ids = [doc["_id"] async for doc in album_ids_cursor]

    # Check which exist in DB
    existing_albums = await db.albums.find(
        {"album_id": {"$in": all_album_ids}}, {"album_id": 1}
    ).to_list(length=len(all_album_ids))
    existing_album_ids = {doc["album_id"] for doc in existing_albums}

    missing_album_ids = [aid for aid in all_album_ids if aid not in existing_album_ids]

    # Fetch missing albums in batches of 20
    for i in range(0, len(missing_album_ids), 20):
        await spotify_rate_limiter.wait_if_needed()
        batch = missing_album_ids[i : i + 20]
        albums_data = sp.albums(batch)
        spotify_rate_limiter.record_requests(1)
        albums = albums_data.get("albums", [])

        docs = []
        for album in albums:
            if album:
                docs.append(
                    {
                        "album_id": album["id"],
                        "name": album["name"],
                        "album_type": album.get("album_type"),
                        "total_tracks": album.get("total_tracks"),
                        "release_date": album.get("release_date"),
                        "release_date_precision": album.get("release_date_precision"),
                        "label": album.get("label"),
                        "popularity": album.get("popularity"),
                        "image": (
                            album["images"][0]["url"] if album.get("images") else None
                        ),
                        "artist_ids": [a["id"] for a in album.get("artists", [])],
                    }
                )

        if docs:
            await db.albums.insert_many(docs)
            albums_synced += len(docs)

    if artists_synced or albums_synced:
        logger.info(
            f"sync_all_missing_metadata: {artists_synced} artists, {albums_synced} albums"
        )

    return {"artists_synced": artists_synced, "albums_synced": albums_synced}
