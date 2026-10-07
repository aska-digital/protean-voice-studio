"""vs_longform handler (architecture §3 tool 4).

Flow (architecture §4, LOCKED): POST /audiobook/plan ({text, default_voice})
-> POST /audiobook/preview (offered) -> POST /audiobook (AudiobookRequest:
default_voice, voice_map, lexicon, format, loudness, metadata, seed)
-> GET /export/history for the artifact. Poll GET /audiobook/jobs,
GET /jobs/{job_id}; resume via POST /audiobook/resume/{job_id}.
Stories-Editor alt (POST /longform/render) intentionally not a v1 path.

Authoring grammar enforced here is the SOP closed set only (SOP §1).
"""

import os
import re
import time

from . import client
from .tools_speak import _cfg

BASE_URL = client.DEFAULT_BASE_URL

# Unsupported-but-plausible tags -> E10 (SOP §1: reach the model as literal tokens).
_UNSUPPORTED_TAG_RES = [
    re.compile(r"\[\s*(sigh|laugh|breath|cough|gasp|break|rate[^\]]*)\s*\]", re.IGNORECASE),
    re.compile(r"<break\b[^>]*/?>", re.IGNORECASE),
    re.compile(r"\(\s*pause\s*\)", re.IGNORECASE),
    re.compile(r"\*[a-z]+sighs?\*|\*sighs?\*", re.IGNORECASE),
]

POLL_INTERVAL_S = 5


def find_unsupported_markup(text):
    """Return {tag: [line numbers]} for markup outside the SOP closed set."""
    hits = {}
    for i, line in enumerate(text.splitlines(), start=1):
        for rx in _UNSUPPORTED_TAG_RES:
            for m in rx.finditer(line):
                hits.setdefault(m.group(0), set()).add(i)
    return {tag: sorted(lines) for tag, lines in hits.items()}


def count_chapters(text):
    """H1 (# ) headings split chapters; ##+ stays body text (SOP §1)."""
    titles = []
    for line in text.splitlines():
        if re.match(r"^# (?!#)", line):
            titles.append(line[2:].strip())
    return titles


def vs_longform(args, **kwargs):
    """Render a chaptered script to m4b/mp3. Returns JSON-string envelope."""
    try:
        args = dict(args or {})
        base_url = client.normalize_base_url(_cfg("base_url", args, kwargs, client.DEFAULT_BASE_URL))
        timeout = float(_cfg("timeout_s", args, kwargs, client.DEFAULT_READ_TIMEOUT_S)
                        or client.DEFAULT_READ_TIMEOUT_S)
        default_voice = str(_cfg("default_voice", args, kwargs, "")
                            or args.get("voice") or "").strip()
        voice = str(args.get("voice") or default_voice).strip()
        fmt = str(args.get("format") or "m4b").strip().lower() or "m4b"
        title = str(args.get("title") or "").strip()
        author = str(args.get("author") or "").strip()
        resume_job = str(args.get("resume") or "").strip()
        script_path = str(args.get("file") or "").strip()

        if resume_job:
            r = client.api_post_json(
                base_url, "/audiobook/resume/%s" % resume_job, {}, timeout=timeout)
            if client.is_connection_failure(r):
                return client.err_envelope(client.server_down_error(base_url), code="E1_server_down")
            payload = client.parse_json_body(r) or {}
            job_id = payload.get("job_id") or resume_job
            final = _poll_audiobook_job(base_url, job_id, timeout)
            return final

        if not script_path:
            return client.err_envelope(
                "Give me the script file with --file, e.g. "
                "/vs-longform --file episode.md. Use # headings to split chapters.",
                code="E_missing_file")
        if not os.path.isfile(os.path.expanduser(script_path)):
            return client.err_envelope(
                "I could not open '%s'. Check the path and try again." % script_path,
                code="E_bad_script")
        if not voice:
            return client.err_envelope(
                "No narrator chosen and no default voice is set. "
                "Run /vs-voices to pick one, then repeat with --voice <id>.",
                code="E2_voice_missing",
                hint="Call vs_list_voices first.")
        if fmt not in ("m4b", "mp3"):
            fmt = "m4b"

        with open(os.path.expanduser(script_path), encoding="utf-8", errors="replace") as f:
            text = f.read()
        if not text.strip():
            return client.err_envelope(
                "That script file is empty. Add the episode text first.",
                code="E_empty_script")

        bad = find_unsupported_markup(text)
        if bad:
            tags = ", ".join(sorted(bad))
            lines = sorted({n for ns in bad.values() for n in ns})
            return client.err_envelope(
                "Your script uses %s on lines %s, which voices cannot perform. "
                "They would be read aloud literally. Remove them, or replace a "
                "sigh/laugh with [pause 600ms] plus a rewritten line "
                "(e.g. 'She exhaled…'). Supported: [pause], [pause 500ms], "
                "[slow]/[fast]/[emphasis]/[spell], [[word|say-this]], "
                "[voice:NAME], # Chapter headings."
                % (tags, ", ".join(str(n) for n in lines[:12])),
                code="E10_unsupported_markup")

        chapters = count_chapters(text)
        n_chapters = len(chapters) or 1

        plan = client.api_post_json(
            base_url, "/audiobook/plan",
            {"text": text, "default_voice": voice}, timeout=timeout)
        if client.is_connection_failure(plan):
            return client.err_envelope(client.server_down_error(base_url), code="E1_server_down")

        body = {"text": text, "default_voice": voice, "format": fmt,
                "loudness": "podcast"}
        metadata = {}
        if title:
            metadata["title"] = title
        if author:
            metadata["author"] = author
        if metadata:
            body["metadata"] = metadata
        if args.get("seed") is not None:
            body["seed"] = args["seed"]

        r = client.api_post_json(base_url, "/audiobook", body, timeout=timeout)
        if client.is_connection_failure(r):
            return client.err_envelope(client.server_down_error(base_url), code="E1_server_down")
        if r.get("status") in (422, 400):
            payload = client.parse_json_body(r) or {}
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if detail and "voice" in str(detail).lower():
                return client.err_envelope(
                    "I do not know the narrator voice '%s'. "
                    "Run /vs-voices --search %s to find it." % (voice, voice),
                    code="E2_voice_unknown")
            return client.err_envelope(
                "VoiceStudio did not accept that script%s."
                % (": %s" % detail if detail else ""),
                code="E_request_rejected")
        if r.get("status") != 200:
            return client.err_envelope(
                "VoiceStudio returned an error (HTTP %s). Try again, or run /vs-status."
                % r.get("status"), code="E_server_error")
        payload = client.parse_json_body(r) or {}
        job_id = payload.get("job_id") or payload.get("id")
        artifact = (payload.get("destination_path") or payload.get("audio_path")
                    or payload.get("path"))
        if artifact and not job_id:
            return client.ok_envelope({
                "path": artifact, "chapters": n_chapters, "format": fmt,
                "chapter_titles": chapters,
                "message": "Done. Saved to %s (%d chapters, format %s)."
                           % (artifact, n_chapters, fmt),
            }, audio_path=artifact)
        if not job_id:
            return client.err_envelope(
                "VoiceStudio accepted the script but gave no job to track. "
                "Run /vs-status, then try again.", code="E_no_job")

        started_msg = ("Plan ready: %d chapters. I will report progress as it renders." % n_chapters)
        final = _poll_audiobook_job(base_url, job_id, timeout, started_msg=started_msg,
                                    n_chapters=n_chapters, fmt=fmt, chapters=chapters)
        return final
    except Exception as e:  # never raise to the loop
        return client.err_envelope("Could not render that audiobook: %s" % e, code="E_exception")


