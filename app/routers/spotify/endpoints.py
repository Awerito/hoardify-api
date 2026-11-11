import asyncio
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response

from app.auth import require_admin
from app.services.spotify import (
    get_auth_manager,
    get_spotify_client,
    get_redis_client,
    get_cached_now_playing,
    get_cached_now_playing_svg,
    get_saved_tracks_page,
)
from app.services.svg import generate_not_playing_svg
from app.database import MongoDBConnectionManager
from app.scheduler.jobs.spotify import (
    poll_current_playback,
    poll_recently_played,
    schedule_dashboard_refresh,
)
from app.services.plays import sync_all_missing_metadata

router = APIRouter(prefix="/spotify", tags=["Spotify"])


OAUTH_STATE_KEY = "spotify:oauth_state:{}"
OAUTH_STATE_TTL = 600  # seconds


@router.get("/authorize", summary="Get Spotify OAuth URL")
async def authorize(_: None = Depends(require_admin)):
    """Protected endpoint that returns the Spotify authorization URL."""
    state = secrets.token_urlsafe(32)
    get_redis_client().set(OAUTH_STATE_KEY.format(state), 1, ex=OAUTH_STATE_TTL)
    auth_manager = get_auth_manager()
    auth_url = auth_manager.get_authorize_url(state=state)
    return {"auth_url": auth_url}


@router.get("/callback", summary="Spotify OAuth callback")
async def callback(state: str, code: str | None = None, error: str | None = None):
    """OAuth callback endpoint. Stores token in Redis."""
    if not get_redis_client().delete(OAUTH_STATE_KEY.format(state)):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if error:
        raise HTTPException(
            status_code=400, detail=f"Spotify authorization failed: {error}"
        )
    auth_manager = get_auth_manager()
    await asyncio.to_thread(auth_manager.get_access_token, code, check_cache=False)
    return {
        "message": "Authentication successful. You can now use /spotify/now-playing"
    }


@router.get("/now-playing", summary="Get current track")
async def now_playing():
    """Get currently playing track from Redis cache (updated by job)."""
    redis_client = get_redis_client()
    data = get_cached_now_playing(redis_client)
    if not data:
        return JSONResponse(
            status_code=200,
            content={"is_playing": False, "message": "Nothing playing"},
        )
    return data


@router.get("/now-playing.svg", summary="Embeddable SVG widget")
async def now_playing_svg():
    """Get an embeddable SVG widget showing current track from cache."""
    redis_client = get_redis_client()
    svg = get_cached_now_playing_svg(redis_client)

    if not svg:
        svg = generate_not_playing_svg()

    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.post("/poll/current-playback", summary="Manually poll current playback")
async def manual_poll_current_playback(_: None = Depends(require_admin)):
    """Manually trigger current playback poll."""
    result = await poll_current_playback()
    return result


@router.post("/poll/recently-played", summary="Manually poll recently played")
async def manual_poll_recently_played(_: None = Depends(require_admin)):
    """Manually trigger recently played poll."""
    result = await poll_recently_played()
    return result


@router.post("/sync-metadata", summary="Sync all missing metadata")
async def manual_sync_metadata(_: None = Depends(require_admin)):
    """Sync missing artists and albums from tracks collection."""
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        return {"status": "error", "reason": "not authenticated with Spotify"}

    sp = get_spotify_client()

    async with MongoDBConnectionManager() as db:
        sync_result = await sync_all_missing_metadata(db, sp)

    schedule_dashboard_refresh()
    return {"status": "ok", **sync_result}


@router.post("/sync-favorites", summary="Sync liked songs to favorites collection")
async def sync_favorites(_: None = Depends(require_admin)):
    """Sync Spotify liked songs to favorites collection.

    Paginates through liked songs until finding a full page of already-known tracks.
    First run syncs entire library, subsequent runs stop early.
    """
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        return {"status": "error", "reason": "not authenticated with Spotify"}

    sp = get_spotify_client()

    inserted_count = 0
    pages_fetched = 0
    offset = 0
    limit = 50

    async with MongoDBConnectionManager() as db:
        favorites = db["favorites"]

        while True:
            tracks, total = await asyncio.to_thread(
                get_saved_tracks_page, sp, limit, offset
            )
            pages_fetched += 1

            if not tracks:
                break

            new_in_page = 0
            for track in tracks:
                existing = await favorites.find_one({"track_id": track["track_id"]})
                if not existing:
                    await favorites.insert_one(track)
                    inserted_count += 1
                    new_in_page += 1

            # If less than all tracks in page are new, we've hit known territory
            if new_in_page < len(tracks):
                break

            offset += limit

            # Safety: stop if we've gone through everything
            if offset >= total:
                break

    schedule_dashboard_refresh()
    return {
        "status": "ok",
        "inserted": inserted_count,
        "pages_fetched": pages_fetched,
    }
