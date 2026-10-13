#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.raingist.serve"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
[[ -x "$ROOT/.venv/bin/raingist" ]] || { echo "run 'uv sync' first" >&2; exit 1; }
sed -e "s|@ROOT@|$ROOT|g" -e "s|@HOME@|$HOME|g" "$ROOT/launchd/agent.plist.in" > "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL"
