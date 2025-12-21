import json

import redis
import spotipy
from spotipy.cache_handler import CacheHandler
from spotipy.oauth2 import SpotifyOAuth

from app.config import RedisConfig, SpotifyConfig


class RedisCacheHandler(CacheHandler):
    """Cache handler that stores Spotify tokens in Redis."""

    def __init__(self, redis_client: redis.Redis, key: str = "spotify_token"):
        self.redis = redis_client
        self.key = key

    def get_cached_token(self) -> dict | None:
        token_json = self.redis.get(self.key)
        if token_json:
            return json.loads(token_json)
        return None

    def save_token_to_cache(self, token_info: dict) -> None:
        self.redis.set(self.key, json.dumps(token_info))


def get_redis_client() -> redis.Redis:
    return redis.from_url(RedisConfig.url)


def get_auth_manager() -> SpotifyOAuth:
    redis_client = get_redis_client()
    cache_handler = RedisCacheHandler(redis_client)
    return SpotifyOAuth(
        scope=" ".join(SpotifyConfig.scopes),
        cache_handler=cache_handler,
        open_browser=False,
    )


def get_spotify_client() -> spotipy.Spotify:
    return spotipy.Spotify(auth_manager=get_auth_manager())


def get_now_playing(sp: spotipy.Spotify) -> dict | None:
    """Get current playing track or last played."""
    current = sp.current_playback()

    if current and current.get("is_playing"):
        track = current["item"]
        return {
            "is_playing": True,
            "title": track["name"],
            "artist": ", ".join(a["name"] for a in track["artists"]),
            "album": track["album"]["name"],
            "album_art": (
                track["album"]["images"][0]["url"]
                if track["album"]["images"]
                else None
            ),
            "url": track["external_urls"]["spotify"],
            "progress_ms": current["progress_ms"],
            "duration_ms": track["duration_ms"],
        }

    # If nothing is playing, get last played
    recent = sp.current_user_recently_played(limit=1)
    if recent and recent["items"]:
        track = recent["items"][0]["track"]
        return {
            "is_playing": False,
            "title": track["name"],
            "artist": ", ".join(a["name"] for a in track["artists"]),
            "album": track["album"]["name"],
            "album_art": (
                track["album"]["images"][0]["url"]
                if track["album"]["images"]
                else None
            ),
            "url": track["external_urls"]["spotify"],
            "progress_ms": None,
            "duration_ms": track["duration_ms"],
        }

    return None
