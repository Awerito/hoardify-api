from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from app.auth import User, current_active_user
from app.services.spotify import (
    get_auth_manager,
    get_redis_client,
    get_cached_now_playing,
)
from app.services.svg import generate_now_playing_svg, generate_not_playing_svg
from app.scheduler.jobs.spotify import (
    poll_current_playback,
    poll_recently_played,
    sync_artists,
)

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
    data = get_cached_now_playing(redis_client)

    if not data:
        svg = generate_not_playing_svg()
    else:
        svg = generate_now_playing_svg(
            title=data["title"],
            artist=data["artist"],
            album_art_url=data["album_art"],
            is_playing=data["is_playing"],
        )

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


@router.post("/poll/sync-artists", summary="Manually sync artists")
async def manual_sync_artists(_: User = Depends(current_active_user)):
    """Manually trigger artist sync."""
    result = await sync_artists()
    return result
