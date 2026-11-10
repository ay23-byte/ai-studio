# Handoff: `ay23-byte/ai-studio-automation`

Rebased onto `38631d3` ("Improve Hugging Face Xet downloads and retry resilience")
with **no conflicts** — the Xet env vars and `hf_xet` install coexist with the
storage/cache changes below.

This session's GitHub token is scoped to `ay23-byte/ai-studio`, so every push to
`ai-studio-automation` returns 403 (*Resource not accessible by integration*).
Nothing here is on that repository yet.

## Two ways to land it

### A. Browser only (no terminal)

`browser-upload/` contains the final files. In GitHub's web UI, open the target
repository, use **Add file → Upload files**, and drop each file into its folder:

| Local file | Destination in `ai-studio-automation` |
| --- | --- |
| `browser-upload/make_longform.yml` | `.github/workflows/make_longform.yml` (replaces the truncated file — critical) |
| `browser-upload/make_shorts.yml` | `.github/workflows/make_shorts.yml` |
| `browser-upload/openvino-ltx-local-gpu.yml` | `.github/workflows/openvino-ltx-local-gpu.yml` |
| `browser-upload/AUDIT.md` | `docs/AUDIT.md` (new file) |

Then delete the tracked database in the same commit if the web UI allows it, or
leave it — the patch series does that step.

### B. From a session opened on the target repo

```bash
git clone https://github.com/ay23-byte/ai-studio
git apply --binary ai-studio/handoff/ai-studio-automation/all-changes.patch
```

## What the patches change

| Patch | Summary |
| --- | --- |
| `0001` | Restores `make_longform.yml` (invalid since `b9f0a2d` deleted its `jobs:` block) |
| `0002` | Last Power Codex strings → Engineering Physics, paid ElevenLabs option removed, footage keys documented |
| `0003` | `docs/AUDIT.md` |
| `0004` | OpenVINO: clean all legacy HF caches, reuse a complete INT8 export, clear partial exports, configurable `min_free_gb` |
| `0005` | `make_shorts.yml`: SQLite via `actions/cache`, only `topics.json` committed, `db/studio.sqlite` untracked |

Verified locally against `38631d3`: every workflow parses (`make-longform` has
`jobs.build` and 7 inputs), `compileall` clean, 340 unit tests OK (5 skipped),
`git apply --check --binary` clean, 0 Power Codex references, database untracked.

Patch 4's PowerShell runs only on the self-hosted Windows runner; it is
YAML-validated and reviewed, not executed. One dispatch run with
`min_free_gb: 100` is the required evidence.
