"""VoiceStudio Hermes plugin — registration.

Full native plugin `voicestudio`: 6 tools + 6 mirrored slash commands +
1 bundled skill (architecture §5 file-ownership map).
"""

import logging
import shlex
from pathlib import Path

from . import schemas
from . import tools_design, tools_dub, tools_longform, tools_speak
from . import client

logger = logging.getLogger(__name__)

_TOOLSET = "voicestudio"

_HANDLERS = (
    ("vs_speak", schemas.VS_SPEAK, tools_speak.vs_speak, "vs-speak"),
    ("vs_design_voice", schemas.VS_DESIGN_VOICE, tools_design.vs_design_voice, "vs-design"),
    ("vs_list_voices", schemas.VS_LIST_VOICES, tools_speak.vs_list_voices, "vs-voices"),
    ("vs_longform", schemas.VS_LONGFORM, tools_longform.vs_longform, "vs-longform"),
    ("vs_dub", schemas.VS_DUB, tools_dub.vs_dub, "vs-dub"),
    ("vs_status", schemas.VS_STATUS, tools_dub.vs_status, "vs-status"),
)


def parse_command_args(raw_args):
    """Parse '--flag value' style raw command text into an args dict."""
    args = {}
    if not raw_args or not raw_args.strip():
        return args
    try:
        tokens = shlex.split(raw_args)
    except ValueError:
        tokens = raw_args.split()
    key = None
    for tok in tokens:
        if tok.startswith("--"):
            key = tok[2:]
            args[key] = True
        elif key is not None:
            if args.get(key) is True:
                args[key] = tok
            else:
                args[key] = "%s %s" % (args[key], tok)
        # bare positional tokens with no pending flag are ignored
    for k, v in list(args.items()):
        if v == "true":
            args[k] = True
        elif v == "false":
            args[k] = False
    return args


def _make_command_handler(handler):
    def _handle(raw_args="", **kwargs):
        try:
            parsed = parse_command_args(raw_args or "")
            return handler(parsed, **kwargs)
        except Exception as e:  # never raise to the loop
            return client.err_envelope("Command failed: %s" % e, code="E_exception")
    return _handle


def _check_fn_factory(base_url_getter):
    def _check():
        try:
            return client.is_available(base_url_getter())
        except Exception:
            return False
    return _check


def register(ctx):
    """Wire schemas to handlers: 6 tools + 6 commands + 1 skill."""
    base_url = ctx.get_config("base_url", default=client.DEFAULT_BASE_URL)
    default_voice = ctx.get_config("default_voice", default="")
    default_engine = ctx.get_config("default_engine", default="")
    timeout_s = ctx.get_config("timeout_s", default=client.DEFAULT_READ_TIMEOUT_S)

    tools_speak.BASE_URL = base_url
    tools_speak.DEFAULT_VOICE = default_voice
    tools_speak.DEFAULT_ENGINE = default_engine
    tools_speak.TIMEOUT_S = timeout_s

    check = _check_fn_factory(lambda: tools_speak.BASE_URL)

    for tool_name, schema, handler, command in _HANDLERS:
        ctx.register_tool(
            name=tool_name,
            toolset=_TOOLSET,
            schema=schema,
            handler=handler,
            check_fn=check,
        )
        ctx.register_command(
            command,
            _make_command_handler(handler),
            description=schema.get("description", ""),
        )

    skill_md = Path(__file__).parent / "skills" / "voice-studio" / "SKILL.md"
    if skill_md.exists():
        ctx.register_skill("voice-studio", skill_md)

    logger.debug("voicestudio plugin registered: 6 tools, 6 commands, 1 skill")
