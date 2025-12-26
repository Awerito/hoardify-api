from datetime import datetime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

import cairosvg
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.database import MongoDBConnectionManager
from app.services.svg import generate_listening_grid_svg


class GridFormat(str, Enum):
    svg = "svg"
    png = "png"


DISPLAY_TZ = "America/Santiago"

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
templates = Jinja2Templates(directory="app/templates")


async def get_today_stats() -> dict:
    """Calculate today's listening stats."""
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with MongoDBConnectionManager() as db:
        # Base match for today's plays
        match_today = {"listened_at": {"$gte": start_of_day}}

        # Total plays
        total_plays = await db.plays.count_documents(match_today)

        if total_plays == 0:
            return {
                "date": now.strftime("%Y-%m-%d"),
                "total_plays": 0,
                "total_minutes": 0,
                "unique_tracks": 0,
                "unique_artists": 0,
                "top_tracks": [],
                "top_artists": [],
                "hours": {},
                "max_hour_count": 0,
            }

        # Aggregate stats in one pipeline
        pipeline = [
            {"$match": match_today},
            {
                "$lookup": {
                    "from": "tracks",
                    "localField": "track_id",
                    "foreignField": "track_id",
                    "as": "track",
                }
            },
            {"$unwind": "$track"},
            {
                "$group": {
                    "_id": None,
                    "total_minutes": {
                        "$sum": {"$divide": ["$track.duration_ms", 60000]}
                    },
                    "unique_tracks": {"$addToSet": "$track_id"},
                    "unique_artists": {"$addToSet": "$track.artist_ids"},
                    "plays": {
                        "$push": {
                            "track_id": "$track_id",
                            "name": "$track.name",
                            "artists": "$track.artists",
                            "artist_ids": "$track.artist_ids",
                            "hour": {"$hour": "$listened_at"},
                        }
                    },
                }
            },
        ]

        result = await db.plays.aggregate(pipeline).to_list(length=1)

        if not result:
            return {
                "date": now.strftime("%Y-%m-%d"),
                "total_plays": 0,
                "total_minutes": 0,
                "unique_tracks": 0,
                "unique_artists": 0,
                "top_tracks": [],
                "top_artists": [],
                "hours": {},
                "max_hour_count": 0,
            }

        data = result[0]
        plays = data["plays"]

        # Flatten artist_ids and count unique
        all_artist_ids = set()
        for artist_list in data["unique_artists"]:
            all_artist_ids.update(artist_list)

        # Count plays per track
        track_counts = {}
        for play in plays:
            tid = play["track_id"]
            if tid not in track_counts:
                track_counts[tid] = {
                    "track_id": tid,
                    "name": play["name"],
                    "artists": play["artists"],
                    "count": 0,
                }
            track_counts[tid]["count"] += 1

        top_tracks = sorted(
            track_counts.values(), key=lambda x: x["count"], reverse=True
        )[:10]

        # Count plays per artist
        artist_counts = {}
        for play in plays:
            for i, aid in enumerate(play["artist_ids"]):
                if aid not in artist_counts:
                    artist_counts[aid] = {
                        "artist_id": aid,
                        "name": play["artists"][i] if i < len(play["artists"]) else aid,
                        "count": 0,
                    }
                artist_counts[aid]["count"] += 1

        top_artists = sorted(
            artist_counts.values(), key=lambda x: x["count"], reverse=True
        )[:10]

        # Count plays per hour
        hours = {}
        for play in plays:
            h = str(play["hour"])
            hours[h] = hours.get(h, 0) + 1

        max_hour_count = max(hours.values()) if hours else 0

        return {
            "date": now.strftime("%Y-%m-%d"),
            "total_plays": total_plays,
            "total_minutes": round(data["total_minutes"], 1),
            "unique_tracks": len(data["unique_tracks"]),
            "unique_artists": len(all_artist_ids),
            "top_tracks": top_tracks,
            "top_artists": top_artists,
            "hours": hours,
            "max_hour_count": max_hour_count,
        }


@router.get("/today", summary="Get today's listening stats (JSON)")
async def today_stats_json():
    """Get real-time stats for today's listening activity as JSON."""
    return await get_today_stats()


