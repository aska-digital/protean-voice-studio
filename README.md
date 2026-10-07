# protean-voice-studio

VoiceStudio text-to-speech sidecar client for Hermes Agent, based on
https://github.com/debpalash/VoiceStudio.

## What it does

Six tools, one per user intent:

1. `vs_speak` — Read short text aloud in a chosen voice and save it as an audio file.
2. `vs_design_voice` — Describe a voice in plain words (or clone one from a sample recording) and save it for reuse.
3. `vs_list_voices` — Browse the voices you can use: your saved voices, the shared gallery, and ready-made presets.
4. `vs_longform` — Turn a long script into chaptered audio (audiobook/podcast).
5. `vs_dub` — Dub a video into other languages using one of your voices.
6. `vs_status` — Check that VoiceStudio is running, what is loaded, and what is missing.

Each tool is also mirrored as a slash command (`/vs-speak`, `/vs-design`,
`/vs-voices`, `/vs-longform`, `/vs-dub`, `/vs-status`), plus one bundled
skill (`voice-studio`).

## Prerequisites

A local VoiceStudio server, default `http://127.0.0.1:3900`. Start the
VoiceStudio app first; `/vs-status` tells you when it is back.

## Install

Clone into the Hermes plugins dir (or install from this repo URL):

```bash
git clone https://github.com/aska-digital/protean-voice-studio ~/.hermes/plugins/voicestudio
```

The plugin installs disabled (opt-in). Enable it with:

```bash
hermes plugins enable voicestudio
```

## Configure

Plugin settings (see `plugin.yaml` `config_schema`):

- `base_url` — VoiceStudio server base URL (default `http://127.0.0.1:3900`).
- `default_voice` — Default narrator voice id when the user names none (default empty: pick a voice per call with `/vs-voices`).
- `default_engine` — Preferred engine when several are loaded (default empty).
- `timeout_s` — Read timeout in seconds for generation calls (default 600).

## Usage

```bash
/vs-status
/vs-speak --text 'Hello there.' --voice <id>
```

For chapters, audiobooks, or anything over a few minutes, use `/vs-longform`
with a markdown script file (`#` headings split chapters).

## Dev

```bash
bash run_tests.sh        # unit suite, mocked HTTP (no server needed)
python3 -m pytest tests/ # same suite, direct
```

Live integration tests need the VoiceStudio server running.

## License

MIT. See `LICENSE`.
