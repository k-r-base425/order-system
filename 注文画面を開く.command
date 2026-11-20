#!/bin/zsh
cd "${0:A:h}"
runtime="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$runtime" ]]; then runtime=python3; fi
exec "$runtime" app.py --open
