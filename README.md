# Hoardify API

[![hoardify.grye.org](https://img.shields.io/badge/hoardify.grye.org-blue?style=flat)](https://hoardify.grye.org)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-yellow?style=flat&logo=buy-me-a-coffee)](https://buymeacoffee.com/awerito)

Personal Spotify listening history hoarding API. Tracks what you listen to and stores it for analytics.

## Stack

- **FastAPI** + **Motor** (async MongoDB)
- **APScheduler** for background polling jobs
- **spotipy** for Spotify API
- **Redis** for Spotify token cache

---

## Quickstart

```bash
git clone https://github.com/Awerito/hoardify-api.git
cd hoardify-api
uv sync
cp sample.env .env
# Edit .env with your credentials
uv run uvicorn app.main:app --reload
```

Docs: http://localhost:8000/docs

---

## Configuration

### Admin Password

Generate a bcrypt hash for your admin password:

```bash
python -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('your_password'))"
```

Add the hash to `.env`:

```env
ADMIN_PASSWORD_HASH=$2b$12$...your_hash_here...
```

### Environment Variables

```env
ENV=dev

# MongoDB
MONGO_URI=mongodb://user:password@localhost:27017/spotify_hoarding

# Auth
SECRET_KEY=change_this_to_a_secure_random_string
ADMIN_PASSWORD_HASH=your_bcrypt_hash

# CORS
CORS_ORIGINS=http://localhost:5173,http://localhost:8000

# Redis (Spotify token cache)
REDIS_URL=redis://localhost:6379/0

# Spotify OAuth
SPOTIPY_CLIENT_ID=your_client_id
SPOTIPY_CLIENT_SECRET=your_client_secret
SPOTIPY_REDIRECT_URI=http://localhost:8000/spotify/callback
```

---

## Project Structure

```
.
├── app
│   ├── database
│   │   ├── motor.py
│   │   └── utils.py
│   ├── routers
│   │   ├── auth/
│   │   ├── healthcheck/
│   │   └── spotify/
│   ├── scheduler
│   │   └── jobs/
│   │       └── spotify.py
│   ├── services
│   │   ├── plays.py
│   │   ├── spotify.py
│   │   └── svg.py
│   ├── auth.py
│   ├── config.py
│   └── main.py
├── Dockerfile
├── pyproject.toml
├── uv.lock
└── sample.env
```

---

## Endpoints

### Spotify

| Method | Path | Description |
|--------|------|-------------|
| GET | `/spotify/authorize` | Get Spotify OAuth URL (auth required) |
| GET | `/spotify/callback` | OAuth callback |
| GET | `/spotify/now-playing` | Current track from cache |
| GET | `/spotify/now-playing.svg` | Embeddable SVG widget |
| POST | `/spotify/poll/current-playback` | Manual poll trigger (auth required) |
| POST | `/spotify/poll/recently-played` | Manual poll trigger (auth required) |
| POST | `/spotify/sync-metadata` | Sync all missing artists/albums (auth required) |

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/token` | Get JWT token |

---

## Background Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| `poll_current_playback` | 1-2 sec (adaptive) | Polls current playback, detects track changes, updates listen counts |
| `poll_recently_played` | Every hour | Backfills plays log with exact timestamps |

---

## Collections

### `tracks`

Unique tracks with metadata and listen counts.

```json
{
  "track_id": "4EchqUKQ3qAQuRNKmeIpnf",
  "name": "The Kids Aren't Alright",
  "artists": ["The Offspring"],
  "artist_ids": ["5LfGQac0EIXyAN8aUwmNAQ"],
  "album": "Americana",
  "album_id": "4Hjqdhj5rh816i1dfcUEaM",
  "album_art": "https://i.scdn.co/image/...",
  "duration_ms": 180160,
  "listen_count": 42,
  "first_listened": "2025-12-01T10:30:00.000Z",
  "last_listened": "2025-12-25T15:45:00.000Z"
}
```

### `plays`

Log of each listen event (timestamps rounded to minute).

```json
{
  "track_id": "4EchqUKQ3qAQuRNKmeIpnf",
  "listened_at": "2025-12-21T00:36:00.000Z",
  "device_name": "pop-os",
  "device_type": "Computer",
  "context_type": "collection",
  "context_uri": "spotify:user:xxx:collection",
  "shuffle_state": true
}
```

### `artists`

```json
{
  "artist_id": "5LfGQac0EIXyAN8aUwmNAQ",
  "name": "The Offspring",
  "genres": ["punk rock", "alternative rock"],
  "popularity": 75,
  "image": "https://i.scdn.co/image/..."
}
```

### `albums`

```json
{
  "album_id": "4Hjqdhj5rh816i1dfcUEaM",
  "name": "Americana",
  "album_type": "album",
  "total_tracks": 14,
  "release_date": "1998-11-17",
  "label": "Round Hill Records",
  "popularity": 75,
  "image": "https://i.scdn.co/image/...",
  "artist_ids": ["5LfGQac0EIXyAN8aUwmNAQ"]
}
```

---

## Docker

```bash
docker build -t hoardify-api .
docker run --rm --env-file .env -p 8000:8000 hoardify-api
```

---

## License

[MIT](https://github.com/Awerito/hoardify-api/blob/master/LICENSE)
