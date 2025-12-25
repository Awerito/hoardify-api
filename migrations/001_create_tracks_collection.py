"""
Migration 001: Create tracks collection from existing plays.

Aggregates plays by track_id to create a tracks collection with:
- Track metadata (name, artists, album, etc.)
- listen_count (computed from play count)
- first_listened, last_listened (denormalized timestamps)

Run with: python -m migrations.001_create_tracks_collection
"""

import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()


async def migrate():
    client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
    db = client.selfhoardify

    # Check if tracks already exists
    existing = await db.list_collection_names()
    if "tracks" in existing:
        count = await db.tracks.count_documents({})
        print(f"tracks collection already exists with {count} documents")
        print("Aborting to avoid data loss. Drop it manually if you want to re-run.")
        return

    # Count source documents
    plays_count = await db.plays.count_documents({})
    print(f"Source: {plays_count} documents in plays")

    # Aggregate plays into tracks
    pipeline = [
        {"$sort": {"played_at": 1}},
        {
            "$group": {
                "_id": "$track_id",
                "name": {"$first": "$name"},
                "artists": {"$first": "$artists"},
                "artist_ids": {"$first": "$artist_ids"},
                "album": {"$first": "$album"},
                "album_id": {"$first": "$album_id"},
                "album_art": {"$last": "$album_art"},
                "duration_ms": {"$first": "$duration_ms"},
                "isrc": {"$first": "$isrc"},
                "explicit": {"$first": "$explicit"},
                "popularity": {"$last": "$popularity"},
                "disc_number": {"$first": "$disc_number"},
                "track_number": {"$first": "$track_number"},
                "listen_count": {"$sum": 1},
                "first_listened": {"$first": "$played_at"},
                "last_listened": {"$last": "$played_at"},
            }
        },
        {"$set": {"track_id": "$_id"}},
        {"$unset": "_id"},
        {"$out": "tracks"},
    ]

    print("Running aggregation...")
    await db.plays.aggregate(pipeline).to_list(length=None)

    # Verify
    tracks_count = await db.tracks.count_documents({})
    print(f"Created: {tracks_count} documents in tracks")

    # Create index
    await db.tracks.create_index("track_id", unique=True, name="track_id_unique")
    print("Created unique index on track_id")

    print("Migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate())
