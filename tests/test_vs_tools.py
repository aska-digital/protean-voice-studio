"""VoiceStudio plugin tests — mocked HTTP (unit) + registration contract.

Run:  python -m pytest tests/test_vs_tools.py   (from the voicestudio dir,
      or via ../../run_tests.sh for HERMES_HOME isolation parity)
Live-server tests are NOT in this file (owner runs them separately against
localhost:3900); everything here passes with no server and no network.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_LANE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# _LANE is .../vs-plugin-build/voicestudio; package root is its parent.
_PKG_ROOT = os.path.dirname(_LANE)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from voicestudio import client as vc
from voicestudio import tools_speak, tools_design, tools_longform, tools_dub
from voicestudio import schemas as S
from voicestudio import parse_command_args
import voicestudio as plugin


def _audio_result(body=b"FAKEAUDIO", headers=None):
    return {"status": 200, "body": body,
            "headers": headers or {"content-type": "audio/mpeg", "x-seed": "123"}}


class EnvelopeTests(unittest.TestCase):
    def test_ok_and_err_are_json_strings(self):
        ok = vc.ok_envelope({"a": 1}, audio_path="/tmp/x.mp3")
        err = vc.err_envelope("boom", code="E1_server_down")
        self.assertIsInstance(ok, str)
        self.assertIsInstance(err, str)
        self.assertTrue(json.loads(ok)["success"])
        self.assertFalse(json.loads(err)["success"])
        self.assertEqual(json.loads(err)["code"], "E1_server_down")

    def test_is_connection_failure(self):
        self.assertTrue(vc.is_connection_failure({"error": "refused", "kind": "URLError"}))
        self.assertFalse(vc.is_connection_failure({"status": 200, "body": b"x", "headers": {}}))
        self.assertFalse(vc.is_connection_failure({"status": 422, "body": b"x",
                                                   "headers": {}, "error": "http_422"}))


class SpeakTests(unittest.TestCase):
    def test_success_envelope_and_json_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("voicestudio.client.api_post_multipart",
                            return_value=_audio_result()) as m:
                raw = tools_speak.vs_speak(
                    {"text": "Hello there.", "voice": "c79141c4"},
                    base_url="http://127.0.0.1:3900", out_dir=tmp)
                self.assertIsInstance(raw, str)
                env = json.loads(raw)
                self.assertTrue(env["success"])
                self.assertTrue(env["audio_path"].endswith(".mp3"))
                self.assertTrue(os.path.isfile(env["audio_path"]))
                self.assertEqual(env["data"]["seed"], "123")
                # multipart fields carry profile_id (LOCKED /generate contract)
                _, fields = m.call_args[0][0], m.call_args[0][1]
                posted = m.call_args[0][2]
                self.assertEqual(posted["profile_id"], "c79141c4")
                self.assertEqual(posted["text"], "Hello there.")

    def test_over_limit_E3(self):
        raw = tools_speak.vs_speak({"text": "x" * 6001, "voice": "v"},
                                   base_url="http://x:1")
        env = json.loads(raw)
        self.assertFalse(env["success"])
        self.assertEqual(env["code"], "E3_over_limit")

    def test_speed_out_of_range_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("voicestudio.client.api_post_multipart",
                            return_value=_audio_result()) as m:
                raw = tools_speak.vs_speak(
                    {"text": "Hi.", "voice": "v", "speed": 99},
                    base_url="http://127.0.0.1:3900", out_dir=tmp)
                env = json.loads(raw)
                self.assertTrue(env["success"])
                self.assertIn("note", env["data"])
                self.assertEqual(m.call_args[0][2]["speed"], "1.0")

    def test_server_down_E1(self):
        with mock.patch("voicestudio.client.api_post_multipart",
                        return_value={"error": "refused", "kind": "URLError"}):
            raw = tools_speak.vs_speak({"text": "Hi.", "voice": "v"},
                                       base_url="http://127.0.0.1:3900")
            env = json.loads(raw)
            self.assertFalse(env["success"])
            self.assertEqual(env["code"], "E1_server_down")
            self.assertIn("127.0.0.1:3900", env["error"])

    def test_422_rejection_envelope(self):
        with mock.patch("voicestudio.client.api_post_multipart",
                        return_value={"status": 422, "body": b'{"detail": "bad"}',
                                      "headers": {}, "error": "http_422"}):
            raw = tools_speak.vs_speak({"text": "Hi.", "voice": "v"},
                                       base_url="http://127.0.0.1:3900")
            self.assertFalse(json.loads(raw)["success"])

    def test_missing_voice_prompts_list(self):
        raw = tools_speak.vs_speak({"text": "Hi."}, base_url="http://x:1",
                                   default_voice="")
        env = json.loads(raw)
        self.assertFalse(env["success"])
        self.assertEqual(env["code"], "E2_voice_missing")


class ListVoicesTests(unittest.TestCase):
    def _fake_get(self, base_url, path, timeout=3):
        if path == "/setup/status":
            return {"status": 200, "body": b'{"models_ready": true}', "headers": {}}
        if path == "/profiles":
            return {"status": 200,
                    "body": json.dumps([{"id": "c79141c4", "name": "DK",
                                         "kind": "clone", "language": "English"}]).encode(),
                    "headers": {}}
        return {"status": 404, "body": b"{}", "headers": {}, "error": "http_404"}

    def test_success_and_search(self):
        with mock.patch("voicestudio.client.api_get", side_effect=self._fake_get):
            env = json.loads(tools_speak.vs_list_voices(
                {"search": "DK"}, base_url="http://127.0.0.1:3900"))
            self.assertTrue(env["success"])
            self.assertEqual(env["data"]["count"], 1)
            self.assertEqual(env["data"]["mine"][0]["id"], "c79141c4")

    def test_empty_is_message_not_error(self):
        with mock.patch("voicestudio.client.api_get", side_effect=self._fake_get):
            env = json.loads(tools_speak.vs_list_voices(
                {"search": "zzz-no-such-voice"}, base_url="http://127.0.0.1:3900"))
            self.assertTrue(env["success"])
            self.assertEqual(env["data"]["count"], 0)

    def test_down_E1(self):
        with mock.patch("voicestudio.client.api_get",
                        return_value={"error": "refused", "kind": "URLError"}):
            env = json.loads(tools_speak.vs_list_voices({}, base_url="http://x:1"))
            self.assertEqual(env["code"], "E1_server_down")


class DesignTests(unittest.TestCase):
    def test_missing_name(self):
        env = json.loads(tools_design.vs_design_voice(
            {"describe": "warm voice"}, base_url="http://x:1"))
        self.assertFalse(env["success"])

    def test_describe_xor_sample(self):
        env = json.loads(tools_design.vs_design_voice(
            {"describe": "x", "sample": "y.wav", "name": "N"}, base_url="http://x:1"))
        self.assertFalse(env["success"])

    def test_vague_description_E5(self):
        with mock.patch("voicestudio.client.api_post_json",
                        return_value={"status": 200,
                                      "body": b'{"vd_states": {}, "unmatched": ["florp"]}',
                                      "headers": {}}):
            env = json.loads(tools_design.vs_design_voice(
                {"describe": "florp", "name": "N"}, base_url="http://127.0.0.1:3900"))
            self.assertFalse(env["success"])
            self.assertEqual(env["code"], "E5_vague_description")

    def test_describe_save_roundtrip(self):
        desc = {"status": 200,
                "body": json.dumps({"vd_states": {"Gender": "Female"},
                                    "unmatched": []}).encode(), "headers": {}}
        prof = {"status": 200, "body": json.dumps({"id": "new1"}).encode(),
                "headers": {}}
        fake_preview = json.dumps({"success": True, "data": {"path": "/tmp/p.mp3"},
                                   "audio_path": "/tmp/p.mp3"})
        with mock.patch("voicestudio.client.api_post_json",
                        side_effect=[desc, prof]), \
             mock.patch("voicestudio.client.api_post_multipart",
                        return_value=prof), \
             mock.patch("voicestudio.tools_speak.vs_speak", return_value=fake_preview):
            env = json.loads(tools_design.vs_design_voice(
                {"describe": "warm young female", "name": "Narrator"},
                base_url="http://127.0.0.1:3900", out_dir="/tmp"))
            self.assertTrue(env["success"])
            self.assertEqual(env["data"]["id"], "new1")

    def test_bad_sample_E6(self):
        env = json.loads(tools_design.vs_design_voice(
            {"sample": "/no/such/file.wav", "name": "N"}, base_url="http://x:1"))
        self.assertEqual(env["code"], "E6_bad_sample")


class LongformTests(unittest.TestCase):
    def test_unsupported_markup_E10(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# Ch1\n\nShe [sigh] softly.\n")
            path = f.name
        try:
            env = json.loads(tools_longform.vs_longform(
                {"file": path, "voice": "v"}, base_url="http://x:1"))
            self.assertFalse(env["success"])
            self.assertEqual(env["code"], "E10_unsupported_markup")
        finally:
            os.unlink(path)

    def test_unsupported_markup_E10_padded(self):
        for variant in ("[sigh ]", "[ sigh]", "[ sigh ]", "[SIGH  ]"):
            with self.subTest(variant=variant):
                with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
                    f.write("# Ch1\n\nShe %s softly.\n" % variant)
                    path = f.name
                try:
                    env = json.loads(tools_longform.vs_longform(
                        {"file": path, "voice": "v"}, base_url="http://x:1"))
                    self.assertFalse(env["success"])
                    self.assertEqual(env["code"], "E10_unsupported_markup")
                finally:
                    os.unlink(path)
                hits = tools_longform.find_unsupported_markup("She %s softly." % variant)
                self.assertTrue(hits, variant)

    def test_missing_file(self):
        env = json.loads(tools_longform.vs_longform(
            {"file": "/no/such.md", "voice": "v"}, base_url="http://x:1"))
        self.assertFalse(env["success"])

    def test_chapter_count_helper(self):
        self.assertEqual(tools_longform.count_chapters("# A\ntext\n# B\n"), ["A", "B"])
        self.assertEqual(tools_longform.count_chapters("## not a chapter\n"), [])

    def test_plan_render_poll_roundtrip(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# Ch1\n\nHello. [pause 400ms]\n")
            path = f.name
        try:
            plan = {"status": 200, "body": b'{"chapters": 1}', "headers": {}}
            enq = {"status": 200, "body": b'{"job_id": "j1"}', "headers": {}}
            done = {"status": 200,
                    "body": json.dumps({"job_id": "j1", "status": "done",
                                         "destination_path": "/tmp/ep.m4b"}).encode(),
                    "headers": {}}
            with mock.patch("voicestudio.client.api_post_json",
                            side_effect=[plan, enq]), \
                 mock.patch("voicestudio.client.api_get", return_value=done):
                env = json.loads(tools_longform.vs_longform(
                    {"file": path, "voice": "v"}, base_url="http://127.0.0.1:3900"))
                self.assertTrue(env["success"])
                self.assertEqual(env["audio_path"], "/tmp/ep.m4b")
        finally:
            os.unlink(path)


class DubStatusTests(unittest.TestCase):
    def test_bad_video_E11(self):
        env = json.loads(tools_dub.vs_dub(
            {"video": "/no/such.mp4", "langs": "es"}, base_url="http://x:1"))
        self.assertEqual(env["code"], "E11_bad_video")

    def test_no_langs_E12(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            env = json.loads(tools_dub.vs_dub(
                {"video": f.name, "langs": ""}, base_url="http://x:1"))
            self.assertEqual(env["code"], "E12_no_langs")

    def test_status_ready(self):
        def fake_get(base_url, path, timeout=3):
            bodies = {
                "/setup/status": {"models_ready": True, "missing": [],
                                  "disk_free_gb": 100},
                "/engines": {"active": "test-engine"},
                "/profiles": [{"id": "a", "name": "A"}],
            }
            if path in bodies:
                return {"status": 200, "body": json.dumps(bodies[path]).encode(),
                        "headers": {}}
            return {"status": 404, "body": b"{}", "headers": {}, "error": "http_404"}
        with mock.patch("voicestudio.client.api_get", side_effect=fake_get):
            env = json.loads(tools_dub.vs_status({}, base_url="http://127.0.0.1:3900"))
            self.assertTrue(env["success"])
            self.assertTrue(env["data"]["ready"])

    def test_status_down(self):
        with mock.patch("voicestudio.client.api_get",
                        return_value={"error": "refused", "kind": "URLError"}):
            env = json.loads(tools_dub.vs_status({}, base_url="http://x:1"))
            self.assertTrue(env["success"])
            self.assertFalse(env["data"]["ready"])


class CheckFnTests(unittest.TestCase):
    def test_false_when_unreachable(self):
        with mock.patch("voicestudio.client.api_get",
                        return_value={"error": "refused", "kind": "URLError"}):
            self.assertFalse(vc.is_available("http://127.0.0.1:9", timeout=1))

    def test_true_on_200(self):
        with mock.patch("voicestudio.client.api_get",
                        return_value={"status": 200, "body": b"{}",
                                      "headers": {}}):
            self.assertTrue(vc.is_available("http://127.0.0.1:3900", timeout=1))


class RegistrationTests(unittest.TestCase):
    class FakeCtx:
        def __init__(self):
            self.config = {"base_url": "http://127.0.0.1:3900",
                           "default_voice": "", "default_engine": "",
                           "timeout_s": 600}
            self.tools = []
            self.commands = []
            self.skills = []

        def get_config(self, key, default=None):
            return self.config.get(key, default)

        def register_tool(self, name, toolset=None, schema=None,
                          handler=None, check_fn=None, **kw):
            self.tools.append((name, toolset, schema, handler, check_fn))

        def register_command(self, name, handler, description=""):
            self.commands.append((name, handler, description))

        def register_skill(self, name, path):
            self.skills.append((name, path))

    def test_six_tools_six_commands_one_skill(self):
        ctx = self.FakeCtx()
        plugin.register(ctx)
        self.assertEqual(len(ctx.tools), 6)
        self.assertEqual(len(ctx.commands), 6)
        self.assertEqual(len(ctx.skills), 1)
        self.assertEqual(
            sorted(t[0] for t in ctx.tools),
            ["vs_design_voice", "vs_dub", "vs_list_voices",
             "vs_longform", "vs_speak", "vs_status"])
        self.assertEqual(
            sorted(c[0] for c in ctx.commands),
            ["vs-design", "vs-dub", "vs-longform", "vs-speak", "vs-status", "vs-voices"])
        # manifest <-> registration parity
        import yaml
        manifest = os.path.join(os.path.dirname(plugin.__file__), "plugin.yaml")
        with open(manifest) as f:
            declared = (yaml.safe_load(f) or {}).get("provides_tools", [])
        self.assertEqual(sorted(declared), sorted(t[0] for t in ctx.tools))
        # every handler accepts **kwargs (forward-compat contract)
        import inspect
        for name, _ts, _s, handler, check in ctx.tools:
            self.assertIn("kwargs", inspect.signature(handler).parameters,
                          "handler %s must accept **kwargs" % name)

    def test_command_parses_flags_and_returns_json(self):
        parsed = parse_command_args("--text 'hello world' --voice abc --speed 1.2")
        self.assertEqual(parsed, {"text": "hello world", "voice": "abc", "speed": "1.2"})
        ctx = self.FakeCtx()
        plugin.register(ctx)
        by_name = dict((c[0], c[1]) for c in ctx.commands)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("voicestudio.client.api_post_multipart",
                            return_value=_audio_result()):
                raw = by_name["vs-speak"](
                    "--text hi --voice v", base_url="http://127.0.0.1:3900",
                    out_dir=tmp)
                self.assertTrue(json.loads(raw)["success"])

    def test_all_six_schemas_present(self):
        self.assertEqual(len(S.ALL_SCHEMAS), 6)
        for s in S.ALL_SCHEMAS:
            self.assertTrue(s["name"] and s["description"] and "parameters" in s)


if __name__ == "__main__":
    unittest.main()
