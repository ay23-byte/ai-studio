"""Generate a YouTube thumbnail (1280x720) from the first AI image + title."""

from __future__ import annotations

from pathlib import Path

from studio import config
from studio.media import ffmpeg

FONT_BOLD = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"


def make_thumbnail(
    image_path: Path | None,
    title: str,
    out: str | Path,
    channel: str | None = None,
) -> Path:
    """Overlay a bold title on the image, sized for YouTube thumbnails."""
    out = Path(out)
    channel = channel or config.CHANNEL_NAME
    title_clean = title[:60].replace("'", r"\'").replace(":", " -")
    channel_clean = channel.replace("'", r"\'")

    draw_title = (
        f"drawtext=fontfile={FONT_BOLD}:text='{title_clean}':"
        "fontcolor=white:fontsize=56:borderw=4:bordercolor=black:"
        "x=(w-text_w)/2:y=h*0.62:line_spacing=12"
    )
    draw_channel = (
        f"drawtext=fontfile={FONT_REGULAR}:text='{channel_clean}':"
        "fontcolor=0xFFD700:fontsize=34:borderw=3:bordercolor=black:"
        "x=(w-text_w)/2:y=h*0.85"
    )
    vf = (
        "scale=1280:720:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=1280:720,eq=brightness=-0.12:saturation=1.1,"
        f"{draw_title},{draw_channel}"
    )

    if image_path and Path(image_path).is_file():
        ffmpeg.run(["-loop", "1", "-i", image_path, "-vf", vf, "-frames:v", "1", out])
    else:
        ffmpeg.run(["-f", "lavfi", "-i", "color=c=0x0a1a3a:s=1280x720",
                    "-vf", vf, "-frames:v", "1", out])
    return out


__all__ = ["make_thumbnail"]
