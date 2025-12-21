# Selfhoardify API

[![selfhoardify.grye.org](https://img.shields.io/badge/selfhoardify.grye.org-blue?style=flat)](https://selfhoardify.grye.org)
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
git clone https://github.com/Awerito/selfhoardify-api.git
cd selfhoardify-api
python -m venv env && source env/bin/activate
pip install -r requirements.txt
cp sample.env .env
# Edit .env with your credentials
uvicorn app.main:app --reload
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
├── requirements.txt
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
| POST | `/spotify/poll/sync-artists` | Manual artist sync (auth required) |

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/token` | Get JWT token |

---

## Background Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| `poll_current_playback` | Every 30 sec | Polls current playback, saves to DB, caches to Redis |
| `poll_recently_played` | Every hour | Fetches last 50 tracks with exact timestamps |
| `sync_artists` | 6 AM & 6 PM | Syncs artist genres for new artists |

---

## Collections

### `plays`

```json
{
  "track_id": "4EchqUKQ3qAQuRNKmeIpnf",
  "name": "The Kids Aren't Alright",
  "artists": ["The Offspring"],
  "artist_ids": ["5LfGQac0EIXyAN8aUwmNAQ"],
  "album": "Americana",
  "album_art": "https://i.scdn.co/image/...",
  "duration_ms": 180160,
  "played_at": "2025-12-21T00:36:49.833Z",
  "device_name": "pop-os",
  "device_type": "Computer",
  "context_type": "collection",
  "context_uri": "spotify:user:xxx:collection"
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

---

## Docker

```bash
docker build -t selfhoardify-api .
docker run --rm --env-file .env -p 8000:8000 selfhoardify-api
```

---

## License

[MIT](https://github.com/Awerito/selfhoardify-api/blob/master/LICENSE)
