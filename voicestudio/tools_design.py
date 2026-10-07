"""vs_design_voice handler (architecture §3 tool 2).

Flows (architecture §4, LOCKED):
- describe: POST /design/describe (free text -> attrs) -> POST /profiles
  with kind=design + vd_states JSON.
- clone: POST /profiles multipart, kind=clone, ref_audio=<wav/m4a>.
"""

import os

from . import client
from .tools_speak import _cfg, _resolve_voice  # shared settings plumbing

BASE_URL = client.DEFAULT_BASE_URL

DESCRIBE_CHAR_LIMIT = 2000
PREVIEW_TEXT = "Hello. This is a short preview of the new voice."
SAMPLE_EXTS = (".wav", ".m4a")


def _post_profile(base_url, fields, files, timeout):
    r = client.api_post_multipart(base_url, "/profiles", fields, files=files, timeout=timeout)
    if client.is_connection_failure(r):
        return None, client.err_envelope(client.server_down_error(base_url), code="E1_server_down")
    payload = client.parse_json_body(r) or {}
    if r.get("status") in (409, 422, 400):
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("detail") or payload.get("error") or "")
        if "already" in detail.lower() or "exists" in detail.lower() or "taken" in detail.lower():
            name = fields.get("name", "")
            return None, client.err_envelope(
                "You already have a voice called '%s'. Pick another name, "
                "or tell me to replace it." % name, code="E7_duplicate_name")
        return None, client.err_envelope(
            "VoiceStudio did not accept that voice%s." % (": %s" % detail if detail else ""),
            code="E_request_rejected")
    if r.get("status") != 200:
        return None, client.err_envelope(
            "VoiceStudio returned an error (HTTP %s). Try again, or run /vs-status."
            % r.get("status"), code="E_server_error")
    return payload if isinstance(payload, dict) else {}, None


def _preview_take(base_url, profile_id, out_dir, timeout):
    """Render a short sample with the new voice; best-effort, returns path or None."""
    try:
        from . import tools_speak
        raw = tools_speak.vs_speak(
            {"text": PREVIEW_TEXT, "voice": profile_id},
            base_url=base_url, out_dir=out_dir, timeout_s=timeout)
        import json as _json
        env = _json.loads(raw)
        if env.get("success"):
            return (env.get("audio_path")
                    or (env.get("data") or {}).get("path"))
    except Exception:
        pass
    return None


def vs_design_voice(args, **kwargs):
    """Describe-or-clone a voice and save it for reuse. Returns JSON string."""
    try:
        args = dict(args or {})
        base_url = client.normalize_base_url(_cfg("base_url", args, kwargs, client.DEFAULT_BASE_URL))
        timeout = float(_cfg("timeout_s", args, kwargs, client.DEFAULT_READ_TIMEOUT_S)
                        or client.DEFAULT_READ_TIMEOUT_S)
        out_dir = _cfg("out_dir", args, kwargs, ".")
        name = str(args.get("name") or "").strip()
        describe = str(args.get("describe") or "").strip()
        sample = str(args.get("sample") or "").strip()
        preview = args.get("preview", True)
        preview = False if preview in (False, "false", "False", "0", 0) else True

        if not name:
            return client.err_envelope(
                "Give the new voice a name with --name, e.g. "
                "/vs-design --describe 'warm young female' --name 'Narrator'.",
                code="E_missing_name")
        if describe and sample:
            return client.err_envelope(
                "Use --describe or --sample, not both. Describe a voice in words, "
                "or clone one from a recording.",
                code="E_both_sources")
        if not describe and not sample:
            return client.err_envelope(
                "Say what the voice should sound like (--describe '...') or give a "
                "recording to clone (--sample voice.wav).",
                code="E_no_source")

        if sample:
            # Clone path: POST /profiles multipart, kind=clone.
            if not os.path.isfile(os.path.expanduser(sample)):
                return client.err_envelope(
                    "I could not use '%s'. I need a wav or m4a recording "
                    "with a few seconds of clear speech." % sample,
                    code="E6_bad_sample")
            if os.path.splitext(sample)[1].lower() not in SAMPLE_EXTS:
                return client.err_envelope(
                    "I could not use '%s'. I need a wav or m4a recording "
                    "with a few seconds of clear speech." % sample,
                    code="E6_bad_sample")
            with open(os.path.expanduser(sample), "rb") as f:
                content = f.read()
            payload, err = _post_profile(
                base_url,
                {"kind": "clone", "name": name},
                {"ref_audio": (os.path.basename(sample), content)},
                timeout)
            if err:
                return err
            new_id = payload.get("id") or payload.get("profile_id") or name
            preview_path = _preview_take(base_url, new_id, out_dir, timeout) if preview else None
            data = {"id": new_id, "name": name,
                    "message": "Voice '%s' is ready (id %s). Use it with --voice %s."
                               % (name, new_id, new_id)}
            if preview_path:
                data["preview_path"] = preview_path
                data["message"] += " Preview saved to %s." % preview_path
            return client.ok_envelope(data)

        # Design path: describe -> save as profile.
        if len(describe) > DESCRIBE_CHAR_LIMIT:
            return client.err_envelope(
                "That description is %d characters. Keep it under %d, "
                "e.g. 'warm young female, slight British accent'."
                % (len(describe), DESCRIBE_CHAR_LIMIT),
                code="E_describe_too_long")
        r = client.api_post_json(
            base_url, "/design/describe", {"description": describe}, timeout=timeout)
        if client.is_connection_failure(r):
            return client.err_envelope(client.server_down_error(base_url), code="E1_server_down")
        if r.get("status") != 200:
            return client.err_envelope(
                "VoiceStudio did not accept that description (HTTP %s). "
                "Try plainer words, or browse /vs-voices and start from one you like."
                % r.get("status"), code="E_request_rejected")
        desc = client.parse_json_body(r) or {}
        vd_states = desc.get("vd_states") or desc.get("attrs") or {}
        unmatched = desc.get("unmatched") or []
        understood = desc.get("understood") or desc.get("matched") or vd_states
        if not vd_states:
            return client.err_envelope(
                "I understood: %s. I did not catch: %s. Try plainer words "
                "(e.g. young/older, warm/clear, a named accent), or browse "
                "/vs-voices and start from one you like."
                % (understood or "nothing", ", ".join(unmatched) if unmatched else describe),
                code="E5_vague_description")

        import json as _json
        payload, err = _post_profile(
            base_url,
            {"kind": "design", "name": name,
             "vd_states": _json.dumps(vd_states)},
            files=None, timeout=timeout)
        if err:
            return err
        new_id = payload.get("id") or payload.get("profile_id") or name
        preview_path = _preview_take(base_url, new_id, out_dir, timeout) if preview else None
        data = {"id": new_id, "name": name,
                "message": "Voice '%s' is ready (id %s). Use it with --voice %s."
                           % (name, new_id, new_id)}
        if unmatched:
            data["unmatched"] = unmatched
            data["message"] += " Note: I did not use: %s." % ", ".join(unmatched)
        if preview_path:
            data["preview_path"] = preview_path
            data["message"] = data["message"].rstrip(".") + ". Preview saved to %s." % preview_path
        return client.ok_envelope(data)
    except Exception as e:  # never raise to the loop
        return client.err_envelope("Could not design that voice: %s" % e, code="E_exception")
