"""Vertical 9:16 renderer: Ken-Burns images, stock clips, xfades, ducked music."""

from __future__ import annotations

from pathlib import Path

from studio.media import ffmpeg

W, H = 1080, 1920
FADE = 0.3
ENC = ["-c:v", "libx264", "-preset", "fast", "-crf", "19", "-profile:v", "high",
       "-level", "4.0", "-pix_fmt", "yuv420p", "-r", "30", "-video_track_timescale", "15360"]
TRANSITIONS = ["fade", "smoothleft", "fade", "smoothright"]


def _run(cmd: list) -> None:
    ffmpeg.run_cmd(cmd)


def _filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _image_size(path: Path) -> tuple[int, int]:
    return ffmpeg.image_size(path)


def _whoosh(path: Path) -> Path:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
          "-i", "anoisesrc=d=0.7:c=pink:r=44100:a=0.7",
          "-af", "highpass=f=250,lowpass=f=3500,afade=t=in:st=0:d=0.3,afade=t=out:st=0.3:d=0.4",
          "-ac", "2", str(path)])
    return path


def _image_segment(src: Path, index: int, duration: float, build_dir: Path) -> Path:
    out = build_dir / f"seg{index}.mp4"
    width, height = _image_size(src)
    frames = max(int(duration * 30), 2)
    zoom = f"1+0.08*on/{frames}" if index % 2 == 0 else f"1.08-0.08*on/{frames}"
    position = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    base = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30",
            "-t", f"{duration:.3f}", "-i", str(src)]
    if height / max(width, 1) >= 1.5:
        vf = (
            f"scale=2160:3840:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop=2160:3840,"
            f"zoompan=z='{zoom}':{position}:d=1:s={W}x{H}:fps=30,"
            "eq=brightness=-0.03:saturation=1.05,vignette=PI/7,format=yuv420p"
        )
        _run(base + ["-vf", vf, "-an", *ENC, str(out)])
    else:
        foreground_height = min(round(W * height / max(width, 1) / 2) * 2, H)
        filter_complex = (
            "[0:v]split=2[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            "gblur=sigma=40,eq=brightness=-0.22:saturation=0.9[bg];"
            f"[b]scale={W * 2}:-2:flags=lanczos,zoompan=z='{zoom}':{position}:d=1:"
            f"s={W}x{foreground_height}:fps=30[fg];"
            "[bg][fg]overlay=0:(H-h)/2,vignette=PI/7,format=yuv420p[v]"
        )
        _run(base + ["-filter_complex", filter_complex, "-map", "[v]", "-an", *ENC, str(out)])
    return out


def _clip_segment(src: Path, index: int, duration: float, build_dir: Path) -> Path:
    out = build_dir / f"seg{index}.mp4"
    scaled_w = int(W * 1.12) // 2 * 2
    scaled_h = int(H * 1.12) // 2 * 2
    progress = f"min(t/{duration:.3f},1)"
    x = f"(iw-ow)*{progress}" if index % 2 == 0 else f"(iw-ow)*(1-{progress})"
    vf = (
        f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={scaled_w}:{scaled_h},fps=30,"
        f"crop={W}:{H}:x='{x}':y='(ih-oh)/2',setsar=1,"
        "eq=brightness=-0.08:saturation=0.85,vignette=PI/6,format=yuv420p"
    )
    _run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1",
          "-i", str(src), "-t", f"{duration:.3f}", "-vf", vf, "-an", *ENC, str(out)])
    return out


def render(media, lens, cuts, voice, ass, total, out, music=None,
           music_vol: float = 0.45, sfx_vol: float = 0.15,
           work_dir: str | Path | None = None) -> Path:
    """Render the Short. ``lens`` must match ``total`` (voice track duration)."""
    out = Path(out)
    total_timeline = total + 0.6
    build_dir = Path(work_dir) if work_dir else out.parent
    parts: list[Path] = []
    for index, item in enumerate(media):
        duration = lens[index] + FADE
        source = Path(item["path"])
        parts.append(
            _image_segment(source, index, duration, build_dir)
            if item["type"] == "image"
            else _clip_segment(source, index, duration, build_dir)
        )

    chain, previous, accumulated = [], "[0:v]", 0.0
    for k in range(1, len(parts)):
        accumulated += lens[k - 1]
        label = f"[x{k}]"
        transition = TRANSITIONS[(k - 1) % len(TRANSITIONS)]
        chain.append(
            f"{previous}[{k}:v]xfade=transition={transition}:"
            f"duration={FADE}:offset={accumulated:.3f}{label}"
        )
        previous = label
    subtitles = f"subtitles=filename='{_filter_path(Path(ass))}'"
    filter_graph = ";".join(chain + [f"{previous}{subtitles}[vout]"]) + ";"

    inputs: list[str] = []
    for part in parts:
        inputs += ["-i", str(part)]
    inputs += ["-i", str(voice)]
    count = len(parts)
    index = count + 1
    norm = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
    audio_filters = [f"[{count}:a]{norm},apad=whole_dur={total_timeline:.3f}[va0]"]
    mix_inputs: list[str] = []
    if music and Path(music).exists():
        inputs += ["-stream_loop", "-1", "-t", f"{total_timeline + 1:.2f}", "-i", str(music)]
        audio_filters.append("[va0]asplit=2[va][key]")
        audio_filters.append(
            f"[{index}:a]{norm},loudnorm=I=-14:TP=-2:LRA=7,aresample=44100,"
            f"highpass=f=100,lowpass=f=10000,volume={music_vol},afade=t=in:st=0:d=1.0[mu]"
        )
        audio_filters.append(
            "[mu]asplit=2[mu1][mu2];[mu1][key]"
            "sidechaincompress=threshold=0.03:ratio=6:attack=12:release=450:makeup=1[duck]"
        )
        mix_inputs = ["[va]", "[duck]"]
        index += 1
    else:
        audio_filters[0] = (
            f"[{count}:a]{norm},apad=whole_dur={total_timeline:.3f}[va]"
        )
        mix_inputs = ["[va]"]

    if sfx_vol > 0 and cuts:
        whoosh = _whoosh(build_dir / "whoosh.wav")
        inputs += ["-i", str(whoosh)]
        transitions = len(cuts)
        if transitions > 1:
            audio_filters.append(
                f"[{index}:a]{norm},asplit={transitions}"
                + "".join(f"[w{i}]" for i in range(transitions))
            )
        else:
            audio_filters.append(f"[{index}:a]{norm}[w0]")
        for i, at in enumerate(cuts):
            milliseconds = int(at * 1000)
            audio_filters.append(
                f"[w{i}]adelay={milliseconds}|{milliseconds},volume={sfx_vol}[d{i}]"
            )
            mix_inputs.append(f"[d{i}]")

    fade = f"afade=t=out:st={max(total_timeline - 1.2, 0):.3f}:d=1.2"
    audio_filters.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0:"
        f"normalize=0,alimiter=limit=0.95,{fade}[aout]"
    )
    filter_graph += ";".join(audio_filters)

    _run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
          "-filter_complex", filter_graph,
          "-map", "[vout]", "-map", "[aout]", "-t", f"{total_timeline:.3f}", *ENC,
          "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
          "-movflags", "+faststart", str(out)])
    return out


__all__ = ["render", "W", "H"]
