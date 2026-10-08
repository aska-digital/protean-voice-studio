"""vs_speak + vs_list_voices handlers (architecture §3 tools 1 and 3).

Short-form default: POST /generate multipart with profile_id (architecture §4,
LOCKED). /v1/audio/speech is ONLY for OpenAI-protocol clients — never used here.
"""

import json
import os
import time

from . import client

# Overridable at register() time from plugin settings; tests pass per-call kwargs.
# NOTE (CTO hardening): base_url / default_voice / timeout_s / out_dir control
# where uploads go and which server is hit. They come ONLY from plugin settings
# (module defaults set by register()) and explicit test kwargs — never from
# per-call args, which are prompt-injectable.
BASE_URL = client.DEFAULT_BASE_URL
DEFAULT_VOICE = ""
TIMEOUT_S = client.DEFAULT_READ_TIMEOUT_S


def hermes_home():
    """Hermes home dir: $HERMES_HOME, falling back to ~/.hermes."""
    return os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


def default_out_dir():
    """Plugin-owned output dir for saved audio (created on demand)."""
    return os.path.join(hermes_home(), "plugin-data", "voicestudio")


OUT_DIR = default_out_dir()

SPEAK_CHAR_LIMIT = 6000
SPEED_MIN, SPEED_MAX = 0.25, 4.0


def _cfg(key, args, kwargs, default=""):
    """Plugin-setting lookup: explicit test kwarg wins, else module default.

    Per-call args are NEVER consulted here — args are prompt-injectable, and
    these keys (base_url/out_dir/timeout_s/default_voice) decide where
    uploads go and which server is hit. args is kept in the signature so all
    existing call sites stay unchanged.
    """
    if key in kwargs and kwargs[key] is not None:
        return kwargs[key]
    module_defaults = {
        "base_url": BASE_URL, "default_voice": DEFAULT_VOICE,
        "timeout_s": TIMEOUT_S, "out_dir": OUT_DIR,
    }
    return module_defaults.get(key, default)


def _is_under(path_real, root_real):
    try:
        return os.path.commonpath([path_real, root_real]) == root_real
    except (ValueError, OSError):
        return False


def refused_input_path(path):
    """True when path resolves inside HERMES_HOME or ~/.ssh (never read these)."""
    real = os.path.realpath(os.path.expanduser(path))
    hh = os.path.realpath(hermes_home())
    ssh = os.path.realpath(os.path.expanduser(os.path.join("~", ".ssh")))
    return _is_under(real, ssh) or _is_under(real, hh)


def check_input_file(path, allowed_exts, kind_label, bad_ext_code):
    """Allowlist gate for user-supplied input files. Returns None when OK,
    else (message, code) for an err_envelope. Missing files return None so
    the caller can report them with its own not-found code."""
    if refused_input_path(path):
        return ("I cannot use files from that location. "
                "Pick a file outside your Hermes data directory and SSH keys, "
                "then try again.", "E_refused_path")
    ext = os.path.splitext(path)[1].lower()
    if ext not in allowed_exts:
        return ("I could not use '%s'. %s files must be one of: %s."
                % (path, kind_label, ", ".join(sorted(allowed_exts))),
                bad_ext_code)
    return None


def resolve_out_path(out_path):
    """Confine an explicit out_path under plugin-data/voicestudio/.

    Resolves symlinks/.. and rejects anything escaping the plugin dir.
    Returns the absolute confined path; raises ValueError on escape.
    """
    base = os.path.realpath(default_out_dir())
    os.makedirs(base, exist_ok=True)
    expanded = os.path.expanduser(out_path)
    if os.path.isabs(expanded):
        cand = os.path.realpath(expanded)
    else:
        cand = os.path.realpath(os.path.join(base, expanded))
    if not _is_under(cand, base):
        raise ValueError("out_path escapes the plugin output directory")
    return cand


def _resolve_voice(args, kwargs):
    v = (args.get("voice") if isinstance(args, dict) else None) or ""
    v = str(v).strip()
    if v:
        return v
    dflt = _cfg("default_voice", args, kwargs, "")
    return str(dflt).strip()


