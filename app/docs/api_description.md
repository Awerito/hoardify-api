Personal Spotify listening history hoarding API.

Polls your Spotify playback, stores tracks in MongoDB, and provides analytics.

---

<details>
<summary>Click to expand</summary>

## Auth

Get a JWT token via `POST /token` with username `admin` and your configured password.

Protected endpoints require `Authorization: Bearer <token>` header.

---

## Spotify Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /spotify/authorize` | Returns Spotify OAuth URL (protected) |
| `GET /spotify/callback` | OAuth callback, stores token in Redis |
| `GET /spotify/now-playing` | Current track from Redis cache |
| `GET /spotify/now-playing.svg` | Embeddable SVG widget |
| `POST /spotify/poll/*` | Manual job triggers (protected) |

---

## Background Jobs

| Job | Schedule |
|-----|----------|
| `poll_current_playback` | Every 30 sec |
| `poll_recently_played` | Every hour |
| `sync_artists` | 6 AM & 6 PM |

---

## Collections

- **plays**: Track plays with device/context info
- **artists**: Artist metadata with genres

</details>
