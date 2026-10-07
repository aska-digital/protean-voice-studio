"""VoiceStudio sidecar-server HTTP layer — no VS semantics here.

Thin stdlib-only client (urllib) for the already-running VoiceStudio server.
Transport rules (architecture §2, LOCKED):
- base URL from plugin settings, default http://127.0.0.1:3900
- short connect timeout (~3 s) for the availability probe
- long read timeout (>= 600 s) for generation calls
- artifacts stay on disk; this layer returns bytes + headers, never blobs in envelopes.
"""

import io
import json
import mimetypes
import os
import urllib.error
import urllib.request
import uuid

DEFAULT_BASE_URL = "http://127.0.0.1:3900"
PROBE_TIMEOUT_S = 3
DEFAULT_READ_TIMEOUT_S = 600

SETUP_STATUS_PATH = "/setup/status"


def normalize_base_url(raw, default=DEFAULT_BASE_URL):
    """Return a clean base URL with no trailing slash."""
    if not raw or not str(raw).strip():
        return default
    return str(raw).strip().rstrip("/")


def _read_response(resp):
    return {
        "status": resp.status,
        "body": resp.read(),
        "headers": {k.lower(): v for k, v in resp.headers.items()},
    }


def api_get(base_url, path, timeout=PROBE_TIMEOUT_S):
    """GET path. Returns dict(status, body, headers) or dict(error=...).

    Never raises: URLError/timeout surface as {"error": ..., "kind": ...}.
    """
    url = normalize_base_url(base_url) + path
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _read_response(resp)
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return {"status": e.code, "body": body, "headers": {}, "error": "http_%d" % e.code}
    except Exception as e:
        return {"error": str(e), "kind": type(e).__name__}


def api_post_json(base_url, path, payload, timeout=DEFAULT_READ_TIMEOUT_S):
    """POST JSON payload. Same never-raise contract as api_get."""
    url = normalize_base_url(base_url) + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _read_response(resp)
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return {"status": e.code, "body": body, "headers": {}, "error": "http_%d" % e.code}
    except Exception as e:
        return {"error": str(e), "kind": type(e).__name__}


def api_post_multipart(base_url, path, fields, files=None, timeout=DEFAULT_READ_TIMEOUT_S):
    """POST multipart/form-data.

    fields: {name: str value}; files: {name: (filename, bytes, content_type?)}.
    Same never-raise contract as api_get.
    """
    files = files or {}
    boundary = "vs%s" % uuid.uuid4().hex
    buf = io.BytesIO()
    for name, value in (fields or {}).items():
        if value is None:
            continue
        buf.write(("--%s\r\n" % boundary).encode())
        buf.write(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode())
        buf.write(str(value).encode("utf-8"))
        buf.write(b"\r\n")
    for name, spec in files.items():
        filename, content = spec[0], spec[1]
        ctype = spec[2] if len(spec) > 2 and spec[2] else (
            mimetypes.guess_type(filename)[0] or "application/octet-stream")
        buf.write(("--%s\r\n" % boundary).encode())
        buf.write(
            ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
             % (name, filename)).encode())
        buf.write(("Content-Type: %s\r\n\r\n" % ctype).encode())
        buf.write(content if isinstance(content, bytes) else str(content).encode("utf-8"))
        buf.write(b"\r\n")
    buf.write(("--%s--\r\n" % boundary).encode())

    url = normalize_base_url(base_url) + path
    req = urllib.request.Request(
        url, data=buf.getvalue(), method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _read_response(resp)
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return {"status": e.code, "body": body, "headers": {}, "error": "http_%d" % e.code}
    except Exception as e:
        return {"error": str(e), "kind": type(e).__name__}


def is_available(base_url, timeout=PROBE_TIMEOUT_S):
    """Availability probe: GET /setup/status 200 within ~3 s (architecture §2)."""
    try:
        r = api_get(base_url, SETUP_STATUS_PATH, timeout=timeout)
        return r.get("status") == 200
    except Exception:
        return False


def parse_json_body(result):
    """Best-effort JSON decode of a transport result body; None on failure."""
    try:
        raw = result.get("body") or b""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if not raw.strip():
            return None
        return json.loads(raw)
    except Exception:
        return None


# ---- JSON envelopes (registry contract: handlers return JSON strings) ----

def ok_envelope(data, audio_path=None):
    env = {"success": True, "data": data}
    if audio_path:
        env["audio_path"] = audio_path
    return json.dumps(env)


def err_envelope(message, code=None, hint=None):
    env = {"success": False, "error": message}
    if code:
        env["code"] = code
    if hint:
        env["hint"] = hint
    return json.dumps(env)


def is_connection_failure(result):
    """True when the transport result means 'server unreachable' (E1)."""
    if not isinstance(result, dict):
        return True
    if result.get("status") == 200:
        return False
    return "error" in result and "status" not in result


# ---- UX error strings (ux-spec §Error catalog, Frida-drafted, proofread-pending) ----

def server_down_error(base_url):
    return (
        "I could not reach VoiceStudio at %s. "
        "Start the VoiceStudio app, or check the address in settings. "
        "Then try again. Run /vs-status to see when it is back."
        % normalize_base_url(base_url)
    )


def unknown_voice_error(name):
    return (
        "I do not know a voice called '%s'. "
        "Run /vs-voices --search %s to find it, or make one with /vs-design."
        % (name, name)
    )


def save_bytes(data, out_dir, stem, ext):
    """Persist artifact bytes to disk; return the absolute path."""
    out_dir = os.path.abspath(os.path.expanduser(out_dir or "."))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s.%s" % (stem, ext.lstrip(".")))
    with open(path, "wb") as f:
        f.write(data)
    return path
