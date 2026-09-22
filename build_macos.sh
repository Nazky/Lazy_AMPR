#!/usr/bin/env bash
# Native macOS release build. Produces an ad-hoc signed Lazy_AMPR.app for the
# architecture of the host (arm64 or x86_64) plus a zip and SHA-256 manifest.
# Mirrors build_linux.sh; see README "Build for macOS".
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
parent_dir="$(dirname -- "$project_dir")"
bootstrap_python="${PYTHON:-python3}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "build_macos.sh must run on macOS." >&2
    exit 1
fi

if ! "$bootstrap_python" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>/dev/null; then
    echo "Python 3.12 is required. Set PYTHON=python3.12 (found: $("$bootstrap_python" --version 2>&1 || echo unavailable))." >&2
    exit 1
fi

version="$(cd -- "$project_dir" && "$bootstrap_python" -c 'from version import VERSION; print(VERSION)' 2>/dev/null || true)"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)?$ ]]; then
    echo "Invalid application version: ${version:-unavailable}" >&2
    exit 1
fi

# macOS realpath has no -m (the path may not exist yet), so normalise in Python.
abspath() {
    "$bootstrap_python" -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$1"
}

arch="$(uname -m)"
release_base="$(abspath "${LAZY_AMPR_RELEASE_BASE:-$parent_dir/release}")"
requested_output="${1:-$release_base/$version-macos-$arch}"
release_root="$(abspath "$requested_output")"
if [[ "$(dirname -- "$release_root")" != "$release_base" || -z "$(basename -- "$release_root")" ]]; then
    echo "Refusing to clean unexpected release path: $release_root" >&2
    exit 1
fi

build_venv="${LAZY_AMPR_BUILD_VENV:-$project_dir/.venv-macos}"
if [[ ! -x "$build_venv/bin/python" ]]; then
    "$bootstrap_python" -m venv "$build_venv"
    "$build_venv/bin/python" -m pip install -r "$project_dir/requirements-build.txt"
fi
python="$build_venv/bin/python"

work="$release_root/work"
dist="$release_root/dist"
app="$dist/Lazy_AMPR.app"
workers="$app/Contents/Resources/workers"
archive="$release_root/Lazy_AMPR-$version-macOS-$arch.zip"

# Signing identity. "-" is ad-hoc. Lazy_AMPR.spec reads the same variables.
identity="${LAZY_AMPR_CODESIGN_IDENTITY:--}"
sign() {
    /usr/bin/codesign --force --sign "$identity" --timestamp=none "$@"
}
# --- Notarization hook (not enabled) -----------------------------------------
# To ship a Gatekeeper-clean build, export
#   LAZY_AMPR_CODESIGN_IDENTITY="Developer ID Application: <name> (<team>)"
#   LAZY_AMPR_ENTITLEMENTS="$project_dir/resources/entitlements.plist"
# (entitlements need com.apple.security.cs.allow-unsigned-executable-memory and
# com.apple.security.cs.disable-library-validation for CPython), change sign()
# to pass --options runtime --entitlements "$LAZY_AMPR_ENTITLEMENTS" and drop
# --timestamp=none, move the worker tree from Contents/Resources to
# Contents/Frameworks (notarization rejects Mach-O under Resources), then after
# the zip is written run:
#   xcrun notarytool submit "$archive" --keychain-profile <profile> --wait
#   xcrun stapler staple "$app"   # and re-create the zip
# ------------------------------------------------------------------------------

rm -rf -- "$release_root"
mkdir -p -- "$work" "$dist"
cd -- "$project_dir"

# Build with PyInstaller. A failed bundle signature must fail the build rather
# than be logged as a warning.
export PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR=1
"$python" -m PyInstaller --noconfirm --clean --workpath "$work" --distpath "$dist" Lazy_AMPR.spec
"$python" -m PyInstaller --noconfirm --clean --workpath "$work" --distpath "$dist" ampr_pack.spec
"$python" -m PyInstaller --noconfirm --clean --workpath "$work" --distpath "$dist" ampr_pack_profile.spec

if [[ ! -d "$app" ]]; then
    echo "PyInstaller did not produce $app" >&2
    exit 1
fi

# Setup worker binaries. utils/tool_runner.py looks for
# <dir of executable>/workers/<name>/<name>, i.e. Contents/MacOS/workers. The
# real files live under Contents/Resources (non-Mach-O files under MacOS or
# Frameworks would get xattr-stored signatures that a zip drops) and are
# reached through a relative symlink, the same technique PyInstaller uses for
# its own data files.
mkdir -p -- "$workers"
cp -a -- "$dist/ampr_pack" "$workers/"
cp -a -- "$dist/ampr_pack_profile" "$workers/"
ln -s ../Resources/workers "$app/Contents/MacOS/workers"
chmod +x \
    "$app/Contents/MacOS/Lazy_AMPR" \
    "$workers/ampr_pack/ampr_pack" \
    "$workers/ampr_pack_profile/ampr_pack_profile"

# Code sign inside-out. PyInstaller already ad-hoc signed every binary, but
# copying the workers into the bundle invalidated the bundle seal.
echo "Signing with identity: $identity"
find "$workers" -type f \( -name '*.dylib' -o -name '*.so' \) -print0 \
    | xargs -0 /usr/bin/codesign --force --sign "$identity" --timestamp=none
while IFS= read -r -d '' framework; do
    sign "$framework"
done < <(find "$workers" -type d -name '*.framework' -print0)
sign "$workers/ampr_pack/ampr_pack" "$workers/ampr_pack_profile/ampr_pack_profile"
sign "$app"

/usr/bin/codesign --verify --deep --strict --verbose=1 "$app"
if xattr -lr "$app" 2>/dev/null | grep -q 'com\.apple\.cs\.'; then
    echo "Extended-attribute signatures found inside the bundle; a zip would break them." >&2
    exit 1
fi

# Smoke checks before archiving.
"$workers/ampr_pack/ampr_pack" --help > /dev/null
if [[ -z "${LAZY_AMPR_SKIP_SMOKE:-}" ]]; then
    QT_QPA_PLATFORM=offscreen "$app/Contents/MacOS/Lazy_AMPR" --smoke-test
fi

# Archive with ditto so symlinks, permissions and the bundle layout survive.
ditto -c -k --keepParent "$app" "$archive"

# Generate checksums (macOS has shasum, not sha256sum)
(
    cd -- "$release_root"
    shasum -a 256 "$(basename -- "$archive")" > SHA256SUMS.txt
)

echo "Built $archive"
echo "Size: $(du -h "$archive" | cut -f1)"
cat -- "$release_root/SHA256SUMS.txt"
