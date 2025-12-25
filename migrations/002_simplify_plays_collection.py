"""
Migration 002: Simplify plays collection to log format.

Transforms plays from full track metadata to simple log:
- track_id
- listened_at
- device_name, device_type
- context_type, context_uri
- shuffle_state

Run with: python -m migrations.002_simplify_plays_collection
"""

import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()


async def migrate():
    client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
    db = client.selfhoardify

    # Check if plays_old already exists
    existing = await db.list_collection_names()
    if "plays_old" in existing:
        print("plays_old already exists. Aborting to avoid data loss.")
        print("Drop it manually if you want to re-run.")
        return

    if "plays" not in existing:
        print("plays collection not found. Nothing to migrate.")
        return

    # Count source documents
    plays_count = await db.plays.count_documents({})
    print(f"Source: {plays_count} documents in plays")

    # Rename plays to plays_old
    print("Renaming plays -> plays_old...")
    await db.plays.rename("plays_old")

    # Create new plays with simplified structure
    pipeline = [
        {
            "$project": {
                "_id": 0,
                "track_id": 1,
                "listened_at": "$played_at",
                "device_name": 1,
                "device_type": 1,
                "context_type": 1,
                "context_uri": 1,
                "shuffle_state": 1,
            }
        },
        {"$out": "plays"},
    ]

    print("Creating simplified plays collection...")
    await db.plays_old.aggregate(pipeline).to_list(length=None)

    # Verify
    new_count = await db.plays.count_documents({})
    print(f"Created: {new_count} documents in plays")

    # Create indexes
    await db.plays.create_index("track_id", name="track_id_idx")
    await db.plays.create_index("listened_at", name="listened_at_idx")
    await db.plays.create_index(
        [("track_id", 1), ("listened_at", 1)],
        unique=True,
        name="track_listened_unique",
    )
    print("Created indexes on plays")

    print("Migration complete!")
    print("plays_old kept as backup. Drop manually when ready:")
    print("  db.plays_old.drop()")


if __name__ == "__main__":
    asyncio.run(migrate())
