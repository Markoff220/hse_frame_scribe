#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
TARGET="$BIN_DIR/videonotes"

mkdir -p "$BIN_DIR" "$APPS_DIR"
install -m 755 "$SOURCE_DIR/videonotes" "$TARGET"

cat > "$APPS_DIR/videonotes.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VideoNotes
Comment=Конспекты из видео
Exec=$TARGET
Terminal=false
Categories=AudioVideo;Utility;
EOF

printf 'VideoNotes установлен: %s\n' "$TARGET"
printf 'Если приложение не видно в меню, перезапустите сеанс рабочего стола.\n'
