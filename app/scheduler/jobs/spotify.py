from datetime import datetime, timedelta

from app.database import MongoDBConnectionManager
from app.services.rate_limiter import spotify_rate_limiter
from app.services.spotify import (
    get_auth_manager,
    get_spotify_client,
    get_redis_client,
    get_current_playback,
    get_recently_played,
    cache_now_playing,
    cache_now_playing_svg,
    NOW_PLAYING_SVG_CACHE_KEY,
)
from app.services.svg import generate_now_playing_svg
from app.services.plays import (
    upsert_play,
    upsert_plays,
    sync_missing_artists,
    sync_missing_album,
)
from app.utils.logger import logger

# Will be set by register_jobs
_scheduler = None


def set_scheduler(scheduler) -> None:
    """Set the scheduler instance for dynamic rescheduling."""
    global _scheduler
    _scheduler = scheduler


def _schedule_next_poll() -> None:
    """Schedule next poll based on current rate limit usage."""
    if _scheduler is None:
        return

    stats = spotify_rate_limiter.get_stats()
    next_interval = stats["recommended_interval"]
    next_run = datetime.now() + timedelta(seconds=next_interval)

    try:
        _scheduler.add_job(
            poll_current_playback,
            trigger="date",
            run_date=next_run,
            id="poll_current_playback",
            replace_existing=True,
        )
        logger.info(
            f"Next poll in {next_interval}s "
            f"(requests: {stats['requests_in_window']}/{stats['max_requests']}, "
            f"usage: {stats['usage_ratio']:.0%})"
        )
    except Exception as e:
        logger.warning(f"Failed to schedule next poll: {e}")


async def poll_current_playback():
    """Poll current playback dynamically, save to DB and cache to Redis."""
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        _schedule_next_poll()
        return {"status": "skipped", "reason": "not authenticated"}

    sp = get_spotify_client()
    redis_client = get_redis_client()

    data = get_current_playback(sp)
    spotify_rate_limiter.record_requests(1)

    if not data:
        # Nothing playing - delete cache, let it expire to "Offline"
        cache_now_playing(redis_client, None)
        redis_client.delete(NOW_PLAYING_SVG_CACHE_KEY)
        logger.info("Nothing playing")
        _schedule_next_poll()
        return {"status": "ok", "playing": False}

    now_playing = data["now_playing"]

    # Calculate TTL: remaining time + 30 sec buffer
    remaining_ms = now_playing["duration_ms"] - now_playing["progress_ms"]
    ttl_seconds = max((remaining_ms // 1000) + 30, 60)  # At least 60 sec

    cache_now_playing(redis_client, now_playing, ttl_seconds)

    # Generate and cache SVG with same TTL
    svg = generate_now_playing_svg(
        title=now_playing["title"],
        artist=now_playing["artist"],
        album_art_url=now_playing["album_art"],
        is_playing=now_playing["is_playing"],
    )
    cache_now_playing_svg(redis_client, svg, ttl_seconds)

    async with MongoDBConnectionManager() as db:
        is_new = await upsert_play(db, data["play"])

        # Sync missing artists/album if new play
        if is_new:
            play = data["play"]
            await sync_missing_artists(db, sp, play.get("artist_ids", []))
            await sync_missing_album(db, sp, play.get("album_id"))

    status = "NEW" if is_new else "playing"
    logger.info(f"[{status}] {now_playing['artist']} - {now_playing['title']}")

    _schedule_next_poll()
    return {"status": "ok", "playing": True, "inserted": is_new}


async def poll_recently_played():
    """Poll recently played every hour, save to DB with exact played_at."""
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        return {"status": "skipped", "reason": "not authenticated"}

    sp = get_spotify_client()
    plays = get_recently_played(sp, limit=50)
    spotify_rate_limiter.record_requests(1)

    if not plays:
        return {"status": "ok", "plays": 0}

    async with MongoDBConnectionManager() as db:
        result = await upsert_plays(db, plays)

    logger.info(
        f"poll_recently_played: {result['inserted']} inserted, "
        f"{result['updated']} updated"
    )
    return {"status": "ok", **result}
