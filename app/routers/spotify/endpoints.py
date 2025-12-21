from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from app.auth import User, current_active_user
from app.services.spotify import get_auth_manager, get_spotify_client, get_now_playing
from app.services.svg import generate_now_playing_svg, generate_not_playing_svg

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
    """Get currently playing track or last played."""
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        return JSONResponse(
            status_code=401,
            content={"error": "Not authenticated. Visit /spotify/login first."},
        )
    sp = get_spotify_client()
    data = get_now_playing(sp)
    if not data:
        return JSONResponse(
            status_code=200,
            content={"is_playing": False, "message": "Nothing playing"},
        )
    return data


@router.get("/now-playing.svg", summary="Embeddable SVG widget")
async def now_playing_svg():
    """Get an embeddable SVG widget showing current track."""
    auth_manager = get_auth_manager()
    token_info = auth_manager.get_cached_token()
    if not token_info:
        svg = generate_not_playing_svg()
        return Response(content=svg, media_type="image/svg+xml")

    sp = get_spotify_client()
    data = get_now_playing(sp)

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