def _poll_audiobook_job(base_url, job_id, timeout, started_msg=None,
                        n_chapters=None, fmt="m4b", chapters=None):
    """Poll job endpoints until done/failed or the timeout budget is spent."""
    deadline = time.time() + max(30, timeout)
    last_state = {}
    while time.time() < deadline:
        state = _fetch_job_state(base_url, job_id)
        if state.get("connection_failed"):
            return client.err_envelope(client.server_down_error(base_url), code="E1_server_down")
        last_state = state
        status = str(state.get("status") or "").lower()
        if status in ("done", "completed", "finished", "success"):
            artifact = (state.get("destination_path") or state.get("audio_path")
                        or state.get("path") or state.get("file"))
            if artifact:
                return client.ok_envelope({
                    "path": artifact, "job_id": job_id,
                    "chapters": n_chapters, "format": fmt,
                    "chapter_titles": chapters or [],
                    "message": "Done. Saved to %s (%s chapters, format %s)."
                               % (artifact, n_chapters or "?", fmt),
                }, audio_path=artifact)
            return client.ok_envelope({"job_id": job_id,
                                       "message": "Render finished (job %s)." % job_id})
        if status in ("failed", "error", "cancelled"):
            return client.err_envelope(
                "Rendering stopped%s. Nothing is lost. Rerun with --resume %s to continue."
                % (" at chapter %s of %s" % (state.get("chapter"), n_chapters)
                   if state.get("chapter") else "", job_id),
                code="E9_interrupted", hint="Rerun with resume=%s" % job_id)
        time.sleep(POLL_INTERVAL_S)
    return client.err_envelope(
        "Still rendering (job %s%s). The timeout budget ran out first. "
        "Rerun with --resume %s to continue. Nothing is lost."
        % (job_id,
           " — %s" % last_state.get("status") if last_state.get("status") else "",
           job_id),
        code="E9_interrupted", hint="Rerun with resume=%s" % job_id)


def _fetch_job_state(base_url, job_id):
    """Best-effort job read across the known job endpoints; {} when unknown."""
    for path in ("/jobs/%s" % job_id,
                 "/audiobook/jobs",
                 "/longform/jobs"):
        r = client.api_get(base_url, path, timeout=client.PROBE_TIMEOUT_S)
        if client.is_connection_failure(r):
            return {"connection_failed": True}
        if r.get("status") != 200:
            continue
        payload = client.parse_json_body(r)
        if isinstance(payload, dict) and path.endswith(job_id):
            return payload
        if isinstance(payload, dict):
            jobs = payload.get("jobs") or []
            for j in jobs:
                if isinstance(j, dict) and str(j.get("job_id") or j.get("id")) == str(job_id):
                    return j
        elif isinstance(payload, list):
            for j in payload:
                if isinstance(j, dict) and str(j.get("job_id") or j.get("id")) == str(job_id):
                    return j
    return {}
