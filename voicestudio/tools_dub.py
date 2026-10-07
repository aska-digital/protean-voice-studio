"""vs_dub + vs_status handlers (architecture §3 tools 5 and 6).

Dub (architecture §4, spec-structure + live probes, not Hazen-verified):
field names treated as confirm-at-integration-test.
Status: GET /setup/status + GET /engines (+/engines/tts) + model/system reads.
"""

import os
import time

from . import client
from .tools_speak import _cfg

BASE_URL = client.DEFAULT_BASE_URL
POLL_INTERVAL_S = 10


def vs_dub(args, **kwargs):
    """Dub a video into other languages. Returns JSON-string envelope."""
    try:
        args = dict(args or {})
        base_url = client.normalize_base_url(_cfg("base_url", args, kwargs, client.DEFAULT_BASE_URL))
        timeout = float(_cfg("timeout_s", args, kwargs, client.DEFAULT_READ_TIMEOUT_S)
                        or client.DEFAULT_READ_TIMEOUT_S)
        default_voice = str(_cfg("default_voice", args, kwargs, "") or "").strip()
        video = str(args.get("video") or "").strip()
        langs_raw = str(args.get("langs") or "").strip()
        voice = str(args.get("voice") or default_voice).strip()

        if not video or not os.path.isfile(os.path.expanduser(video)):
            return client.err_envelope(
                "I could not open '%s'. Check the path and that it is a video file. "
                "Then try again." % (video or "(no file given)"),
                code="E11_bad_video")
        if not langs_raw:
            return client.err_envelope(
                "Which languages should I dub into? Example: "
                "/vs-dub --video intro.mp4 --langs es,fr.",
                code="E12_no_langs")
        langs = [l.strip() for l in langs_raw.replace(";", ",").split(",") if l.strip()]
        if not langs:
            return client.err_envelope(
                "Which languages should I dub into? Example: "
                "/vs-dub --video intro.mp4 --langs es,fr.",
                code="E12_no_langs")
        if not voice:
            return client.err_envelope(
                "No voice chosen and no default voice is set. "
                "Run /vs-voices to pick one, then repeat with --voice <id>.",
                code="E2_voice_missing",
                hint="Call vs_list_voices first.")

        with open(os.path.expanduser(video), "rb") as f:
            video_bytes = f.read()
        fields = {"langs": ",".join(langs), "voice_id": voice}
        files = {"video": (os.path.basename(video), video_bytes)}
        r = client.api_post_multipart(base_url, "/batch/enqueue", fields,
                                      files=files, timeout=timeout)
        if r.get("status") == 404:
            # Fallback route for servers exposing the JSON translate door.
            r = client.api_post_json(
                base_url, "/dub/translate",
                {"video": video, "langs": langs, "voice_id": voice},
                timeout=timeout)
        if client.is_connection_failure(r):
            return client.err_envelope(client.server_down_error(base_url), code="E1_server_down")
        if r.get("status") not in (200, 201, 202):
            return client.err_envelope(
                "VoiceStudio did not accept that dub job (HTTP %s). "
                "Try again, or run /vs-status." % r.get("status"),
                code="E_server_error")
        payload = client.parse_json_body(r) or {}
        job_id = payload.get("job_id") or payload.get("id") or payload.get("task_id")
        if not job_id:
            paths = payload.get("paths") or payload.get("files") or []
            if paths:
                return client.ok_envelope({
                    "paths": paths,
                    "message": "Done. Dubbed files: %s." % ", ".join(paths),
                })
            return client.err_envelope(
                "VoiceStudio accepted the dub but gave no job to track. "
                "Run /vs-status, then try again.", code="E_no_job")

        started = "Dub job started for %s. I will tell you when each language finishes." \
                  % ", ".join(langs)
        return _poll_dub_job(base_url, job_id, langs, timeout, started_msg=started)
    except Exception as e:  # never raise to the loop
        return client.err_envelope("Could not start that dub: %s" % e, code="E_exception")


