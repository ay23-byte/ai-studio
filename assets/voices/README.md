# Reference voices

Drop a clean 10–20 second recording here to clone it with Chatterbox.

```
assets/voices/reference.wav
```

Then set:

```bash
CHATTERBOX_REF=assets/voices/reference.wav
VOICE_ENGINE=chatterbox
```

## Recording checklist

- **Length:** 10–20 s. Longer is not better; one continuous take is ideal.
- **Content:** natural sentences with a question and a pause — the model copies
  rhythm, not just timbre. Read a paragraph from the channel's actual scripts.
- **Format:** mono WAV, 24 kHz or higher, no music, no compressor, no reverb.
- **Language:** record in the language you will narrate in (Hindi for Hindi
  videos). A mismatched accent transfers into the output.
- **Levels:** peaks around −6 dBFS, no clipping, no background hiss.

## Choosing a reference for fast Shorts

A reference speaker with a brisk delivery plus `VOICE_PROFILE=fast`
(`cfg_weight≈0.3`) gives the tight, conversational pacing Shorts need. Slower,
warmer references suit `VOICE_PROFILE=documentary`.

This folder is git-ignored apart from this README, so your voice stays local.
