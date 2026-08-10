import statistics
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.database import MongoDBConnectionManager

DISPLAY_TZ = "America/Santiago"
STATS_COLLECTION = "dashboard_stats"
STATS_ID = "current"

# plays -> tracks join, reused across aggregations
TRACK_LOOKUP = [
    {
        "$lookup": {
            "from": "tracks",
            "localField": "track_id",
            "foreignField": "track_id",
            "as": "t",
        }
    },
    {"$unwind": "$t"},
]


async def _totals(db: AsyncIOMotorDatabase) -> dict:
    return {
        "plays": await db.plays.count_documents({}),
        "tracks": await db.tracks.count_documents({}),
        "artists": await db.artists.count_documents({}),
        "albums": await db.albums.count_documents({}),
        "favorites": await db.favorites.count_documents({}),
    }


async def _total_minutes(db: AsyncIOMotorDatabase) -> int:
    res = await db.plays.aggregate(
        [
            *TRACK_LOOKUP,
            {"$group": {"_id": None, "ms": {"$sum": "$t.duration_ms"}}},
        ]
    ).to_list(length=1)
    return round(res[0]["ms"] / 60000) if res else 0


async def _plays_per_month(db: AsyncIOMotorDatabase) -> list[dict]:
    rows = await db.plays.aggregate(
        [
            {
                "$group": {
                    "_id": {
                        "$dateToString": {"format": "%Y-%m", "date": "$listened_at"}
                    },
                    "n": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
        ]
    ).to_list(length=None)
    return [{"month": r["_id"], "plays": r["n"]} for r in rows]


async def _top_artists(db: AsyncIOMotorDatabase) -> list[dict]:
    return await db.plays.aggregate(
        [
            *TRACK_LOOKUP,
            {"$unwind": "$t.artist_ids"},
            {"$group": {"_id": "$t.artist_ids", "plays": {"$sum": 1}}},
            {"$sort": {"plays": -1}},
            {"$limit": 10},
            {
                "$lookup": {
                    "from": "artists",
                    "localField": "_id",
                    "foreignField": "artist_id",
                    "as": "a",
                }
            },
            {"$unwind": "$a"},
            {
                "$project": {
                    "_id": 0,
                    "name": "$a.name",
                    "plays": 1,
                    "image": "$a.image",
                }
            },
        ]
    ).to_list(length=10)


async def _top_albums(db: AsyncIOMotorDatabase) -> list[dict]:
    """Top albums by plays, each with its per-month series (for the muro slider)."""
    albums = await db.plays.aggregate(
        [
            *TRACK_LOOKUP,
            {
                "$group": {
                    "_id": "$t.album_id",
                    "plays": {"$sum": 1},
                    "album": {"$first": "$t.album"},
                    "art": {"$first": "$t.album_art"},
                }
            },
            {"$sort": {"plays": -1}},
            {"$limit": 30},
            {
                "$project": {
                    "_id": 0,
                    "album_id": "$_id",
                    "album": 1,
                    "plays": 1,
                    "art": 1,
                }
            },
        ]
    ).to_list(length=30)

    top_ids = [a["album_id"] for a in albums]
    monthly_rows = await db.plays.aggregate(
        [
            *TRACK_LOOKUP,
            {"$match": {"t.album_id": {"$in": top_ids}}},
            {
                "$group": {
                    "_id": {
                        "aid": "$t.album_id",
                        "ym": {
                            "$dateToString": {"format": "%Y-%m", "date": "$listened_at"}
                        },
                    },
                    "n": {"$sum": 1},
                }
            },
        ]
    ).to_list(length=None)

    series = {aid: {} for aid in top_ids}
    for r in monthly_rows:
        series[r["_id"]["aid"]][r["_id"]["ym"]] = r["n"]
    for a in albums:
        a["monthly"] = series.get(a["album_id"], {})
    return albums


async def _top_tracks(db: AsyncIOMotorDatabase) -> list[dict]:
    return await db.plays.aggregate(
        [
            {"$group": {"_id": "$track_id", "plays": {"$sum": 1}}},
            {"$sort": {"plays": -1}},
            {"$limit": 10},
            {
                "$lookup": {
                    "from": "tracks",
                    "localField": "_id",
                    "foreignField": "track_id",
                    "as": "t",
                }
            },
            {"$unwind": "$t"},
            {
                "$project": {
                    "_id": 0,
                    "name": "$t.name",
                    "artists": "$t.artists",
                    "art": "$t.album_art",
                    "plays": 1,
                }
            },
        ]
    ).to_list(length=10)


async def _top_genres(db: AsyncIOMotorDatabase) -> list[dict]:
    rows = await db.plays.aggregate(
        [
            *TRACK_LOOKUP,
            {"$unwind": "$t.artist_ids"},
            {
                "$lookup": {
                    "from": "artists",
                    "localField": "t.artist_ids",
                    "foreignField": "artist_id",
                    "as": "a",
                }
            },
            {"$unwind": "$a"},
            {"$unwind": "$a.genres"},
            {"$group": {"_id": "$a.genres", "plays": {"$sum": 1}}},
            {"$sort": {"plays": -1}},
            {"$limit": 12},
            {"$project": {"_id": 0, "genre": "$_id", "plays": 1}},
        ]
    ).to_list(length=12)
    return rows


async def _heat(db: AsyncIOMotorDatabase) -> tuple[list[list[int]], int]:
    """7x24 grid (Mon..Sun rows, hour cols) of play counts, local tz. Plus peak hour."""
    rows = await db.plays.aggregate(
        [
            {
                "$group": {
                    "_id": {
                        "dow": {
                            "$dayOfWeek": {
                                "date": "$listened_at",
                                "timezone": DISPLAY_TZ,
                            }
                        },
                        "hour": {
                            "$hour": {"date": "$listened_at", "timezone": DISPLAY_TZ}
                        },
                    },
                    "n": {"$sum": 1},
                }
            },
        ]
    ).to_list(length=None)
    heat = [[0] * 24 for _ in range(7)]
    for r in rows:
        mon0 = (r["_id"]["dow"] + 5) % 7  # Sun(1)->6, Mon(2)->0 ... Sat(7)->5
        heat[mon0][r["_id"]["hour"]] = r["n"]
    hours_total = [sum(heat[d][h] for d in range(7)) for h in range(24)]
    peak_hour = max(range(24), key=lambda h: hours_total[h])
    return heat, peak_hour


async def _heat_top(db: AsyncIOMotorDatabase) -> list[list[dict | None]]:
    """Most-played track (label + album_art) per (weekday, hour) — for ridgeline hover."""
    rows = await db.plays.aggregate(
        [
            {
                "$group": {
                    "_id": {
                        "dow": {
                            "$dayOfWeek": {
                                "date": "$listened_at",
                                "timezone": DISPLAY_TZ,
                            }
                        },
                        "hour": {
                            "$hour": {"date": "$listened_at", "timezone": DISPLAY_TZ}
                        },
                        "track_id": "$track_id",
                    },
                    "n": {"$sum": 1},
                }
            },
            {"$sort": {"n": -1}},
        ]
    ).to_list(length=None)

    top_bucket = {}
    for r in rows:
        key = (r["_id"]["dow"], r["_id"]["hour"])
        if key not in top_bucket:
            top_bucket[key] = r["_id"]["track_id"]

    tid_set = list(set(top_bucket.values()))
    tracks = await db.tracks.find(
        {"track_id": {"$in": tid_set}},
        {"track_id": 1, "name": 1, "artists": 1, "album_art": 1},
    ).to_list(length=None)
    info = {
        t["track_id"]: {
            "label": f"{t['name']} · {', '.join(t.get('artists', []))}",
            "art": t.get("album_art"),
        }
        for t in tracks
    }

    grid: list[list[dict | None]] = [[None] * 24 for _ in range(7)]
    for (dow, hour), tid in top_bucket.items():
        grid[(dow + 5) % 7][hour] = info.get(tid)
    return grid


async def _shuffle_pct(db: AsyncIOMotorDatabase) -> int | None:
    true = await db.plays.count_documents({"shuffle_state": True})
    known = await db.plays.count_documents({"shuffle_state": {"$ne": None}})
    return round(100 * true / known) if known else None


async def _era(db: AsyncIOMotorDatabase) -> dict:
    """Median/oldest/newest release year of what you play, weighted by plays."""
    rows = await db.plays.aggregate(
        [
            *TRACK_LOOKUP,
            {
                "$lookup": {
                    "from": "albums",
                    "localField": "t.album_id",
                    "foreignField": "album_id",
                    "as": "al",
                }
            },
            {"$unwind": "$al"},
            {"$project": {"_id": 0, "y": {"$substrBytes": ["$al.release_date", 0, 4]}}},
        ]
    ).to_list(length=None)
    years = [int(r["y"]) for r in rows if r.get("y") and r["y"].isdigit()]
    if not years:
        return {"median": None, "oldest": None, "newest": None}
    return {
        "median": int(statistics.median(years)),
        "oldest": min(years),
        "newest": max(years),
    }


async def _streak(db: AsyncIOMotorDatabase) -> dict:
    """Longest run of consecutive local days with at least one play."""
    rows = await db.plays.aggregate(
        [
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$listened_at",
                            "timezone": DISPLAY_TZ,
                        }
                    }
                }
            },
            {"$sort": {"_id": 1}},
        ]
    ).to_list(length=None)
    days = [datetime.strptime(r["_id"], "%Y-%m-%d") for r in rows]
    longest = cur = 1 if days else 0
    for i in range(1, len(days)):
        if (days[i] - days[i - 1]).days == 1:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 1
    return {"longest": longest, "active_days": len(days)}


