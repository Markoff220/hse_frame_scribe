#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARCH="$(uname -m)"
BUILD_DIR="$ROOT/dist/macos/build"
PACKAGE_DIR="$BUILD_DIR/VideoNotes-macos-$ARCH"
APP_DIR="$PACKAGE_DIR/VideoNotes.app"
PYAPP_VERSION="0.29.0"

command -v python3 >/dev/null || { echo "Не найден python3" >&2; exit 1; }
command -v cargo >/dev/null || { echo "Не найден cargo. Установите Rust: https://rustup.rs" >&2; exit 1; }
command -v curl >/dev/null || { echo "Не найден curl" >&2; exit 1; }
command -v ditto >/dev/null || { echo "Нужна macOS с утилитой ditto" >&2; exit 1; }

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/wheel" "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cd "$ROOT"
python3 - "$BUILD_DIR/wheel" <<'PY'
import sys
from setuptools.build_meta import build_wheel

print(build_wheel(sys.argv[1], {}))
PY
WHEEL="$(printf '%s\n' "$BUILD_DIR"/wheel/videonotes-*.whl)"
WHEEL_NAME="$(basename "$WHEEL")"
PYAPP_SOURCE="$BUILD_DIR/pyapp-source"
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

install -m 755 "$PYAPP_SOURCE/target/release/pyapp" "$APP_DIR/Contents/MacOS/videonotes"
cat > "$APP_DIR/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleDisplayName</key><string>VideoNotes</string>
  <key>CFBundleExecutable</key><string>videonotes</string>
  <key>CFBundleIdentifier</key><string>org.videonotes.app</string>
  <key>CFBundleName</key><string>VideoNotes</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
</dict></plist>
PLIST
install -m 755 "$ROOT/scripts/macos/install-pyapp.sh" "$PACKAGE_DIR/install.sh"
install -m 644 "$ROOT/scripts/macos/README-pyapp.md" "$PACKAGE_DIR/README.md"

mkdir -p "$ROOT/dist"
ditto -c -k --sequesterRsrc --keepParent "$PACKAGE_DIR" "$ROOT/dist/VideoNotes-macos-$ARCH.zip"
printf 'Готово: %s\n' "$ROOT/dist/VideoNotes-macos-$ARCH.zip"
