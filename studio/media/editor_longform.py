"""Horizontal 16:9 renderer: slow Ken-Burns, xfades, ducked score."""

from __future__ import annotations

from pathlib import Path

from studio.media import ffmpeg

W, H = 1920, 1080
FADE = 0.4
ENC = ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-profile:v", "high",
       "-level", "4.1", "-pix_fmt", "yuv420p", "-r", "30", "-video_track_timescale", "15360"]
TRANSITIONS = ["fade", "smoothleft", "fade", "circlecrop", "fade"]


def _run(cmd: list) -> None:
    ffmpeg.run_cmd(cmd)


def _filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _segment(src: Path, index: int, duration: float, is_image: bool, build_dir: Path) -> Path:
    out = build_dir / f"lseg{index}.mp4"
    if is_image:
        frames = max(int(duration * 30), 2)
        zoom = f"1+0.05*on/{frames}" if index % 2 == 0 else f"1.05-0.05*on/{frames}"
        position = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        vf = (
            f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={W * 2}:{H * 2},"
            f"zoompan=z='{zoom}':{position}:d=1:s={W}x{H}:fps=30,"
            "eq=brightness=-0.03:saturation=1.05,format=yuv420p"
        )
        _run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30",
              "-t", f"{duration:.3f}", "-i", str(src), "-vf", vf, "-an", *ENC, str(out)])
    else:
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={W}:{H},fps=30,setsar=1,eq=brightness=-0.05:saturation=0.9,format=yuv420p"
        )
        _run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1",
              "-i", str(src), "-t", f"{duration:.3f}", "-vf", vf, "-an", *ENC, str(out)])
    return out


def render(sections, voice, ass, total, out, music=None, music_vol: float = 0.35,
           work_dir: str | Path | None = None) -> Path:
    out = Path(out)
    total_timeline = total + 1.5
    build_dir = Path(work_dir) if work_dir else out.parent

    valid: list[tuple[int, Path, float]] = []
    for index, section in enumerate(sections):
        media = section.get("_media", {})
        source = Path(media["path"]) if media.get("path") else None
        if source and source.exists():
            duration = section.get("_dur", 10.0) + FADE
            segment = _segment(
                source, index, duration, media.get("type") == "image", build_dir
            )
            valid.append((index, segment, section.get("_dur", 10.0)))
    if not valid:
        raise RuntimeError("No visual segments to render")

    subtitles = f"subtitles=filename='{_filter_path(Path(ass))}'"
    if len(valid) == 1:
        _, segment, _ = valid[0]
        filter_graph = f"{subtitles}[vout];"
        inputs: list[str] = ["-i", str(segment), "-i", str(voice)]
    else:
        offsets, accumulated = [], 0.0
        for j in range(len(valid) - 1):
            accumulated += valid[j][2]
            offsets.append(accumulated)
        chain, previous = [], "[0:v]"
        for k, offset in enumerate(offsets):
            label = f"[x{k}]"
            transition = TRANSITIONS[k % len(TRANSITIONS)]
            chain.append(
                f"{previous}[{k + 1}:v]xfade=transition={transition}:"
                f"duration={FADE}:offset={offset:.3f}{label}"
            )
            previous = label
        filter_graph = ";".join(chain + [f"{previous}{subtitles}[vout]"]) + ";"
        inputs = []
        for _, segment_path, _ in valid:
            inputs += ["-i", str(segment_path)]
        inputs += ["-i", str(voice)]

    count = len(valid)
    norm = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
    audio_filters = [f"[{count}:a]{norm},apad=whole_dur={total_timeline:.3f}[va]"]
    mix_inputs = ["[va]"]
    index = count + 1
    if music and Path(music).exists():
        inputs += ["-stream_loop", "-1", "-t", f"{total_timeline + 1:.2f}", "-i", str(music)]
        audio_filters[0] = (
            f"[{count}:a]{norm},apad=whole_dur={total_timeline:.3f}[va0];"
            "[va0]asplit=2[va][key]"
        )
        audio_filters.append(
            f"[{index}:a]{norm},loudnorm=I=-14:TP=-2:LRA=7,aresample=44100,"
            f"highpass=f=100,lowpass=f=10000,volume={music_vol},afade=t=in:st=0:d=1.5[mu]"
        )
        audio_filters.append(
            "[mu]asplit=2[mu1][mu2];[mu1][key]"
            "sidechaincompress=threshold=0.03:ratio=5:attack=15:release=600:makeup=1[duck]"
        )
        mix_inputs = ["[va]", "[duck]"]

    fade = f"afade=t=out:st={max(total_timeline - 2.0, 0):.3f}:d=2.0"
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
