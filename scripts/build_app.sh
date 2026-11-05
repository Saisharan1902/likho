#!/bin/zsh
# Builds Likho.app — a small launcher bundle that runs this project's code with its .venv.
#
#   scripts/build_app.sh                 # installs to /Applications/Likho.app
#   scripts/build_app.sh ~/Desktop       # or somewhere else
#
# Code changes take effect next launch (no rebuild needed). Rebuild only if you move the project folder.
set -e
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-/Applications}"
APP="$DEST/Likho.app"
PY="$PROJECT/.venv/bin/python"

[ -x "$PY" ] || { echo "No .venv yet — run ./run.sh once first."; exit 1; }

echo "Building $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# --- Info.plist: menu-bar only app (LSUIElement), mic permission text is required by macOS
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Likho</string>
  <key>CFBundleDisplayName</key><string>Likho</string>
  <key>CFBundleIdentifier</key><string>io.github.saisharan1902.likho</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Likho</string>
  <key>CFBundleIconFile</key><string>Likho</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSMicrophoneUsageDescription</key><string>Likho listens while you hold the dictation key and turns your speech into text.</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
EOF

# --- launcher: a native binary that runs Python as its child, so macOS permissions belong to Likho
# (see scripts/launcher.m for why a script or exec doesn't work)
mkdir -p "$HOME/Library/Logs"
clang -O2 -fobjc-arc -framework Cocoa -o "$APP/Contents/MacOS/Likho" "$PROJECT/scripts/launcher.m" \
  -DPROJECT="\"$PROJECT\"" -DPYTHON="\"$PY\""

# --- icon
ICONSET="$(mktemp -d)/Likho.iconset"
mkdir -p "$ICONSET"
"$PY" "$PROJECT/scripts/make_icon.py" "$ICONSET/icon_512x512@2x.png"
for s in 16 32 128 256 512; do
  sips -z $s $s "$ICONSET/icon_512x512@2x.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$ICONSET/icon_512x512@2x.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Likho.icns"

# --- ad-hoc signature so macOS can remember its permissions
codesign --force --sign - --identifier io.github.saisharan1902.likho "$APP"
touch "$APP"  # refresh Finder's icon cache

echo "Done: $APP"
echo "Logs: ~/Library/Logs/Likho.log"
