# Paste this into a new Arena session opened on `ay23-byte/ai-studio-automation`

---

Apply the prepared fix bundle for this repository, then verify it on GitHub.

1. Fetch the bundle (public, read-only):

   ```bash
   git clone --depth 1 --filter=blob:none --sparse https://github.com/ay23-byte/ai-studio
   cd ai-studio && git sparse-checkout set handoff/ai-studio-automation
   ```

   Patches live in `handoff/ai-studio-automation/`; `all-changes.patch` is the
   combined diff. A copy of the audit is at `handoff/AUDIT.md`.

2. In this repository (`ai-studio-automation`, `main` at `38631d3`), create a
   branch and apply:

   ```bash
   git checkout -b fix/audit-longform-channel-and-storage
   git apply --binary ../ai-studio/handoff/ai-studio-automation/all-changes.patch
   ```

   Expected result: `make_longform.yml` becomes 223 valid lines with `jobs.build`
   and 7 inputs; `run.py`, `core/script_engine.py` and both env templates say
   Engineering Physics; `docs/AUDIT.md` appears; the OpenVINO workflow gains
   legacy-cache cleanup, export reuse and `min_free_gb`; `make_shorts.yml` stops
   committing `db/studio.sqlite` and uses `actions/cache`.

3. Commit in four logical commits (restore workflow / channel identity / audit /
   CI storage), push, and open a pull request against `main`.

4. Verify on GitHub, do not assume: wait for the `validate` workflow, confirm it
   is green, confirm the phantom failed run named
   `.github/workflows/make_longform.yml` no longer appears for the new push, and
   check that the PR diff contains no `db/studio.sqlite` binary change beyond the
   deletion.

5. Ask the human to dispatch **"Free local AI video generation — Intel Iris Xe"**
   with `min_free_gb: 100`. Do not claim the OpenVINO fix works until that run
   reaches the generation step; the PowerShell cannot be executed anywhere else.

6. Then continue with milestone 4 in the audit: a single free-provider registry
   with quota tracking and fallback (footage, images, TTS), replacing per-module
   retry logic. Keep the zero-cost policy: no paid provider, ever.

Constraints: no paid services; never claim an untested feature works; keep
`PRIVACY=private`/`unlisted` on every upload path; small PRs with CI evidence.
