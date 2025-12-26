from datetime import datetime

from app.services.cache import (
    cache_album_art,
    fetch_image_as_base64,
    get_cached_album_art,
    get_redis_client,
)


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
    """SVG for when nothing is playing."""
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


def generate_listening_grid_svg(
    plays_by_day_hour: dict[str, dict[int, dict]],
    cell_size: int = 12,
    gap: int = 2,
) -> str:
    """Generate a GitHub-style listening grid with album art.

    Args:
        plays_by_day_hour: Dict mapping date string (YYYY-MM-DD) to
                          dict mapping hour (0-23) to play data.
                          Dates/hours should already be in local timezone.
        cell_size: Size of each cell in pixels.
        gap: Gap between cells.

    Layout: Rows = days (oldest at top), Columns = 24 hours
    Each cell shows album art of last track played in that hour.
    """
    if not plays_by_day_hour:
        return generate_empty_grid_svg("No listening data")

    # Sort days (oldest first, newest at bottom like GitHub)
    sorted_days = sorted(plays_by_day_hour.keys())
    num_days = len(sorted_days)

    # Layout
    day_label_width = 45
    hour_label_height = 15
    title_height = 22
    padding = 8

    grid_width = 24 * (cell_size + gap) - gap
    grid_height = num_days * (cell_size + gap) - gap

    width = day_label_width + grid_width + padding * 2
    height = title_height + hour_label_height + grid_height + padding * 2

    # Calculate totals
    total_plays = sum(
        play.get("play_count", 1)
        for day_data in plays_by_day_hour.values()
        for play in day_data.values()
    )

    # Font
    font = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'  <rect width="{width}" height="{height}" rx="6" fill="#0d1117"/>',
        # Title
        f'  <text x="{padding}" y="{padding + 14}" fill="#e6edf3" font-family="{font}" font-size="12" font-weight="600">Listening Activity</text>',
        f'  <text x="{width - padding}" y="{padding + 14}" fill="#8b949e" font-family="{font}" font-size="10" text-anchor="end">{total_plays} plays</text>',
    ]

    # Hour labels (every 6 hours: 0, 6, 12, 18)
    for hour in [0, 6, 12, 18]:
        x = padding + day_label_width + hour * (cell_size + gap) + cell_size // 2
        y = title_height + padding + 10
        svg_parts.append(
            f'  <text x="{x}" y="{y}" fill="#8b949e" font-family="{font}" font-size="9" text-anchor="middle">{hour}h</text>'
        )

    # Redis client for album art cache
    redis_client = get_redis_client()

    # Grid
    grid_start_y = title_height + hour_label_height + padding

    for row_idx, day in enumerate(sorted_days):
        y = grid_start_y + row_idx * (cell_size + gap)
        day_data = plays_by_day_hour[day]

        # Day label (show weekday abbreviation)
        day_date = datetime.strptime(day, "%Y-%m-%d")
        weekday = day_date.strftime("%a")
        day_num = day_date.strftime("%d")

        svg_parts.append(
            f'  <text x="{padding + day_label_width - 5}" y="{y + cell_size - 2}" fill="#8b949e" font-family="{font}" font-size="9" text-anchor="end">{weekday} {day_num}</text>'
        )

        # Hour cells
        for hour in range(24):
            x = padding + day_label_width + hour * (cell_size + gap)
            play = day_data.get(hour)

            if play:
                track_name = play.get("name", "Unknown")
                track_name_escaped = (
                    track_name.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                )
                play_count = play.get("play_count", 1)
                tooltip = (
                    f"{day} {hour:02d}:00\n{track_name_escaped}\n({play_count} plays)"
                )

                # Try to get album art (Redis cache with 7 day TTL)
                album_art_url = play.get("album_art")
                album_art_b64 = None

                if album_art_url:
                    album_art_b64 = get_cached_album_art(redis_client, album_art_url)
                    if not album_art_b64:
                        album_art_b64 = fetch_image_as_base64(album_art_url)
                        if album_art_b64:
                            cache_album_art(redis_client, album_art_url, album_art_b64)

                if album_art_b64:
                    svg_parts.append(
                        f'  <image x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" '
                        f'href="data:image/jpeg;base64,{album_art_b64}" preserveAspectRatio="xMidYMid slice">'
                        f"<title>{tooltip}</title></image>"
                    )
                else:
                    # Fallback: Spotify green
                    svg_parts.append(
                        f'  <rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" '
                        f'rx="2" fill="#1DB954"><title>{tooltip}</title></rect>'
                    )
            else:
                # Empty cell
                tooltip = f"{day} {hour:02d}:00 - No plays"
                svg_parts.append(
                    f'  <rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" '
                    f'rx="2" fill="#161b22"><title>{tooltip}</title></rect>'
                )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def generate_empty_grid_svg(title: str = "Today's Listening") -> str:
    """SVG for when there are no plays."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="320" height="80" viewBox="0 0 320 80">
  <rect width="320" height="80" rx="6" fill="#0d1117"/>
  <text x="10" y="20" fill="#8b949e" font-family="system-ui, sans-serif" font-size="12" font-weight="600">{title}</text>
  <text x="160" y="52" fill="#6b7280" font-family="system-ui, sans-serif" font-size="11" text-anchor="middle">
    No plays yet
  </text>
</svg>"""
