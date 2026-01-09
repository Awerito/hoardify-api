import asyncio
from datetime import datetime, timedelta

from app.database import MongoDBConnectionManager
from app.services.cache import ensure_album_art_cached
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
    upsert_track,
    insert_play,
    sync_missing_artists,
    sync_missing_album,
)
from app.utils.logger import logger

# Will be set by register_jobs
_scheduler = None

LAST_TRACK_KEY = "spotify:last_track_id"
SPOTIFY_API_TIMEOUT = 10  # seconds


def set_scheduler(scheduler) -> None:
    """Set the scheduler instance for dynamic rescheduling."""
    global _scheduler
    _scheduler = scheduler


def _schedule_next_poll(requests_made: int = 1, reason: str = "") -> None:
    """
    Schedule next poll based on requests made this cycle.

    Simple logic:
    - 1 request (known track) → next poll in 1s
    - 2+ requests (new track) → next poll in 2s
    """
    if _scheduler is None:
        logger.error("Cannot schedule next poll: scheduler is None")
        return

    next_interval = 2.0 if requests_made > 1 else 1.0
    next_run = datetime.now() + timedelta(seconds=next_interval)

    try:
        _scheduler.add_job(
            poll_current_playback,
            trigger="date",
            run_date=next_run,
            id="poll_current_playback",
            replace_existing=True,
            misfire_grace_time=60,
        )
        if reason:
            logger.debug(f"Next poll in {next_interval}s ({reason})")
    except Exception as e:
        logger.error(f"Failed to schedule next poll: {e}")


async def poll_current_playback():
    """Poll current playback, detect track changes, update tracks + plays."""
    requests_made = 0
    schedule_reason = "poll"

    try:
        auth_manager = get_auth_manager()
        token_info = auth_manager.get_cached_token()
        if not token_info:
            logger.warning("poll_current_playback skipped: no token cached")
            schedule_reason = "no token"
            return {"status": "skipped", "reason": "not authenticated"}

        sp = get_spotify_client()
        redis_client = get_redis_client()

        # Wrap Spotify API call with timeout to prevent hanging
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(get_current_playback, sp),
                timeout=SPOTIFY_API_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"poll_current_playback: Spotify API timeout ({SPOTIFY_API_TIMEOUT}s)"
            )
            schedule_reason = "api timeout"
            return {"status": "error", "reason": "spotify api timeout"}

        requests_made += 1

        if not data:
            # Nothing playing - clear cache and last_track_id
            cache_now_playing(redis_client, None)
            redis_client.delete(NOW_PLAYING_SVG_CACHE_KEY)
            redis_client.delete(LAST_TRACK_KEY)
            logger.info("Nothing playing")
            schedule_reason = "nothing playing"
            return {"status": "ok", "playing": False}

        now_playing = data["now_playing"]
        play = data["play"]
        current_track_id = play["track_id"]

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

        # Pre-cache album art for dashboard grid
        ensure_album_art_cached(redis_client, now_playing.get("album_art"))

        # Check if track changed
        last_track_id = redis_client.get(LAST_TRACK_KEY)
        if last_track_id:
            last_track_id = last_track_id.decode("utf-8")

        is_new_listen = current_track_id != last_track_id

        if is_new_listen:
            async with MongoDBConnectionManager() as db:
                # Upsert track (increments listen_count)
                is_new_track = await upsert_track(db, play, increment_count=True)

                # Insert play to log
                await insert_play(db, play)

                # Sync missing artists/album if new track
                if is_new_track:
                    artists_synced = await sync_missing_artists(
                        db, sp, play.get("artist_ids", [])
                    )
                    if artists_synced > 0:
                        requests_made += 1

                    album_synced = await sync_missing_album(
                        db, sp, play.get("album_id")
                    )
                    if album_synced > 0:
                        requests_made += 1

            # Update last track in Redis
            redis_client.set(LAST_TRACK_KEY, current_track_id)

            status = "NEW TRACK" if is_new_track else "NEW LISTEN"
            logger.info(f"[{status}] {now_playing['artist']} - {now_playing['title']}")
            schedule_reason = "new listen"
        else:
            schedule_reason = "same track"

        return {"status": "ok", "playing": True, "new_listen": is_new_listen}

    except Exception as e:
        logger.error(f"poll_current_playback failed: {e}", exc_info=True)
        schedule_reason = f"error: {type(e).__name__}"
        return {"status": "error", "reason": str(e)}

    finally:
        _schedule_next_poll(requests_made, schedule_reason)


def ensure_poller_alive() -> None:
    """Watchdog: ensure poll_current_playback job exists, revive if dead."""
    if _scheduler is None:
        logger.error("Watchdog: scheduler is None")
        return

    job = _scheduler.get_job("poll_current_playback")
    if job is None:
        logger.warning("Watchdog: poll_current_playback job not found, reviving...")
        _schedule_next_poll(1, "watchdog revive")
    else:
        logger.debug(f"Watchdog: poller alive, next run at {job.next_run_time}")


async def poll_recently_played():
    """Poll recently played every hour, backfill plays log."""
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        return {"status": "skipped", "reason": "not authenticated"}

    sp = get_spotify_client()
    plays = await asyncio.to_thread(get_recently_played, sp, 50)

    if not plays:
        return {"status": "ok", "inserted": 0, "skipped": 0}

    inserted = 0
    skipped = 0

    async with MongoDBConnectionManager() as db:
        for play in plays:
            # Insert play - returns True if new, False if duplicate
            was_new = await insert_play(db, play)
            if was_new:
                inserted += 1
                # Only increment listen_count for plays not seen before
                await upsert_track(db, play, increment_count=True)
            else:
                skipped += 1
                # Still upsert track metadata but don't increment count
                await upsert_track(db, play, increment_count=False)

    logger.info(f"poll_recently_played: {inserted} inserted, {skipped} skipped")
    return {"status": "ok", "inserted": inserted, "skipped": skipped}
