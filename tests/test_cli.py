"""CLI surface and diagnostics."""

from __future__ import annotations

import pytest

from studio.cli import build_parser, main
from tests.conftest import requires_ffmpeg


def test_parser_defaults():
    args = build_parser().parse_args(["shorts", "Inflation kya hai"])
    assert args.command == "shorts"
    assert args.topic == "Inflation kya hai"
    assert args.profile is None
    assert args.engine is None


def test_parser_accepts_voice_flags():
    args = build_parser().parse_args(
        ["long", "MF", "--profile", "documentary", "--engine", "chatterbox",
         "--reference", "ref.wav", "--minutes", "9"]
    )
    assert args.profile == "documentary"
    assert args.engine == "chatterbox"
    assert args.minutes == 9


def test_help_exits_cleanly():
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


def test_no_command_shows_help(capsys):
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_doctor_reports_engines(capsys):
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "voice engines" in output
    assert "chatterbox" in output
    assert "ffmpeg" in output


def test_doctor_reports_hardware(capsys):
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "hardware" in output
    assert "cpu" in output
    assert "device=" in output


def test_qa_allow_silence_flag():
    args = build_parser().parse_args(["qa", "video.mp4", "--allow-silence"])
    assert args.allow_silence is True
    assert build_parser().parse_args(["qa", "video.mp4"]).allow_silence is False


def test_device_flag_is_plumbed():
    args = build_parser().parse_args(["shorts", "x", "--device", "cpu"])
    assert args.device == "cpu"
    args = build_parser().parse_args(["long", "x", "--device", "cuda"])
    assert args.device == "cuda"
    assert build_parser().parse_args(["voice", "hi"]).device is None


@requires_ffmpeg
def test_bench_reports_engine_speed(temp_config, capsys):
    assert main(["bench", "--engine", "silent", "--profile", "fast"]) == 0
    output = capsys.readouterr().out
    assert "realtime x" in output
    assert "est. Short" in output


@requires_ffmpeg
def test_voice_command_writes_sample(temp_config):
    out = temp_config / "sample.wav"
    code = main(["voice", "Namaste doston, aaj inflation samjhenge.",
                 "--engine", "silent", "--profile", "fast", "-o", str(out)])
    assert code == 0
    assert out.is_file() and out.stat().st_size > 1000


def test_command_errors_return_nonzero(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("synthesis exploded")

    monkeypatch.setattr("studio.cli.preview", boom)
    assert main(["voice", "hello", "--engine", "silent"]) == 1
