# protean-voice-studio

VoiceStudio text-to-speech sidecar client for Hermes Agent, based on
https://github.com/debpalash/VoiceStudio.

## What it does

Six tools, one per user intent:

1. `vs_speak`: reads short text aloud in a chosen voice and saves it as an audio file.
2. `vs_design_voice`: describes a voice in plain words (or clones one from a sample recording) and saves it for reuse.
3. `vs_list_voices`: browses the voices you can use: your saved voices, the shared gallery, and ready-made presets.
4. `vs_longform`: turns a long script into chaptered audio (audiobook/podcast).
5. `vs_dub`: dubs a video into other languages using one of your voices.
6. `vs_status`: checks that VoiceStudio is running, what is loaded, and what is missing.

Each tool is also mirrored as a slash command (`/vs-speak`, `/vs-design`,
`/vs-voices`, `/vs-longform`, `/vs-dub`, `/vs-status`), plus one bundled
skill (`voice-studio`).

## Prerequisites

A local VoiceStudio server, default `http://127.0.0.1:3900`. Start the
VoiceStudio app first; `/vs-status` tells you when it is back.

## Install

From the Hermes plugin catalog:

```bash
hermes plugins install voicestudio
```

Manual install: point Hermes at the `voicestudio/` subdirectory. It
carries the manifest and the package together:

```bash
git clone https://github.com/aska-digital/protean-voice-studio
hermes plugins install ./protean-voice-studio/voicestudio
```

The plugin installs disabled (opt-in). Enable it with:

```bash
hermes plugins enable voicestudio
```

## Configure

Plugin settings (see `plugin.yaml` `config_schema`):

- `base_url`: VoiceStudio server base URL (default `http://127.0.0.1:3900`).
- `default_voice`: default narrator voice id when the user names none (default empty: pick a voice per call with `/vs-voices`).
- `default_engine`: preferred engine when several are loaded (default empty).
- `timeout_s`: read timeout in seconds for generation calls (default 600).

## Usage

```bash
/vs-status
/vs-speak --text 'Hello there.' --voice <id>
```

For chapters, audiobooks, or anything over a few minutes, use `/vs-longform`
with a markdown script file (`#` headings split chapters).

## Disclosure

What the plugin does on your machine, for the catalog record:

- All network traffic stays between Hermes and your VoiceStudio server
  (default `http://127.0.0.1:3900`, configurable via `base_url`).
  Nothing is sent to third-party services.
- `vs_dub` uploads your video file to the VoiceStudio server;
  `vs_design_voice --sample` uploads your sample recording. Both stay
  on your local server.
- The plugin reads the script, video, and sample files you point it at,
  and writes generated audio under the plugin output directory
  (or the `--out_path` you give).
- No credentials are read or stored. No telemetry. No self-updates:
  catalog installs stay pinned to the reviewed commit.

## Dev

```bash
bash run_tests.sh        # unit suite, mocked HTTP (no server needed)
python3 -m pytest tests/ # same suite, direct
```

Live integration tests need the VoiceStudio server running.

## License

MIT. See `LICENSE`.
