import base64
import urllib.request


def fetch_image_as_base64(url: str) -> str | None:
    """Download an image and convert it to base64."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = response.read()
            return base64.b64encode(data).decode("utf-8")
    except Exception:
        return None


def generate_now_playing_svg(
    title: str,
    artist: str,
    album_art_url: str | None = None,
    is_playing: bool = False,
) -> str:
    """Generate a terminal-style SVG with current track."""
    # Escape special XML characters
    title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    artist = artist.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Truncate if too long
    max_len = 30
    if len(title) > max_len:
        title = title[: max_len - 3] + "..."
    if len(artist) > max_len:
        artist = artist[: max_len - 3] + "..."

    status = "Now Playing" if is_playing else "Last Played"
    status_color = "#1DB954" if is_playing else "#6b7280"

    # Try to fetch album art
    album_art_b64 = None
    if album_art_url:
        album_art_b64 = fetch_image_as_base64(album_art_url)

    album_image_section = ""
    if album_art_b64:
        album_image_section = f"""
        <image
            x="15"
            y="35"
            width="60"
            height="60"
            href="data:image/jpeg;base64,{album_art_b64}"
            preserveAspectRatio="xMidYMid slice"
        />"""

    text_x = 85 if album_art_b64 else 15

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="400" height="110" viewBox="0 0 400 110">
  <rect width="400" height="110" rx="5" fill="#1a1a2e"/>
  <rect x="0" y="0" width="400" height="22" rx="5" fill="#16213e"/>
  <circle cx="12" cy="11" r="5" fill="#ff5f56"/>
  <circle cx="28" cy="11" r="5" fill="#ffbd2e"/>
  <circle cx="44" cy="11" r="5" fill="#27ca40"/>
  <text x="200" y="15" fill="#8892b0" font-family="monospace" font-size="11" text-anchor="middle">
    {status}
  </text>
  {album_image_section}
  <text x="{text_x}" y="58" fill="#ccd6f6" font-family="monospace" font-size="13" font-weight="bold">
    {title}
  </text>
  <text x="{text_x}" y="78" fill="#8892b0" font-family="monospace" font-size="11">
    {artist}
  </text>
  <circle cx="380" cy="55" r="8" fill="none" stroke="{status_color}" stroke-width="2"/>
  <polygon points="378,52 378,58 382,55" fill="{status_color}"/>
</svg>"""


def generate_not_playing_svg() -> str:
    """SVG for when no data is available."""
    return """<svg xmlns="http://www.w3.org/2000/svg" width="400" height="110" viewBox="0 0 400 110">
  <rect width="400" height="110" rx="5" fill="#1a1a2e"/>
  <rect x="0" y="0" width="400" height="22" rx="5" fill="#16213e"/>
  <circle cx="12" cy="11" r="5" fill="#ff5f56"/>
  <circle cx="28" cy="11" r="5" fill="#ffbd2e"/>
  <circle cx="44" cy="11" r="5" fill="#27ca40"/>
  <text x="200" y="15" fill="#8892b0" font-family="monospace" font-size="11" text-anchor="middle">
    Spotify
  </text>
  <text x="200" y="65" fill="#6b7280" font-family="monospace" font-size="13" text-anchor="middle">
    Nothing playing right now
  </text>
</svg>"""
