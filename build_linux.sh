#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
parent_dir="$(dirname -- "$project_dir")"
bootstrap_python="${PYTHON:-python3}"
version="$(cd -- "$project_dir" && "$bootstrap_python" -c 'from version import VERSION; print(VERSION)' 2>/dev/null || true)"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)?$ ]]; then
    echo "Invalid application version: ${version:-unavailable}" >&2
    exit 1
fi

release_base="$(realpath -m -- "$parent_dir/release")"
requested_output="${1:-$release_base/$version-linux}"
release_root="$(realpath -m -- "$requested_output")"
if [[ "$(dirname -- "$release_root")" != "$release_base" || -z "$(basename -- "$release_root")" ]]; then
    echo "Refusing to clean unexpected release path: $release_root" >&2
    exit 1
fi

build_venv="${LAZY_AMPR_BUILD_VENV:-$project_dir/.venv-linux}"
if [[ ! -x "$build_venv/bin/python" ]]; then
    "$bootstrap_python" -m venv "$build_venv"
    "$build_venv/bin/python" -m pip install -r "$project_dir/requirements-build.txt"
fi
python="$build_venv/bin/python"

work="$release_root/work"
dist="$release_root/dist"
appdir="$release_root/Lazy_AMPR.AppDir"
appimage="$release_root/Lazy_AMPR-$version-x86_64.AppImage"

rm -rf -- "$release_root"
mkdir -p -- "$work" "$dist"
cd -- "$project_dir"

# Build with PyInstaller
"$python" -m PyInstaller --noconfirm --clean --workpath "$work" --distpath "$dist" Lazy_AMPR.spec
"$python" -m PyInstaller --noconfirm --clean --workpath "$work" --distpath "$dist" ampr_pack.spec
"$python" -m PyInstaller --noconfirm --clean --workpath "$work" --distpath "$dist" ampr_pack_profile.spec

# Setup worker binaries
mkdir -p -- "$dist/Lazy_AMPR/workers"
cp -a -- "$dist/ampr_pack" "$dist/Lazy_AMPR/workers/"
cp -a -- "$dist/ampr_pack_profile" "$dist/Lazy_AMPR/workers/"
chmod +x -- \
    "$dist/Lazy_AMPR/Lazy_AMPR" \
    "$dist/Lazy_AMPR/workers/ampr_pack/ampr_pack" \
    "$dist/Lazy_AMPR/workers/ampr_pack_profile/ampr_pack_profile"

# Create AppDir structure
mkdir -p -- "$appdir/usr/bin"
mkdir -p -- "$appdir/usr/lib"
mkdir -p -- "$appdir/usr/share/applications"
mkdir -p -- "$appdir/usr/share/icons/hicolor/256x256/apps"
mkdir -p -- "$appdir/usr/share/metainfo"

# Copy application files
cp -a -- "$dist/Lazy_AMPR/"* "$appdir/usr/bin/"

# Create AppRun script
cat > "$appdir/AppRun" << 'EOF'
#!/bin/bash
SELF="$(readlink -f "$0")"
HERE="$(dirname "$SELF")"

export PATH="$HERE/usr/bin:$PATH"
export LD_LIBRARY_PATH="$HERE/usr/lib:$LD_LIBRARY_PATH"
export QT_PLUGIN_PATH="$HERE/usr/lib/qt5/plugins:$QT_PLUGIN_PATH"
export QML2_IMPORT_PATH="$HERE/usr/lib/qt5/qml:$QML2_IMPORT_PATH"

# Set XDG dirs for portable mode
if [ -z "${XDG_CONFIG_HOME:-}" ]; then
    export XDG_CONFIG_HOME="$HOME/.config"
fi
if [ -z "${XDG_DATA_HOME:-}" ]; then
    export XDG_DATA_HOME="$HOME/.local/share"
fi

exec "$HERE/usr/bin/Lazy_AMPR" "$@"
EOF
chmod +x -- "$appdir/AppRun"

# Create .desktop file
cat > "$appdir/Lazy_AMPR.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Lazy AMPR
GenericName=PS5 Game Compressor
Comment=Compress PS5 games using AMPR and LZ4
Exec=Lazy_AMPR
Icon=lazy_ampr
Categories=Game;Utility;
Terminal=false
StartupNotify=true
X-AppImage-Version=$version
EOF

