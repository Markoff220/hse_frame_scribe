#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-/Applications}"

mkdir -p "$TARGET_DIR"
ditto "$SOURCE_DIR/VideoNotes.app" "$TARGET_DIR/VideoNotes.app"
open "$TARGET_DIR/VideoNotes.app"
printf 'VideoNotes установлен: %s/VideoNotes.app\n' "$TARGET_DIR"
