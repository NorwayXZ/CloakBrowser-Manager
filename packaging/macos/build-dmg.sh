#!/bin/sh
# Build "CloakBrowser Manager.app" and wrap it in a drag-to-install DMG.
#
#   ./packaging/macos/build-dmg.sh
#
# Output: build/macos/CloakBrowser-Manager-<version>-<arch>.dmg
# Only touches build/macos and frontend/dist; never the profile data directory.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
HERE="$ROOT/packaging/macos"
BUILD="$ROOT/build/macos"
VENV="$BUILD/venv"
APP_NAME="CloakBrowser Manager"
ARCH="$(uname -m)"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "[error] DMG builds must run on macOS" >&2
    exit 1
fi

# Bundle version: newest vX.Y.Z tag; build number = commit count; DMG name adds the commit.
VERSION="${CLOAKBROWSER_APP_VERSION:-$(git -C "$ROOT" tag --list 'v[0-9]*' --sort=-v:refname | head -n 1 | sed 's/^v//')}"
VERSION="${VERSION:-0.0.0}"
BUILD_NUMBER="$(git -C "$ROOT" rev-list --count HEAD 2>/dev/null || echo 0)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo local)"
export CLOAKBROWSER_APP_BUILD="$BUILD_NUMBER"
export CLOAKBROWSER_APP_VERSION="$VERSION"
echo "[build] version $VERSION build $BUILD_NUMBER ($COMMIT, $ARCH)"

mkdir -p "$BUILD"
printf '{"version": "%s", "build": "%s", "commit": "%s"}\n' "$VERSION" "$BUILD_NUMBER" "$COMMIT" > "$BUILD/app_version.json"

echo "[build] frontend"
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund && npm run build)

if [ ! -x "$VENV/bin/python" ]; then
    echo "[build] creating build venv"
    python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -q --disable-pip-version-check \
    -r "$ROOT/backend/requirements.txt" \
    -r "$HERE/requirements-build.txt" \
    -c "$ROOT/packaging/constraints.txt"

echo "[build] icon"
ICONSET="$BUILD/AppIcon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
"$VENV/bin/python" "$ROOT/packaging/make_icon.py" "$BUILD/icon-1024.png"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$BUILD/icon-1024.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$BUILD/icon-1024.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUILD/AppIcon.icns"

echo "[build] app bundle"
"$VENV/bin/python" -m PyInstaller --noconfirm --clean \
    --distpath "$BUILD/dist" --workpath "$BUILD/work" \
    "$HERE/CloakBrowserManager.spec"

APP="$BUILD/dist/$APP_NAME.app"
# Ad-hoc signature so Apple Silicon will run the bundle's binaries.
codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP"

echo "[build] dmg"
STAGE="$BUILD/dmg-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="$BUILD/CloakBrowser-Manager-$VERSION-$COMMIT-$ARCH.dmg"
rm -f "$DMG"
# hdiutil occasionally fails with "Resource busy" on CI runners; retry a few times.
attempt=1
until hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null; do
    if [ "$attempt" -ge 5 ]; then
        echo "[error] hdiutil create failed" >&2
        exit 1
    fi
    attempt=$((attempt + 1))
    sleep 5
done
rm -rf "$STAGE"

echo "[done] $DMG"