async def _plays_per_day(db: AsyncIOMotorDatabase) -> list[dict]:
    rows = await db.plays.aggregate(
        [
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$listened_at",
                            "timezone": DISPLAY_TZ,
                        }
                    },
                    "n": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
        ]
    ).to_list(length=None)
    return [{"day": r["_id"], "n": r["n"]} for r in rows]


async def _span(db: AsyncIOMotorDatabase) -> dict:
    first = await db.plays.find_one({}, sort=[("listened_at", 1)])
    last = await db.plays.find_one({}, sort=[("listened_at", -1)])
    fmt = lambda d: d["listened_at"].strftime("%Y-%m-%d") if d else None
    return {"start": fmt(first), "end": fmt(last)}


async def compute_dashboard(db: AsyncIOMotorDatabase) -> dict:
    """Compute the full dashboard payload from Mongo (read-only)."""
    totals = await _totals(db)
    heat, peak_hour = await _heat(db)
    payload = {
        **totals,
        "total_minutes": await _total_minutes(db),
        "plays_per_month": await _plays_per_month(db),
        "top_artists": await _top_artists(db),
        "top_albums": await _top_albums(db),
        "top_tracks": await _top_tracks(db),
        "top_genres": await _top_genres(db),
        "heat": heat,
        "peak_hour": peak_hour,
        "heat_top": await _heat_top(db),
        "shuffle_pct": await _shuffle_pct(db),
        "era": await _era(db),
        "streak": await _streak(db),
        "plays_per_day": await _plays_per_day(db),
        "span": await _span(db),
    }
    payload["avg_plays_per_track"] = (
        round(payload["plays"] / payload["tracks"], 2) if payload["tracks"] else 0
    )
    return payload


async def refresh_dashboard_stats() -> dict:
    """Recompute the materialized dashboard doc and return it. Run by the
    scheduler and after writes that change the numbers (e.g. favorites sync)."""
    async with MongoDBConnectionManager() as db:
        payload = await compute_dashboard(db)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        doc = {"_id": STATS_ID, **payload}
        await db[STATS_COLLECTION].replace_one({"_id": STATS_ID}, doc, upsert=True)
    return doc


async def read_dashboard_stats() -> dict:
    """Read the materialized dashboard doc (cheap find_one). Builds it once if
    it does not exist yet."""
    async with MongoDBConnectionManager() as db:
        doc = await db[STATS_COLLECTION].find_one({"_id": STATS_ID})
    return doc if doc is not None else await refresh_dashboard_stats()