def _poll_dub_job(base_url, job_id, langs, timeout, started_msg=None):
    deadline = time.time() + max(60, timeout)
    last = {}
    while time.time() < deadline:
        r = client.api_get(base_url, "/batch/jobs/%s" % job_id,
                           timeout=client.PROBE_TIMEOUT_S)
        if client.is_connection_failure(r):
            return client.err_envelope(client.server_down_error(base_url), code="E1_server_down")
        payload = client.parse_json_body(r) or {}
        last = payload if isinstance(payload, dict) else {}
        status = str(last.get("status") or "").lower()
        if status in ("done", "completed", "finished", "success"):
            paths = last.get("paths") or last.get("files") or []
            failed = last.get("failed") or {}
            if failed:
                ok_langs = [l for l in langs if l not in failed]
                bad = ", ".join("%s (%s)" % kv for kv in failed.items()) \
                    if isinstance(failed, dict) else str(failed)
                return client.ok_envelope({
                    "paths": paths, "job_id": job_id, "partial": True,
                    "message": "Dubbed %s, but %s failed. Your finished files: %s. "
                               "Say the word and I will retry %s."
                               % (", ".join(ok_langs) or "nothing yet", bad,
                                  ", ".join(paths) or "none yet", bad),
                })
            return client.ok_envelope({
                "paths": paths, "job_id": job_id,
                "message": "Done. Dubbed files: %s." % (", ".join(paths) or "(no paths returned)"),
            })
        if status in ("failed", "error", "cancelled"):
            return client.err_envelope(
                "The dub job failed (%s). Run /vs-status, then try again."
                % (last.get("error") or job_id), code="E13_dub_failed")
        time.sleep(POLL_INTERVAL_S)
    return client.err_envelope(
        "%s Still going (job %s). Check back later. The job keeps its progress."
        % ((started_msg + " " if started_msg else ""), job_id),
        code="E_dub_pending", hint="Poll /batch/jobs/%s" % job_id)


def vs_status(args, **kwargs):
    """Readiness check: setup/status + engines + model/system. Returns JSON string."""
    try:
        args = dict(args or {}) if args else {}
        base_url = client.normalize_base_url(_cfg("base_url", args, kwargs, client.DEFAULT_BASE_URL))

        probe = client.api_get(base_url, "/setup/status", timeout=client.PROBE_TIMEOUT_S)
        if client.is_connection_failure(probe):
            return client.ok_envelope({
                "ready": False,
                "message": client.server_down_error(base_url),
            })

        setup = client.parse_json_body(probe) or {}
        engines, engines_tts, model, sysinfo, recent_errors = None, None, None, None, None
        for path, slot in (("/engines", "engines"), ("/engines/tts", "engines_tts"),
                           ("/model/status", "model"), ("/system/info", "sysinfo"),
                           ("/system/errors/recent", "recent_errors")):
            r = client.api_get(base_url, path, timeout=client.PROBE_TIMEOUT_S)
            if r.get("status") == 200:
                val = client.parse_json_body(r)
                if slot == "engines":
                    engines = val
                elif slot == "engines_tts":
                    engines_tts = val
                elif slot == "model":
                    model = val
                elif slot == "sysinfo":
                    sysinfo = val
                elif slot == "recent_errors":
                    recent_errors = val

        n_voices = None
        try:
            pr = client.api_get(base_url, "/profiles", timeout=client.PROBE_TIMEOUT_S)
            pp = client.parse_json_body(pr)
            if isinstance(pp, dict) and isinstance(pp.get("profiles"), list):
                n_voices = len(pp["profiles"])
            elif isinstance(pp, list):
                n_voices = len(pp)
        except Exception:
            pass

        missing = setup.get("missing") or []
        models_ready = setup.get("models_ready")
        ready = bool(models_ready) if models_ready is not None else not missing
        if ready:
            engine_name = ""
            try:
                if isinstance(engines, dict):
                    engine_name = (engines.get("active") or engines.get("engine") or "")
            except Exception:
                pass
            msg = ("VoiceStudio is ready. Engine: %s. Voices available: %s. Disk: %s free."
                   % (engine_name or "unknown",
                      n_voices if n_voices is not None else "unknown",
                      ("%s GB" % setup.get("disk_free_gb"))
                      if setup.get("disk_free_gb") is not None else "unknown"))
            return client.ok_envelope({
                "ready": True, "setup": setup,
                "engines": engines, "engines_tts": engines_tts,
                "model": model, "system": sysinfo,
                "voices_available": n_voices,
                "message": msg,
            })
        fix = "Missing: %s." % ", ".join(missing) if missing else "Models still loading."
        return client.ok_envelope({
            "ready": False, "setup": setup,
            "engines": engines, "model": model, "system": sysinfo,
            "recent_errors": recent_errors,
            "message": "VoiceStudio is not fully ready: %s "
                       "Wait a little and retry, or check the VoiceStudio app. "
                       "Run this command again to see when it is back." % fix,
        })
    except Exception as e:  # never raise to the loop
        return client.err_envelope("Could not check VoiceStudio status: %s" % e,
                                   code="E_exception")
