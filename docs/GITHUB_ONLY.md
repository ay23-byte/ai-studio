# Run and test everything on GitHub — no laptop, no IDE

You do not need VS Code, a terminal, Python or ffmpeg on your machine. Every
check, render and publish step can be started from the **Actions** tab and its
result can be inspected in the browser.

> One caveat: the **Run workflow** button only lists workflows that exist on the
> default branch (`main`). Merge the branch that adds these workflows once, and
> from then on every button below is available.

## The four buttons

| I want to… | Workflow | What it does |
| --- | --- | --- |
| **Test everything** | Actions → **verify** → Run workflow | lint (code + workflows) + unit tests on Python 3.10/3.11/3.12, a real end-to-end render test, real Shorts and long-form renders, the QA gate, hardware report, voice benchmark, and real edge-tts speech |
| **Make a Short** | Actions → **make-shorts** → Run workflow | builds one Short; `script_source: demo` needs **no API key**, `engine: edge` gives real speech |
| **Make a long-form video** | Actions → **make-longform** → Run workflow | builds one 16:9 video (needs `GEMINI_API_KEY` for a fresh script) |
| **Check the channel is alive** | Actions → **watchdog** → Run workflow | fails if nothing was published in the last 26 hours |

Automatic, no clicking required:

| Event | Workflow |
| --- | --- |
| push to `main`, every pull request | `verify` (including a real edge-tts sample and the slow render test) |
| daily 09:00 IST | `make-shorts` (builds; uploads only if you enable it) |
| daily 12:30 IST | `watchdog` |
| Mondays 10:30 IST | `dependency-audit` (`pip-audit`) |

## Reading the result

1. Open **Actions → verify → the newest run**.
2. The run page opens on the **Summary** tab: QA verdict, benchmark, hardware
   line and live-voice files are printed there — no log digging needed.
3. Scroll to **Artifacts** and download:
   * `rendered-demo` — `shorts_demo.mp4`, `longform_demo.mp4`, thumbnails and
     the `doctor` / `bench` / `qa` text logs;
   * `live-voice` — real edge-tts WAVs (`edge_natural.wav`, `edge_fast.wav`), produced on every run so you can hear the actual fallback voice;
   * `junit-3.12` — machine-readable test report.
4. Play the MP4 directly from the browser to judge captions, pacing and visuals.

A red ✗ never publishes anything: the QA gate blocks uploads, and the file is
kept as an artifact so you can see what went wrong.

## Choosing the voice engine (without installing anything)

| Engine | Needs | Quality | Speed on GitHub |
| --- | --- | --- | --- |
| `silent` | nothing | timing/layout only | seconds |
| `edge` | nothing (free Microsoft endpoint) | good, clear, less human | ~1 min per video |
| `chatterbox-http` | `CHATTERBOX_API_URL` variable pointing at your GPU box | human, cloneable | depends on the box |
| `chatterbox` | `pip install -r requirements-voice.txt` inside the job | human | slow on shared runners |

`verify` with `engine: edge` is the cheapest way to *hear* a full pipeline on
GitHub. `make-shorts` with `engine: edge` produces a upload-ready video with no
API keys at all (use `script_source: demo`, or add `GEMINI_API_KEY` for fresh
topics).

## Secrets and variables

**Settings → Secrets and variables → Actions**

Secrets (never printed):

| Name | Used by | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | make-shorts, make-longform | scripts + SEO |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | make-shorts | AI images |
| `PIXABAY_API_KEY` | make-shorts | stock footage |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | upload steps | YouTube |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | failures + watchdog | alerts |
| `CHATTERBOX_API_TOKEN` | live job | remote GPU voice |

If an upload reports Google OAuth `invalid_grant`, the stored refresh token is
revoked/expired or mismatched with the OAuth client. Re-authorise the same
YouTube account with the same client and at least
`https://www.googleapis.com/auth/youtube.upload`, then replace the
`YT_REFRESH_TOKEN` Actions secret. Keep the client ID/secret unless the OAuth
client itself changed. Google expires refresh tokens after 7 days when an
External OAuth consent screen remains in Testing; publish the consent screen to
avoid that testing-mode expiry. `youtube.upload` is sufficient for uploading;
full `https://www.googleapis.com/auth/youtube` enables optional status checks,
playlists and comments. A missing read scope after upload no longer fails the
job: the video ID is saved, the status poll is skipped, and the upload is not
retried. See [Publishing](../README.md#fixing-invalid_grant-during-upload).

Variables (visible, handy for switching behaviour):

| Name | Example | Purpose |
| --- | --- | --- |
| `CHATTERBOX_API_URL` | `https://colab-host:4123` | enables the remote voice engine |
| `CHATTERBOX_REF` | `assets/voices/reference.wav` | cloned voice reference |

## Housekeeping

* **Re-run failed jobs** on the run page retries only the failed part.
* **Artifacts expire after 14 days** — download anything you want to keep.
* Each render is timestamped, so two runs never overwrite each other's file.
* Private repos consume Actions minutes (2000/month on the free plan); the daily
  Short plus one `verify` run per day is roughly 10–15 minutes/day.
* If a schedule silently stops, `watchdog` turns that into a failure and a
  Telegram message.

## Power users (optional)

The same actions from a terminal, if one is ever handy:

```bash
gh workflow run verify.yml -f engine=edge -f live_network=true
gh run watch
gh run download --name rendered-demo
```
