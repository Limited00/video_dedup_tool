#!/usr/bin/env bash
# AppImage 打包脚本（Linux CI 用）
# 用法: bash build_appimage.sh <cpu|gpu> <version>
# 产物: VideoDedupTool-v<version>-linux-x86_64-<cpu|gpu>.AppImage
set -euo pipefail

VARIANT="${1:-cpu}"
VERSION="${2:-1.0.0}"
APP="VideoDedupTool"
APPDIR="${APP}.AppDir"

echo "==> PyInstaller 打包 (onedir, ${VARIANT})"
if [ "$VARIANT" = "gpu" ]; then
  python build.py --onedir --gpu --appname "$APP"
else
  python build.py --onedir --cpu --appname "$APP"
fi

echo "==> 组装 AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "dist/${APP}/"* "$APPDIR/usr/bin/"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/VideoDedupTool" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/${APP}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Video Dedup Tool
Comment=Video deduplication tool
Exec=${APP}
Categories=AudioVideo;Video;
Terminal=false
EOF

echo "==> 下载 appimagetool"
wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -O appimagetool
chmod +x appimagetool

OUT="${APP}-v${VERSION}-linux-x86_64-${VARIANT}.AppImage"
echo "==> 生成 AppImage: ${OUT}"
./appimagetool --appimage-extract-and-run "$APPDIR" "$OUT"

echo "==> 完成"
ls -lh "$OUT"
