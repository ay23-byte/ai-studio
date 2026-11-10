# Handoff: `ay23-byte/ai-studio-automation`

This session's GitHub connection can only write to `ay23-byte/ai-studio`, so the
work below was prepared against `ay23-byte/ai-studio-automation` but could not be
pushed (HTTP 403: *Resource not accessible by integration*).

The patches apply cleanly to `9341d56` (the merge of PR #138) and were verified
locally:

* YAML parsed for every workflow; the restored `make_longform.yml` has
  `jobs.build` and its 7 inputs;
* `python -m compileall` clean;
* `python -m unittest discover -s tests` — 340 tests, OK (5 skipped);
* `git apply --check --binary` against a clean `9341d56` worktree.

| Patch | Summary |
| --- | --- |
| `0001-fix-ci-restore-the-long-form-production-workflow.patch` | Restores `make_longform.yml` (invalid since `b9f0a2d` deleted its `jobs:` block) and keeps only the paid MuAPI control removed |
| `0002-chore-point-channel-defaults-at-Engineering-Physics-.patch` | Replaces the last Power Codex strings, removes the paid ElevenLabs option from both env templates, documents the footage provider keys |
| `0003-docs-add-the-repository-audit-milestone-1.patch` | Adds `docs/AUDIT.md` (audit of 9341d56, including the PR #138 review) |
| `0004-fix-ci-reuse-a-valid-LTX-export-and-clean-every-lega.patch` | OpenVINO job: cleans every legacy HF cache location, reuses a complete INT8 export, clears partial exports, configurable free-space input |
| `0005-fix-ci-keep-studio-state-out-of-git.patch` | `make_shorts.yml`: SQLite restored/saved with `actions/cache`, only `topics.json` committed, `db/studio.sqlite` untracked |

`all-changes.patch` is the same set as one diff.

To continue from a session opened on `ai-studio-automation`:

```bash
git clone https://github.com/ay23-byte/ai-studio  # public, read-only
git apply --binary ai-studio/handoff/ai-studio-automation/all-changes.patch
```

Then push a branch and open the PR. The PowerShell logic in patch 4 cannot be
executed outside the self-hosted Windows runner; it still needs one real run.