def vs_speak(args, **kwargs):
    """Say text in a voice, save audio file. Returns JSON-string envelope."""
    try:
        args = dict(args or {})
        base_url = client.normalize_base_url(_cfg("base_url", args, kwargs, client.DEFAULT_BASE_URL))
        timeout = float(_cfg("timeout_s", args, kwargs, client.DEFAULT_READ_TIMEOUT_S) or client.DEFAULT_READ_TIMEOUT_S)
        out_dir = _cfg("out_dir", args, kwargs, None) or default_out_dir()

        text = str(args.get("text") or "")
        if not text.strip():
            return client.err_envelope(
                "Give me the words to say with --text, e.g. /vs-speak --text 'Hello there'.",
                code="E_missing_text")

        if len(text) > SPEAK_CHAR_LIMIT:
            return client.err_envelope(
                "That is %d characters. Too long for one quick take (limit ~%d). "
                "Split it at paragraph breaks, or use /vs-longform for the whole thing."
                % (len(text), SPEAK_CHAR_LIMIT),
                code="E3_over_limit",
                hint="Split at paragraph breaks or call vs_longform.")

        voice = _resolve_voice(args, kwargs)
        if not voice:
            return client.err_envelope(
                "No voice chosen and no default voice is set. "
                "Run /vs-voices to pick one, then repeat with --voice <id>.",
                code="E2_voice_missing",
                hint="Call vs_list_voices first.")

        try:
            speed = float(args.get("speed", 1.0) or 1.0)
        except (TypeError, ValueError):
            speed = 1.0
        speed_note = None
        if not (SPEED_MIN <= speed <= SPEED_MAX):
            speed_note = ("Speed must be between 0.25 and 4.0 (1.0 is normal). "
                          "I used 1.0 this time.")
            speed = 1.0

        fields = {"text": text, "profile_id": voice, "speed": str(speed)}
        if args.get("seed") is not None:
            fields["seed"] = str(args["seed"])

        r = client.api_post_multipart(base_url, "/generate", fields, timeout=timeout)
        if client.is_connection_failure(r):
            return client.err_envelope(client.server_down_error(base_url), code="E1_server_down")
        if r.get("status") == 404:
            return client.err_envelope(
                client.unknown_voice_error(voice), code="E2_voice_unknown",
                hint="Call vs_list_voices to search.")
        if r.get("status") in (422, 400):
            detail = (client.parse_json_body(r) or {})
            msg = detail.get("detail") if isinstance(detail, dict) else None
            if msg and "voice" in str(msg).lower():
                return client.err_envelope(
                    client.unknown_voice_error(voice), code="E2_voice_unknown")
            return client.err_envelope(
                "VoiceStudio did not accept that take%s."
                % (": %s" % msg if msg else " (request rejected)."),
                code="E_request_rejected")
        if r.get("status") != 200:
            return client.err_envelope(
                "VoiceStudio returned an error (HTTP %s). Try again, or run /vs-status."
                % r.get("status"), code="E_server_error")

        body = r.get("body") or b""
        ctype = (r.get("headers") or {}).get("content-type", "")
        if body.lstrip()[:1] in (b"{", b"["):
            # Server answered JSON (history row / pointer) instead of audio.
            payload = client.parse_json_body(r) or {}
            if isinstance(payload, dict) and payload.get("audio_path"):
                data = {"path": payload["audio_path"], "voice": voice, "content_type": ctype}
                seed = payload.get("seed")
                if seed is not None:
                    data["seed"] = seed
                    data["message"] = ("Done. Saved to %(path)s (voice %(voice)s). "
                                       "Seed %(seed)s: reuse it to repeat this exact take." % data)
                else:
                    data["message"] = "Done. Saved to %(path)s (voice %(voice)s)." % data
                if speed_note:
                    data["note"] = speed_note
                return client.ok_envelope(data, audio_path=payload["audio_path"])
            return client.err_envelope(
                "VoiceStudio answered without audio. Try again, or run /vs-status.",
                code="E_empty_render")

        out_path = args.get("out_path")
        if out_path:
            try:
                path = resolve_out_path(out_path)
            except ValueError:
                return client.err_envelope(
                    "I cannot save there. Output files stay inside the "
                    "plugin output directory — give just a file name.",
                    code="E_bad_out_path")
            dest_dir = os.path.dirname(path)
            os.makedirs(dest_dir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(body)
        else:
            stem = "vs-speak-%d" % int(time.time())
            path = client.save_bytes(body, out_dir, stem, "mp3")

        seed = (r.get("headers") or {}).get("x-seed")
        data = {"path": path, "voice": voice, "bytes": len(body)}
        if seed is not None:
            data["seed"] = seed
        data["message"] = ("Done. Saved to %(path)s (voice %(voice)s). Seed %(seed)s: "
                           "reuse it to repeat this exact take." % data) if seed is not None else \
            ("Done. Saved to %s (voice %s)." % (path, voice))
        if speed_note:
            data["note"] = speed_note
        return client.ok_envelope(data, audio_path=path)
    except Exception as e:  # never raise to the loop
        return client.err_envelope("Could not render that take: %s" % e, code="E_exception")


def _matches(item, search):
    if not search:
        return True
    hay = json.dumps(item).lower()
    return all(w in hay for w in search.lower().split())


def vs_list_voices(args, **kwargs):
    """Browse saved voices, gallery, and presets. Read-only. Returns JSON string."""
    try:
        args = dict(args or {})
        base_url = client.normalize_base_url(_cfg("base_url", args, kwargs, client.DEFAULT_BASE_URL))
        timeout = client.PROBE_TIMEOUT_S
        search = str(args.get("search") or "").strip()
        kind = str(args.get("kind") or "").strip().lower() or "all"

        probe = client.api_get(base_url, "/setup/status", timeout=timeout)
        if client.is_connection_failure(probe):
            return client.err_envelope(client.server_down_error(base_url), code="E1_server_down")

        mine, gallery, presets = [], [], []
        if kind in ("all", "mine"):
            r = client.api_get(base_url, "/profiles", timeout=timeout)
            payload = client.parse_json_body(r)
            if isinstance(payload, dict) and isinstance(payload.get("profiles"), list):
                items = payload["profiles"]
            elif isinstance(payload, list):
                items = payload
            else:
                items = []
            mine = [{"id": p.get("id"), "name": p.get("name"),
                     "kind": p.get("kind"), "language": p.get("language")}
                    for p in items if isinstance(p, dict) and _matches(p, search)]
        if kind in ("all", "gallery"):
            r = client.api_get(base_url, "/gallery/voices", timeout=timeout)
            payload = client.parse_json_body(r)
            items = payload if isinstance(payload, list) else (
                payload.get("voices") if isinstance(payload, dict) else []) or []
            gallery = [{"id": g.get("id"), "name": g.get("name")}
                       for g in items if isinstance(g, dict) and _matches(g, search)]
            if not gallery:  # fall back to archetype starting points
                r2 = client.api_get(base_url, "/archetypes", timeout=timeout)
                p2 = client.parse_json_body(r2)
                items2 = p2 if isinstance(p2, list) else (
                    p2.get("archetypes") if isinstance(p2, dict) else []) or []
                gallery = [{"id": g.get("id"), "name": g.get("name")}
                           for g in items2 if isinstance(g, dict) and _matches(g, search)]
        if kind in ("all", "presets"):
            r = client.api_get(base_url, "/personalities", timeout=timeout)
            payload = client.parse_json_body(r)
            items = payload if isinstance(payload, list) else (
                payload.get("personalities") if isinstance(payload, dict) else []) or []
            presets = [{"id": g.get("id"), "name": g.get("name")}
                       for g in items if isinstance(g, dict) and _matches(g, search)]

        n = len(mine) + len(gallery) + len(presets)
        if n == 0:
            return client.ok_envelope({
                "count": 0,
                "message": ("No voices match '%s'. Try a shorter search "
                            "or make one with /vs-design." % search) if search else
                           "No voices found. Make one with /vs-design.",
                "mine": [], "gallery": [], "presets": [],
            })
        return client.ok_envelope({
            "count": n,
            "mine": mine, "gallery": gallery, "presets": presets,
            "message": ("Found %d voices. Yours: %s. Gallery highlights: %s. Presets: %s. "
                        "Use any with --voice <id>."
                        % (n,
                           ", ".join(v.get("name") or v.get("id") for v in mine[:5]) or "none",
                           ", ".join(v.get("name") or v.get("id") for v in gallery[:5]) or "none",
                           ", ".join(v.get("name") or v.get("id") for v in presets[:5]) or "none")),
        })
    except Exception as e:  # never raise to the loop
        return client.err_envelope("Could not list voices: %s" % e, code="E_exception")
