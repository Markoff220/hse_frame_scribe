#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="$ROOT/dist/linux/build"
PACKAGE_DIR="$BUILD_DIR/VideoNotes-linux-x86_64"

command -v python3 >/dev/null || { echo "Не найден python3" >&2; exit 1; }
command -v cargo >/dev/null || { echo "Не найден cargo. Установите Rust: https://rustup.rs" >&2; exit 1; }
command -v curl >/dev/null || { echo "Не найден curl" >&2; exit 1; }

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/wheel" "$PACKAGE_DIR"

cd "$ROOT"
python3 - "$BUILD_DIR/wheel" <<'PY'
import sys
from setuptools.build_meta import build_wheel

print(build_wheel(sys.argv[1], {}))
PY
WHEEL="$(printf '%s\n' "$BUILD_DIR"/wheel/videonotes-*.whl)"

PYAPP_VERSION="0.29.0"
PYAPP_SOURCE="$BUILD_DIR/pyapp-source"
WHEEL_NAME="$(basename "$WHEEL")"
mkdir -p "$PYAPP_SOURCE"
curl --fail --location --silent --show-error \
  "https://github.com/ofek/pyapp/releases/download/v${PYAPP_VERSION}/source.tar.gz" \
  | tar -xz -C "$PYAPP_SOURCE" --strip-components=1
cp "$WHEEL" "$PYAPP_SOURCE/$WHEEL_NAME"

(
  cd "$PYAPP_SOURCE"
  PYAPP_PROJECT_PATH="$WHEEL_NAME" \
  PYAPP_EXEC_MODULE="videonotes.desktop" \
  PYAPP_IS_GUI=1 \
  PYAPP_PYTHON_VERSION="3.13" \
  cargo build --release
)

install -m 755 "$PYAPP_SOURCE/target/release/pyapp" "$PACKAGE_DIR/videonotes"
install -m 755 "$ROOT/scripts/linux/install.sh" "$PACKAGE_DIR/install.sh"
install -m 644 "$ROOT/scripts/linux/README.md" "$PACKAGE_DIR/README.md"

tar -C "$BUILD_DIR" -czf "$ROOT/dist/VideoNotes-linux-x86_64.tar.gz" "$(basename "$PACKAGE_DIR")"
printf 'Готово: %s\n' "$ROOT/dist/VideoNotes-linux-x86_64.tar.gz"