# Copy .desktop to standard locations
cp -- "$appdir/Lazy_AMPR.desktop" "$appdir/usr/share/applications/Lazy_AMPR.desktop"

# Create/copy icon
# Try to find an icon in the project, otherwise create a placeholder
icon_found=""
for icon_path in "$project_dir/assets/icon.png" "$project_dir/icon.png" "$project_dir/lazy_ampr.png" "$project_dir/resources/icon.png"; do
    if [[ -f "$icon_path" ]]; then
        cp -- "$icon_path" "$appdir/lazy_ampr.png"
        cp -- "$icon_path" "$appdir/usr/share/icons/hicolor/256x256/apps/lazy_ampr.png"
        icon_found="$icon_path"
        break
    fi
done

if [[ -z "$icon_found" ]]; then
    # Create a simple placeholder icon (256x256 blue square with "LA" text)
    if command -v convert &>/dev/null; then
        convert -size 256x256 xc:"#007aff" \
            -fill white -font DejaVu-Sans-Bold -pointsize 96 \
            -gravity center -annotate +0+0 "LA" \
            "$appdir/lazy_ampr.png"
        cp -- "$appdir/lazy_ampr.png" "$appdir/usr/share/icons/hicolor/256x256/apps/lazy_ampr.png"
    else
        # Create minimal PNG with Python
        "$python" -c "
from PIL import Image, ImageDraw, ImageFont
img = Image.new('RGB', (256, 256), '#007aff')
draw = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 96)
except:
    font = ImageFont.load_default()
draw.text((78, 78), 'LA', fill='white', font=font)
img.save('$appdir/lazy_ampr.png')
" 2>/dev/null || {
            # Fallback: create a 1x1 pixel PNG
            printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\r\xe4\xa0\x00\x00\x00\x00IEND\xaeB`\x82' > "$appdir/lazy_ampr.png"
        }
        cp -- "$appdir/lazy_ampr.png" "$appdir/usr/share/icons/hicolor/256x256/apps/lazy_ampr.png"
    fi
fi

# Create AppStream metainfo
cat > "$appdir/usr/share/metainfo/lazy_ampr.appdata.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>lazy_ampr</id>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <name>Lazy AMPR</name>
  <summary>PS5 Game Compressor using AMPR and LZ4</summary>
  <description>
    <p>
      Lazy AMPR is a tool for compressing PS5 games using the AMPR
      (Adaptive Media Packing Runtime) format with LZ4 compression.
      It supports batch processing, automatic TOML profile generation,
      and trace-based optimization.
    </p>
  </description>
  <launchable type="desktop-id">Lazy_AMPR.desktop</launchable>
  <url type="homepage">https://github.com/NazkyYT/Lazy_AMPR</url>
  <releases>
    <release version="$version" date="$(date +%Y-%m-%d)"/>
  </releases>
  <content_rating type="oars-1.1"/>
</component>
EOF

# Download appimagetool if not present
appimagetool="${APPIMAGETOOL:-$project_dir/tools/appimagetool-x86_64.AppImage}"
if [[ ! -x "$appimagetool" ]]; then
    mkdir -p -- "$(dirname -- "$appimagetool")"
    echo "Downloading appimagetool..."
    wget -q "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" -O "$appimagetool" || \
    curl -sL "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" -o "$appimagetool"
    chmod +x -- "$appimagetool"
fi

# Build the AppImage
echo "Building AppImage..."
"$appimagetool" --appimage-extract-and-run \
    "$appdir" \
    "$appimage"

# Generate checksums
(
    cd -- "$release_root"
    sha256sum "$(basename -- "$appimage")" > SHA256SUMS.txt
)

echo "Built $appimage"
echo "Size: $(du -h "$appimage" | cut -f1)"
cat -- "$release_root/SHA256SUMS.txt"

# Optional: also create a tar.gz for users who prefer it
archive="$release_root/Lazy_AMPR-$version-Linux-x86_64.tar.gz"
tar -C "$dist/Lazy_AMPR" -czf "$archive" .
echo "Also built $archive"