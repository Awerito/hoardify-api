from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from app.auth import User, current_active_user
from app.services.spotify import (
    get_auth_manager,
    get_spotify_client,
    get_redis_client,
    get_cached_now_playing,
    get_cached_now_playing_svg,
)
from app.services.svg import generate_not_playing_svg
from app.database import MongoDBConnectionManager
from app.scheduler.jobs.spotify import (
    poll_current_playback,
    poll_recently_played,
)
from app.services.plays import sync_all_missing_metadata
from app.services.rate_limiter import spotify_rate_limiter

router = APIRouter(prefix="/spotify", tags=["Spotify"])


@router.get("/authorize", summary="Get Spotify OAuth URL")
async def authorize(_: User = Depends(current_active_user)):
    """Protected endpoint that returns the Spotify authorization URL."""
    auth_manager = get_auth_manager()
    auth_url = auth_manager.get_authorize_url()
    return {"auth_url": auth_url}


@router.get("/callback", summary="Spotify OAuth callback")
async def callback(code: str):
    """OAuth callback endpoint. Stores token in Redis."""
    auth_manager = get_auth_manager()
    auth_manager.get_access_token(code)
    return {"message": "Authentication successful. You can now use /spotify/now-playing"}


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
async def manual_poll_current_playback(_: User = Depends(current_active_user)):
    """Manually trigger current playback poll."""
    result = await poll_current_playback()
    return result


@router.post("/poll/recently-played", summary="Manually poll recently played")
async def manual_poll_recently_played(_: User = Depends(current_active_user)):
    """Manually trigger recently played poll."""
    result = await poll_recently_played()
    return result


@router.post("/sync-metadata", summary="Sync all missing metadata")
async def manual_sync_metadata(_: User = Depends(current_active_user)):
    """Sync missing artists and albums from tracks collection."""
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        return {"status": "error", "reason": "not authenticated with Spotify"}

    sp = get_spotify_client()

    async with MongoDBConnectionManager() as db:
        sync_result = await sync_all_missing_metadata(db, sp)

    return {"status": "ok", **sync_result}


@router.get("/rate-limit-stats", summary="Get rate limiter stats")
async def rate_limit_stats(_: User = Depends(current_active_user)):
    """Get current Spotify API rate limiter statistics."""
    return spotify_rate_limiter.get_stats()
