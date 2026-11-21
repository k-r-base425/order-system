#!/bin/zsh
cd "${0:A:h}"
codex_python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
runtime=""
for candidate in ".venv/bin/python3" "$codex_python" "$(command -v python3)"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then runtime="$candidate"; break; fi
done
if [[ -z "$runtime" ]] || ! "$runtime" -c "import PIL, reportlab" 2>/dev/null; then
  echo "必要なライブラリ（Pillow・ReportLab）が見つかりません。"
  echo "次のコマンドで準備してから、もう一度開いてください。"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
exec "$runtime" app.py --open
