#!/bin/zsh
# Install (or reinstall) the 9:30am daily job: DB update + EDA rebuild + TOTO Slack alert.
#   ./scripts/install_launchd.sh            install / reload
#   ./scripts/install_launchd.sh uninstall  remove
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-$(command -v python3)}"
LABEL=com.toto.daily
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
if [[ "${1:-}" == "uninstall" ]]; then
  rm -f "$DEST"; echo "Removed $LABEL"; exit 0
fi

mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"
sed -e "s#__PYTHON__#$PYTHON#g" -e "s#__ROOT__#$ROOT#g" "$ROOT/launchd/$LABEL.plist.template" > "$DEST"
plutil -lint "$DEST" >/dev/null
launchctl bootstrap "gui/$UID" "$DEST"
echo "Installed $LABEL -> $DEST (python: $PYTHON)"
echo "Run now:   launchctl kickstart gui/$UID/$LABEL"
echo "Logs:      $ROOT/logs/daily.log"
