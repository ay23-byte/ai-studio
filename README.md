# AI Studio

[![verify](https://github.com/ay23-byte/ai-studio/actions/workflows/verify.yml/badge.svg?branch=main)](https://github.com/ay23-byte/ai-studio/actions/workflows/verify.yml)
[![make-shorts](https://github.com/ay23-byte/ai-studio/actions/workflows/make-shorts.yml/badge.svg?branch=main)](https://github.com/ay23-byte/ai-studio/actions/workflows/make-shorts.yml)

An automated faceless video studio for Hindi/Hinglish explainer channels:
**script → human-sounding voice → visuals → burned captions → YouTube**.

Version 2.0 rebuilds the project as a proper `studio/` package and replaces the
robotic edge-tts narration with a pluggable voice layer built around
**[Chatterbox](https://github.com/resemble-ai/chatterbox)** (Resemble AI's
open-source TTS), plus a pacing engine that makes the delivery sound like a
person talking — including a deliberately **fast, Shorts-ready profile**.

```
python run.py demo                     # build a Short from the built-in demo script
python run.py shorts "Inflation kya hai" --profile fast
python run.py long   "Mutual funds" --minutes 7 --profile natural
```

---

## 1. What changed in 2.0

| Area | Before | Now |
| --- | --- | --- |
| Layout | flat files at repo root importing `core.*` (broken) | `studio/` package with `media/`, `voice/`, `pipeline/`, `publishing/`; thin `run.py` shims |
| Voice | edge-tts only, fixed prosody | Chatterbox (local or remote HTTP), edge-tts fallback, pluggable engines + `silent` dry-run engine |
| Pacing | one rate per sentence | punctuation-aware pauses, jittered tempo, emphasis, breaths, silence trimming, broadcast loudness |
| Captions | evenly guessed timings | exact per-sentence timings from the synthesized audio |
| Visuals | hard failure when APIs were down | AI image → stock clip → local gradient placeholder |
| Ops | DB committed on every run | DB uploaded as artifact, topics progress committed |
| Quality | no tests, no lint | 130+ tests, ruff, CI matrix, schema validation, retry layer, QA gate |
| Operations | DB committed on every run | atomic renders, cached DB, watchdog, pinned actions and constraints |

---

## 2. Project structure

```
ai-studio/
├── studio/
│   ├── config.py              environment + paths (no import side effects)
│   ├── logs.py                one logging facade
│   ├── db.py                  SQLite jobs (lazy schema)
│   ├── script_engine.py       Gemini scripts + SEO
│   ├── notify.py              Telegram alerts
│   ├── resilience.py          retry/backoff for network + model calls
│   ├── validation.py          script schema checks + normalisation
│   ├── qa.py                  publish-readiness gate (silence, duration, streams)
│   ├── artifacts.py           atomic renders, timestamped filenames
│   ├── hardware.py            CPU/GPU detection + Iris Xe guidance
│   ├── cli.py                 `run.py` implementation
│   ├── daily.py               scheduled runner (`run_daily.py`)
│   ├── content/               built-in demo scripts
│   ├── media/
│   │   ├── ffmpeg.py          binary resolution, duration, image size, decode
│   │   ├── images.py          Cloudflare/Pollinations/Pixabay + placeholder
│   │   ├── editor_shorts.py   9:16 renderer
│   │   ├── editor_longform.py 16:9 renderer
│   │   └── thumbnails.py      1280×720 thumbnails
│   ├── voice/
│   │   ├── types.py           PacingProfile presets, Utterance, VoiceTrack
│   │   ├── humanize.py        text normalisation + pause/tempo planning
│   │   ├── assemble.py        synthesize → trim → concat → master → timings
│   │   └── engines/
│   │       ├── chatterbox.py        local Chatterbox (incl. Hindi pack)
│   │       ├── chatterbox_server.py remote Chatterbox HTTP API
│   │       ├── edge.py              free fallback
│   │       └── silent.py            timed silence for dry runs/tests
│   ├── pipeline/              captions.py, shorts.py, longform.py
│   └── publishing/youtube.py  upload, playlists, comments
├── tools/preview_voice.py     A/B voice profiles
├── tests/                     unit + opt-in end-to-end render tests
├── assets/{music,clips,voices}/
├── .github/workflows/         verify, make-shorts, make-longform, watchdog, audit
├── run.py  run_daily.py       compatibility entry points
├── requirements*.txt  constraints.txt
└── pyproject.toml
```

Everything is importable as a library:

```python
from studio.pipeline import build_shorts
from studio.voice import synthesize, SpeechChunk

track = synthesize(
    [SpeechChunk("Inflation kya hai? Chalo simple example se samjhein.", "scene0")],
    build_dir="build/demo", language="hindi",
    engine="chatterbox", profile="fast",
)
print(track.duration, track.spans)   # exact spans for cuts + captions
```

---

## 3. Quick start

**No terminal?** Tests, renders and publishing can all be triggered from the
GitHub **Actions** tab — see [`docs/GITHUB_ONLY.md`](docs/GITHUB_ONLY.md).

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -r requirements.txt      # light: scripts, images, upload, edge-tts
cp .env.example .env                 # fill in keys later

sudo apt install ffmpeg fonts-noto-core fonts-noto-devanagari   # macOS: brew install ffmpeg
# or, without root: pip install imageio-ffmpeg

python run.py doctor                 # checks ffmpeg, engines, keys
python run.py voice "Namaste, yeh aawaz kaisi lagi?" --engine edge
```

A **fully offline** smoke test (no keys, no network, silent audio, placeholder
visuals) proves the whole render path:

```bash
STUDIO_OFFLINE=1 python run.py demo --engine silent
```

---

## 4. Hardware: normal laptops, Intel Iris Xe, CPU-only

Two commands tell you what this machine can actually do:

```bash
python run.py doctor    # CPU / GPU / RAM / torch / engine availability + advice
python run.py bench     # real synthesis speed, extrapolated to Short and long-form
```

**The honest bit about integrated graphics.** Chatterbox is a PyTorch model with
CUDA, Apple-MPS and (with Intel extensions) XPU paths. An **Intel Iris Xe** has
no supported acceleration path, so narration runs on the **CPU**; the iGPU only
helps with video decode/playback. That is perfectly usable for a daily Short and
slow for a 7-minute video:

| Setup | Engine | 30 s Short | 7 min long-form |
| --- | --- | --- | --- |
| Iris Xe laptop, multilingual 500M | `chatterbox` (CPU) | ~2–5 min | ~25–50 min |
| Iris Xe laptop, nano 110M (English) | `chatterbox` (CPU) | <1 min | ~5–8 min |
| Laptop, no model | `edge` | seconds | ~1 min |
| Free/cheap GPU box (Colab, Kaggle, RunPod) | `chatterbox-http` | ~30 s–2 min | ~3–8 min |

These are typical ranges, not promises — run `bench` for your own numbers.

### 4.1 Recommended setup for a laptop

**A. Best Hindi voice, laptop only (slow but unattended-friendly)**

```bash
pip install -r requirements-voice.txt
export VOICE_ENGINE=chatterbox CHATTERBOX_DEVICE=cpu
export CHATTERBOX_MODEL=multilingual
export CHATTERBOX_THREADS=4     # leave cores for ffmpeg; 0 = all cores
export VOICE_PROFILE=fast
python run.py shorts "Inflation kya hai" --profile fast
```

Schedule Shorts overnight or via GitHub Actions; do long-form when the laptop is
plugged in. The pipeline caches each sentence, so a re-render after a visual
change is nearly free.

**B. Fastest good Hindi voice — borrow a GPU**

Run any Chatterbox HTTP server (e.g. `chatterbox-tts-api`, port 4123) on Colab,
Kaggle, a gaming PC or a cheap cloud GPU, then point the laptop at it:

```bash
export VOICE_ENGINE=chatterbox-http
export CHATTERBOX_API_URL=http://<gpu-host>:4123
```

Nothing else changes: same profiles, same pacing, same captions.

**C. Zero-install fallback**

```bash
export VOICE_ENGINE=edge   # seconds per video, less human
```

### 4.2 Laptop tuning knobs

| Variable | Why |
| --- | --- |
| `CHATTERBOX_THREADS=4` | bounds PyTorch intra-op threads so ffmpeg still gets CPU |
| `CHATTERBOX_MODEL=nano` | 110M English-only model, ~3× faster than realtime on 8 cores |
| `VOICE_PROFILE=fast` | shorter gaps + tempo, no extra model cost |
| `VOICE_SYNTH_ATTEMPTS=3` | automatic retry per sentence |
| `STUDIO_OFFLINE=1` | skip image APIs (uses gradient placeholders) for quick tests |
| `CHATTERBOX_IPEX=1` | only if `intel-extension-for-pytorch` is installed; stays fp32 for stability |

Keep ~4 GB RAM free while the multilingual model runs; close other browser tabs
during a build. On a 2-core machine expect the long-form estimate to be painful —
that is exactly what `bench` is for.

## 5. Chatterbox: the human voice

Chatterbox is a 0.5B-parameter open TTS model with zero-shot voice cloning and
two expressive knobs:

* **`exaggeration`** — emotional intensity (`0.25` calm → `1.5+` dramatic)
* **`cfg_weight`** — pacing/conditioning weight (`~0.3` = brisk, `0.7+` = deliberate)

The multilingual checkpoint speaks **Hindi (`language_id="hi"`)** along with 22
other languages; there is also a dedicated Hindi language pack.

> Upstream note: Resemble AI archived the repo in August 2026 ("retired
> research"). It is MIT-licensed, still installable, and runs entirely offline —
> pin `chatterbox-tts` in `requirements-voice.txt` so a future release cannot
> break you.

### 4.1 Option A — local model (GPU recommended)

```bash
pip install -r requirements-voice.txt      # chatterbox-tts + torch (~4 GB)

export VOICE_ENGINE=chatterbox
export CHATTERBOX_MODEL=multilingual       # English-only: english | turbo | nano
export CHATTERBOX_DEVICE=cuda              # cpu | mps | cuda
export CHATTERBOX_T3=v3                    # latest multilingual checkpoint

python run.py doctor                       # chatterbox should now be ✓
python tools/preview_voice.py              # writes output/voice_samples/*.wav
```

Weights download from Hugging Face on the first sentence. On CPU it works but is
several times slower than realtime — fine for one video, painful for a daily cron.

### 4.2 Option B — remote GPU server (best for GitHub Actions)

Run any Chatterbox HTTP server (for example the popular `chatterbox-tts-api`,
default port `4123`) on a GPU box, then point the studio at it:

```bash
export VOICE_ENGINE=chatterbox-http
export CHATTERBOX_API_URL=http://gpu-box:4123
# export CHATTERBOX_API_TOKEN=...          # optional bearer token
```

The remote engine posts `{input, exaggeration, cfg_weight, language_id}` to
`/v1/audio/speech` and, when a reference clip is set, uploads it to
`/v1/audio/speech/upload`. In CI set `CHATTERBOX_API_URL` as a repository secret.

### 4.3 Option C — edge-tts fallback

No GPU and no server? `VOICE_ENGINE=edge` (or leave `auto`) keeps working with
the same pacing layer, just a less human timbre.

### 4.4 Cloning a voice

Record 10–20 s (mono WAV, clean, same language you narrate) and point
`CHATTERBOX_REF` at it:

```bash
export CHATTERBOX_REF=assets/voices/reference.wav
```

Rules of thumb (from the upstream guide):

* match the reference language to `language_id`, or the accent leaks;
* a **brisk** reference + `cfg_weight≈0.3` gives the best Shorts pacing;
* a warm/slow reference suits `VOICE_PROFILE=documentary`.

For the dedicated Hindi pack, ship the checkpoint folder and use
`CHATTERBOX_CKPT_DIR=assets/models/chatterbox-hi` (loaded via `from_local`).

---

## 6. How the humanisation works

`studio/voice/humanize.py` + `assemble.py` do the work so every engine sounds
alive:

1. **Normalise** — strip markdown, expand ₹/$/% into spoken words, spell digits
   in Hindi or English (`500` → "पाँच सौ"), keep paragraph breaks.
2. **Split** — danda/`.`/`?`/`!`/ellipses, without breaking "Dr.", "Rs." or decimals.
3. **Plan pauses** — punctuation- and length-aware, ±18–25 % jitter, longer gap at
   paragraph breaks. Clipped Shorts lines get shorter gaps than long sentences.
4. **Plan tempo** — each sentence gets a ±3–5 % tempo offset; the profile adds a
   pitch-safe `atempo` on top (fast = ×1.08, energetic = ×1.12).
5. **Emphasise** — questions, exclamations and very short lines get an
   `exaggeration` boost for Chatterbox.
6. **Breathe** — optionally mixes a short band-passed breath into natural gaps
   (12 % volume, so it reads as an intake, not a hiss).
7. **Clean** — trims model silence, micro-fades edges (no clicks), concatenates,
   then high-pass, gentle compression and `loudnorm I=-16 LUFS`.
8. **Time** — returns per-sentence timings and per-scene spans; captions and cuts
   use these, so text, voice and visuals stay locked.

### Pacing profiles

| Profile | Tempo | Sentence gap | Chatterbox `cfg` / `exagg` | Use for |
| --- | --- | --- | --- | --- |
| `natural` | ×1.00 | 0.30 s | 0.50 / 0.50 | long-form default |
| `fast` | ×1.08 | 0.20 s | 0.30 / 0.60 | **Shorts default** |
| `energetic` | ×1.12 | 0.18 s | 0.35 / 0.75 | high-retention hooks |
| `documentary` | ×0.97 | 0.38 s | 0.55 / 0.45 | calm explainers |

Measured on a five-sentence Hinglish passage the same text renders ~26 % faster
in `fast` than in `documentary` before any engine speed-up.

Pick one with `VOICE_PROFILE=fast` or `--profile fast`; audition them all:

```bash
python tools/preview_voice.py --engine chatterbox --reference assets/voices/reference.wav
```

---

## 7. CLI

| Command | What it does |
| --- | --- |
| `python run.py doctor` | environment, ffmpeg, engines, credentials, topics |
| `python run.py shorts "topic" [--category finance] [--profile fast] [--engine auto]` | generate script → render Short |
| `python run.py long "topic" --minutes 7 [--profile natural]` | long-form video |
| `python run.py voice "text" -o out.wav [--profile fast] [--device cpu]` | voice sample only |
| `python run.py bench [--engine …] [--device …]` | measure real synthesis speed on this machine |
| `python run.py qa output/<file>.mp4 [--kind shorts] [--expected 32.5]` | publish-readiness report |
| `python run.py demo [--format shorts\|long]` | built-in script, no Gemini |
| `python run.py list` | recent jobs |
| `python run.py upload --id 3` | upload a built video (title, tags, playlist, comment) |
| `python run_daily.py --format shorts [--engine …] [--profile …]` | next topic from `topics.json` |
| `python run_daily.py --upload-latest` | publish newest unpublished build |

`python -m studio …` is equivalent to `python run.py …`.

---

## 8. Configuration

All variables are optional; see `.env.example` for the annotated list.

| Group | Variables |
| --- | --- |
| Scripts | `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS` (model ids are retired by Google; fallbacks keep builds alive) |
| Images | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `PIXABAY_API_KEY`, `POLLINATIONS_GAP`, `STUDIO_OFFLINE` |
| Voice | `VOICE_ENGINE`, `VOICE_PROFILE`, `CHATTERBOX_MODEL`, `CHATTERBOX_DEVICE`, `CHATTERBOX_T3`, `CHATTERBOX_CKPT_DIR`, `CHATTERBOX_REF`, `CHATTERBOX_API_URL`, `CHATTERBOX_API_TOKEN`, `CHATTERBOX_TEMPERATURE`, `CHATTERBOX_REPETITION_PENALTY` |
| Fallback voice | `VOICE_HINDI`, `VOICE_ENGLISH`, `VOICE_FEMALE` |
| Channel | `CHANNEL_NAME`, `PRIVACY`, `PUBLISH_AT_IST` |
| YouTube | `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` |
| Alerts | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| CPU tuning | `CHATTERBOX_THREADS`, `CHATTERBOX_IPEX`, `STUDIO_SKIP_TORCH_PROBE` |
| Reliability | `VOICE_SYNTH_ATTEMPTS`, `VOICE_RETRY_DELAY`, `SKIP_QA`, `STUDIO_LOG_FORMAT`, `STUDIO_RUN_ID` |
| Paths | `AI_STUDIO_HOME`, `AI_STUDIO_OUTPUT_DIR`, `AI_STUDIO_ASSETS_DIR` |

---

## 9. Tests and CI

```bash
pip install -r requirements-dev.txt
ruff check studio tests tools
pytest -q                              # 174 tests, ~6 s
STUDIO_SLOW_TESTS=1 pytest   # + real ffmpeg render, ~27 s
```

The suite covers sentence splitting, Hindi/English number spelling, pause and
tempo planning, the Chatterbox adapter contract (language id, exaggeration,
cfg weight, voice reference, older-API fallbacks) using a faked model, the
remote-server payload, caption alignment, DB/config behaviour and the package
layout. `tests/test_pipeline_slow.py` renders a real MP4 with the silent engine.

`verify.yml` is the single end-to-end check: workflow linting, Python linting,
the unit suite on Python 3.10/3.11/3.12, a real Shorts render, a real long-form
render, the QA gate, the hardware report and the voice benchmark — with the MP4s,
WAVs and logs attached as artifacts and summarised on the run page. Push and
pull requests trigger it; it can also be dispatched by hand with an `engine`
choice. `lock-check.yml` audits the pinned dependencies weekly, `watchdog.yml`
alerts when the channel goes quiet, and `make-shorts.yml` / `make-longform.yml`
are the production builders. Browser-only instructions:
[`docs/GITHUB_ONLY.md`](docs/GITHUB_ONLY.md).

---

## 10. Publishing

1. Create an OAuth client (Desktop) in Google Cloud, enable *YouTube Data API v3*.
2. Authorise at minimum with `https://www.googleapis.com/auth/youtube.upload`
   to upload videos. The broader `https://www.googleapis.com/auth/youtube` scope
   also enables optional processing-status reads, playlist management and
   comments. Those extras are best-effort; a read-scope failure after YouTube
   accepts an upload no longer fails the job. OAuth grants cannot be broadened
   by code; re-consent with the same client only if you want those extras.
3. Put `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` in `.env` or
   repository secrets.
4. `PRIVACY=private` plus `PUBLISH_AT_IST=19:00` schedules the premiere; leave
   `PUBLISH_AT_IST` empty to publish immediately at `PRIVACY`.
5. Uploads are flagged `containsSyntheticMedia` — keep that honest.

### Fixing `invalid_grant` during upload

`invalid_grant` is returned by Google's token endpoint before YouTube receives a
video. The refresh token is revoked/expired, or it does not match the configured
OAuth client; retrying the same token cannot repair it. Re-authorise the same
YouTube channel with the same OAuth client and at least the
`https://www.googleapis.com/auth/youtube.upload` scope (full `youtube` scope is
optional), then replace the repository's
**Actions secret** `YT_REFRESH_TOKEN` under **Settings → Secrets and variables
→ Actions**. If the OAuth client was rotated, update `YT_CLIENT_ID` and
`YT_CLIENT_SECRET` to the matching pair as well. For an External OAuth consent
screen left in **Testing**, Google refresh tokens expire after 7 days; publish
the consent screen (or expect to re-authorise and rotate the secret).

An `invalid_grant` occurs before YouTube receives the video, so that job remains
queued. A separate read-scope failure while checking processing can happen
**after** YouTube accepted an upload. The returned video ID is saved first; the
status poll is optional, and the job is still reported as uploaded if that poll
is unavailable. Verify the video in YouTube Studio and do not upload it again.

---

## 11. Production checklist

What the repository already enforces for you:

| Concern | Implementation |
| --- | --- |
| Malformed LLM output | `studio/validation.py` normalises scenes/sections and raises before any media is generated |
| Transient Gemini/TTS/image errors | `studio/resilience.py` exponential backoff on 429/5xx/timeouts and per-sentence retries |
| Half-written videos | `studio/artifacts.py` writes to a temp file and renames atomically |
| Silent or corrupt uploads | `studio/qa.py` blocks the upload unless streams, duration, orientation and audio level pass |
| State between runs | SQLite restored/saved with `actions/cache`, `topics.json` committed by the bot |
| Missed daily run | `watchdog.yml` fails and alerts if nothing was published in 26 h |
| Reproducible installs | `constraints.txt`, weekly `pip-audit` workflow, GitHub Actions pinned to commit SHAs |
| Debuggable logs | `STUDIO_LOG_FORMAT=json` with a `STUDIO_RUN_ID`, render artifacts kept 14 days |

Checks worth doing after changing engine, profile or channel:

```bash
python run.py doctor                 # hardware + engines + credentials
python run.py voice "test line" -o /tmp/t.wav --profile fast
python run.py qa output/<file>.mp4   # pass/fail report
```

Operator duties that stay manual:

* review `topics.json` and set `approved: false` on anything off-brand;
* keep the YouTube refresh token and Telegram bot alive (watchdog catches silence);
* keep a licensed music folder in `assets/music` and note each track's licence;
* watch the YouTube quota — one upload costs ~1600 of the 10 000 daily units;
* spot-check one video after upgrading models or changing voice references.

## 12. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No usable voice engine found` | `pip install edge-tts` for a quick start, or `pip install -r requirements-voice.txt`, or set `CHATTERBOX_API_URL` |
| Chatterbox is very slow / OOM on CPU | use `CHATTERBOX_DEVICE=cpu` with short sentences (already the default), or move to the HTTP server engine |
| Hindi sounds accented | set `CHATTERBOX_REF` to a Hindi clip, ensure `CHATTERBOX_MODEL=multilingual`, and `cfg_weight≈0.3` |
| Captions drift | check `ffprobe` is installed; without it durations fall back to `ffmpeg -i`/wave parsing, which can be a frame off |
| Devanagari boxes in burned captions | install `fonts-noto-devanagari` (CI already does) |
| `ffmpeg was not found` | install ffmpeg or `pip install imageio-ffmpeg` |
| Build dies with no images | image APIs are throttled; set `STUDIO_OFFLINE=1` to use gradient placeholders, or add `CLOUDFLARE_API_TOKEN` |

---

## 13. Credits

* [Chatterbox](https://github.com/resemble-ai/chatterbox) by Resemble AI (MIT) —
  model, watermarking and reference recordings stay subject to its disclaimer.
* [edge-tts](https://github.com/rany2/edge-tts) for the free fallback voices.
* Gemini, Cloudflare Workers AI, Pollinations, Pixabay, ffmpeg.

Use synthetic voices and cloned likenesses only with consent, and keep the
educational disclaimer on finance content.
