#!/bin/bash
# VoiceStudio plugin test runner (CI parity: temp HERMES_HOME isolation,
# never touches the real ~/.hermes/). Run from the repo root.
set -euo pipefail
LANE="$(cd "$(dirname "$0")" && pwd)"
export HERMES_HOME="$(mktemp -d "${TMPDIR:-/tmp}/vs-plugin-test-home.XXXXXX")"
trap 'rm -rf "$HERMES_HOME"' EXIT
export TZ=UTC
export PYTHONPATH="$LANE${PYTHONPATH:+:$PYTHONPATH}"
cd "$LANE"
python3 -m pytest tests/test_vs_tools.py "$@"
