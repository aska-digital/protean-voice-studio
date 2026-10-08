"""LLM-visible tool schemas — descriptions are the routing surface.

Six tools, one per user intent (architecture §3, STABLE).
"""

VS_SPEAK = {
    "name": "vs_speak",
    "description": (
        "Read short text aloud in a VoiceStudio voice and save it as an audio file. "
        "Use for any 'say X in voice Y' request up to a few paragraphs long "
        "(~6000 characters per call). Takes text, a voice id or name, playback "
        "speed (0.25 to 4.0, default 1.0), and an optional seed to repeat a take. "
        "Returns the saved audio file path, duration, and seed. "
        "For chapters, audiobooks, or anything over a few minutes, use vs_longform. "
        "To find a voice, use vs_list_voices; to make one, use vs_design_voice."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to speak. Required. Max ~6000 characters per call; split longer input or use vs_longform.",
            },
            "voice": {
                "type": "string",
                "description": "Voice id or name (e.g. a profile id). Defaults to the configured default voice.",
            },
            "speed": {
                "type": "number",
                "description": "Playback speed multiplier, 0.25 to 4.0. Default 1.0.",
            },
            "seed": {
                "type": "integer",
                "description": "Optional seed to repeat an exact take. Reuse the seed returned last time.",
            },
            "out_path": {
                "type": "string",
                "description": "Optional output file name for the audio (e.g. take.mp3). Saved inside the plugin output directory; paths escaping it are rejected. Omit to auto-name.",
            },
        },
        "required": ["text"],
    },
}

VS_DESIGN_VOICE = {
    "name": "vs_design_voice",
    "description": (
        "Create a reusable VoiceStudio voice, two ways: describe it in plain words "
        "(e.g. 'warm young female, slight British accent', max 2000 characters) or "
        "clone it from a short wav/m4a sample recording. Give the saved voice a name. "
        "Returns the new voice id plus a preview audio path. "
        "To browse existing voices instead, use vs_list_voices."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "describe": {
                "type": "string",
                "description": "Plain-words voice description, max 2000 chars. Use this OR sample, never both.",
            },
            "sample": {
                "type": "string",
                "description": "Path to a wav or m4a recording of clear speech to clone. Use this OR describe, never both.",
            },
            "name": {
                "type": "string",
                "description": "Required. What to call the saved voice.",
            },
            "preview": {
                "type": "boolean",
                "description": "Render a short sample before saving. Default true.",
            },
        },
        "required": ["name"],
    },
}

VS_LIST_VOICES = {
    "name": "vs_list_voices",
    "description": (
        "Browse the voices available in VoiceStudio: the user's saved voices, "
        "the shared gallery, and ready-made presets. Read-only and cheap. "
        "Call this first whenever the user names no voice. "
        "Optional search word filters by name or style; kind filters to "
        "mine, gallery, or presets. Returns matching voices with ids to use "
        "as the voice argument of vs_speak, vs_longform, or vs_dub."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "search": {
                "type": "string",
                "description": "Optional word to filter voices by name or style.",
            },
            "kind": {
                "type": "string",
                "description": "Optional filter: mine, gallery, or presets. Default all, saved voices first.",
                "enum": ["mine", "gallery", "presets"],
            },
        },
        "required": [],
    },
}

VS_LONGFORM = {
    "name": "vs_longform",
    "description": (
        "Turn a long script into chaptered audio (audiobook or podcast episode). "
        "Best for anything over a few minutes. Takes a markdown script file "
        "(# headings start new chapters), a narrator voice, output format "
        "(m4b keeps chapters, mp3 for wide compatibility), and optional title/author. "
        "Reports a chapter plan first, then renders with progress; an interrupted "
        "render can be continued with resume. Script markup is limited to the "
        "supported set: [pause], [pause 500ms], [slow]/[fast]/[emphasis]/[spell] "
        "spans, [[word|say-this]] pronunciation pins, [voice:NAME] switches, "
        "and # chapter headings."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "Required. Path to the markdown script file (# headings split chapters).",
            },
            "voice": {
                "type": "string",
                "description": "Default narrator voice id. Defaults to the configured default voice.",
            },
            "format": {
                "type": "string",
                "description": "Output format. Default m4b (keeps chapters); mp3 for wide compatibility.",
                "enum": ["m4b", "mp3"],
            },
            "title": {
                "type": "string",
                "description": "Optional title written into the file info.",
            },
            "author": {
                "type": "string",
                "description": "Optional author written into the file info.",
            },
            "resume": {
                "type": "string",
                "description": "Optional job id to continue an interrupted render. Nothing is lost on interruption.",
            },
        },
        "required": ["file"],
    },
}

VS_DUB = {
    "name": "vs_dub",
    "description": (
        "Dub a video file into other languages using a VoiceStudio voice. "
        "Takes a video file path, one or more target languages (e.g. es,fr), "
        "and a voice. Starts a dub job and reports per-language progress. "
        "Finished files keep the non-failed languages even if one language fails."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "video": {
                "type": "string",
                "description": "Required. Path to the video file to dub.",
            },
            "langs": {
                "type": "string",
                "description": "Required. Target languages, comma-separated (e.g. es,fr).",
            },
            "voice": {
                "type": "string",
                "description": "Voice id for the dubbed speech. Defaults to the configured default voice.",
            },
        },
        "required": ["video", "langs"],
    },
}

VS_STATUS = {
    "name": "vs_status",
    "description": (
        "Check that VoiceStudio is running, which engine is loaded, how many voices "
        "are available, and what is missing. Takes no arguments. "
        "Call this when anything else reports the server unreachable, or when "
        "the user asks whether VoiceStudio is ready."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

ALL_SCHEMAS = [VS_SPEAK, VS_DESIGN_VOICE, VS_LIST_VOICES, VS_LONGFORM, VS_DUB, VS_STATUS]
