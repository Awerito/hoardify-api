import json
from datetime import datetime, timezone

import redis
import spotipy
from spotipy.cache_handler import CacheHandler
from spotipy.oauth2 import SpotifyOAuth

from app.config import RedisConfig, SpotifyConfig

NOW_PLAYING_CACHE_KEY = "now_playing"


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


def get_recently_played(sp: spotipy.Spotify, limit: int = 50) -> list[dict]:
    """Fetch recently played tracks and transform to our schema."""
    response = sp.current_user_recently_played(limit=limit)
    plays = []
    for item in response.get("items", []):
        track = item["track"]
        plays.append(
            {
                "track_id": track["id"],
                "name": track["name"],
                "artists": [a["name"] for a in track["artists"]],
                "artist_ids": [a["id"] for a in track["artists"]],
                "album": track["album"]["name"],
                "album_art": (
                    track["album"]["images"][0]["url"]
                    if track["album"]["images"]
                    else None
                ),
                "duration_ms": track["duration_ms"],
                "played_at": item["played_at"],
            }
        )
    return plays


def get_current_playback(sp: spotipy.Spotify) -> dict | None:
    """Fetch current playback with device/context info for storage."""
    current = sp.current_playback()

    if not current or not current.get("item"):
        return None

    track = current["item"]
    progress_ms = current.get("progress_ms", 0)
    now = datetime.now(timezone.utc)
    played_at = datetime.fromtimestamp(
        (now.timestamp() * 1000 - progress_ms) / 1000, tz=timezone.utc
    )
    played_at_rounded = played_at.replace(second=0, microsecond=0)

    context = current.get("context")
    device = current.get("device")

    return {
        "play": {
            "track_id": track["id"],
            "name": track["name"],
            "artists": [a["name"] for a in track["artists"]],
            "artist_ids": [a["id"] for a in track["artists"]],
            "album": track["album"]["name"],
            "album_art": (
                track["album"]["images"][0]["url"]
                if track["album"]["images"]
                else None
            ),
            "duration_ms": track["duration_ms"],
            "played_at": played_at,
            "played_at_rounded": played_at_rounded,
            "device_name": device["name"] if device else None,
            "device_type": device["type"] if device else None,
            "context_type": context["type"] if context else None,
            "context_uri": context["uri"] if context else None,
            "shuffle_state": current.get("shuffle_state"),
        },
        "now_playing": {
            "is_playing": current.get("is_playing", False),
            "title": track["name"],
            "artist": ", ".join(a["name"] for a in track["artists"]),
            "album": track["album"]["name"],
            "album_art": (
                track["album"]["images"][0]["url"]
                if track["album"]["images"]
                else None
            ),
            "url": track["external_urls"]["spotify"],
            "progress_ms": progress_ms,
            "duration_ms": track["duration_ms"],
        },
    }


def cache_now_playing(redis_client: redis.Redis, data: dict | None) -> None:
    """Cache now playing data to Redis."""
    if data is None:
        redis_client.delete(NOW_PLAYING_CACHE_KEY)
    else:
        redis_client.set(NOW_PLAYING_CACHE_KEY, json.dumps(data), ex=120)


def get_cached_now_playing(redis_client: redis.Redis) -> dict | None:
    """Get cached now playing data from Redis."""
    data = redis_client.get(NOW_PLAYING_CACHE_KEY)
    if data:
        return json.loads(data)
    return None