@router.get("/today/view", response_class=HTMLResponse, summary="View today's stats")
async def today_stats_html(request: Request):
    """View today's listening stats as HTML dashboard."""
    stats = await get_today_stats()
    return templates.TemplateResponse(
        request,
        "dashboard/today.html",
        {"stats": stats},
    )


async def get_plays_by_day_hour(days: int = 7) -> dict[str, dict[int, dict]]:
    """Get last play per hour for each day in the grid.

    Args:
        days: Number of days to include (default 7).

    Returns:
        Dict mapping date string to dict mapping hour to play data.
        Dates and hours are in Chilean time (America/Santiago).
    """
    # Calculate date range in Chilean time
    local_tz = ZoneInfo(DISPLAY_TZ)
    now_local = datetime.now(local_tz)

    # Convert to UTC for MongoDB query (include up to current moment)
    now_utc = now_local.astimezone(timezone.utc)

    # Start from beginning of hour, days ago
    start_local = now_local.replace(minute=0, second=0, microsecond=0) - timedelta(days=days)
    start_utc = start_local.astimezone(timezone.utc)

    async with MongoDBConnectionManager() as db:
        pipeline = [
            {"$match": {"listened_at": {"$gte": start_utc, "$lt": now_utc}}},
            {"$sort": {"listened_at": 1}},
            # Group by Chilean time (not UTC)
            {
                "$group": {
                    "_id": {
                        "date": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$listened_at",
                                "timezone": DISPLAY_TZ,
                            }
                        },
                        "hour": {
                            "$hour": {"date": "$listened_at", "timezone": DISPLAY_TZ}
                        },
                    },
                    "last_track_id": {"$last": "$track_id"},
                    "play_count": {"$sum": 1},
                }
            },
            # JOIN only with unique hour entries (~168 max for 7 days)
            {
                "$lookup": {
                    "from": "tracks",
                    "localField": "last_track_id",
                    "foreignField": "track_id",
                    "as": "track",
                }
            },
            {"$unwind": "$track"},
            {
                "$project": {
                    "_id": 0,
                    "date": "$_id.date",
                    "hour": "$_id.hour",
                    "track_id": "$last_track_id",
                    "name": "$track.name",
                    "album_art": "$track.album_art",
                    "play_count": 1,
                }
            },
        ]
        plays = await db.plays.aggregate(pipeline).to_list(length=500)

    # Build result dict
    plays_by_day_hour: dict[str, dict[int, dict]] = {}

    # Initialize all days in range (Chilean time)
    for i in range(days):
        day = (start_local + timedelta(days=i)).strftime("%Y-%m-%d")
        plays_by_day_hour[day] = {}

    for play in plays:
        day = play["date"]
        hour = play["hour"]
        if day not in plays_by_day_hour:
            plays_by_day_hour[day] = {}
        plays_by_day_hour[day][hour] = play

    return plays_by_day_hour


@router.get("/grid.svg", summary="Listening grid (SVG) - deprecated")
async def listening_grid_svg_legacy(days: int = 7):
    """Deprecated: Use /grid?format=svg instead."""
    return await listening_grid(days=days, format=GridFormat.svg)


@router.get("/grid", summary="Listening grid")
async def listening_grid(days: int = 7, format: GridFormat = GridFormat.svg):
    """Generate a GitHub-style listening grid with album art.

    Shows listening activity over multiple days.
    - Rows: days (oldest at top)
    - Columns: 24 hours
    - Cells: album art of last track played in that hour

    Query params:
        days: Number of days to show (default 7, max 30)
        format: Output format - svg or png (default svg)
                Use png for GitHub READMEs (GitHub blocks SVGs with embedded images)
    """
    days = min(max(days, 1), 30)  # Clamp to 1-30
    plays_by_day_hour = await get_plays_by_day_hour(days)
    svg = generate_listening_grid_svg(plays_by_day_hour)

    if format == GridFormat.png:
        png = cairosvg.svg2png(bytestring=svg.encode("utf-8"))
        return Response(
            content=png,
            media_type="image/png",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
