---
name: voice-studio
description: "VoiceStudio usage guidance: speak, design voices, long-form chapters, dubbing, status. Use when the user wants audio narration via the voicestudio plugin tools."
---

# Voice Studio

Use these tools when the user wants audio: narration, voice design,
long-form chapters, dubbing, or a VoiceStudio health check.

## Which tool

- `vs_speak`: short text (up to ~6000 characters). Needs a voice:
  call `vs_list_voices` first when the user names none.
- `vs_design_voice`: a new voice from a plain-words description or a
  wav/m4a sample (never both). Always needs a `--name`.
- `vs_list_voices`: browse saved, gallery, and preset voices.
  Read-only; call first when no voice is set.
- `vs_longform`: chaptered audio from a markdown script
  (`#` headings split chapters). Anything over a few minutes.
- `vs_dub`: dub a video into comma-separated languages (e.g. `es,fr`).
- `vs_status`: is VoiceStudio running and ready? Call when anything
  reports the server unreachable.

## Script markup (vs_longform only)

Supported: `[pause]`, `[pause 500ms]`, `[slow]` / `[fast]` /
`[emphasis]` / `[spell]` spans, `[[word|say-this]]` pronunciation pins,
`[voice:NAME]` switches, `#` chapter headings. Anything else is read
aloud literally. Strip it first.

## Recovery

- Server unreachable → start the VoiceStudio app, then `/vs-status`.
- No voice or unknown voice → `/vs-voices` to pick one.
- Interrupted long render → resume with the job id
  (`--resume <job_id>`); nothing is lost.
