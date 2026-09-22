#!/usr/bin/env bash
set -euo pipefail

BUILD_DIR=/tmp/readDoc-build
APPDIR=/out/readDoc.AppDir
rm -rf "$BUILD_DIR" "$APPDIR"

cmake -S /src -B "$BUILD_DIR" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr \
    -DBUILD_TESTING=ON
cmake --build "$BUILD_DIR" --parallel "$(nproc)"
DESTDIR="$APPDIR" cmake --install "$BUILD_DIR"

RESOURCE_DIR="$APPDIR/usr/share/readDoc"
PYTHON_SITE="$APPDIR/usr/lib/python3.10/site-packages"
mkdir -p \
    "$APPDIR/usr/bin" \
    "$APPDIR/usr/lib/qt6/plugins" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
    "$RESOURCE_DIR/model" \
    "$RESOURCE_DIR/tokenizer" \
    "$RESOURCE_DIR/licenses" \
    "$PYTHON_SITE"

# Bundle a fixed Python runtime. The final application does not use system pip,
# Hugging Face cache, Torch, or any online service.
cp -L /usr/bin/python3.10 "$APPDIR/usr/bin/python3"
cp -a /usr/lib/python3.10 "$APPDIR/usr/lib/"
python3 -m pip install --no-cache-dir --disable-pip-version-check \
    --no-index --find-links /opt/readDoc-wheels \
    --target "$PYTHON_SITE" \
    'numpy<2' \
    'PyMuPDF==1.26.3' \
    'ctranslate2==4.6.0' \
    'transformers==4.46.3' \
    'sentencepiece==0.2.0' \
    'protobuf==5.28.3'

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PYTHON_SITE" \
    python3 /src/tests/test_pdf_layout.py

cp -a /model-src/. "$RESOURCE_DIR/model/"
cp -L /tokenizer-src/config.json "$RESOURCE_DIR/tokenizer/config.json"
cp -L /tokenizer-src/sentencepiece.bpe.model \
    "$RESOURCE_DIR/tokenizer/sentencepiece.bpe.model"

cp -L /usr/bin/tesseract "$APPDIR/usr/bin/tesseract"
TESSDATA_FILE="$(find /usr/share/tesseract-ocr -name eng.traineddata -print -quit)"
if [[ -z "$TESSDATA_FILE" ]]; then
    echo "Could not locate Tesseract English language data." >&2
    exit 1
fi
TESSDATA_SOURCE="$(dirname "$TESSDATA_FILE")"
mkdir -p "$APPDIR/usr/share/tesseract-ocr/tessdata"
cp -a "$TESSDATA_SOURCE"/. "$APPDIR/usr/share/tesseract-ocr/tessdata/"

QT_PLUGIN_SOURCE="$(qtpaths6 --query QT_INSTALL_PLUGINS 2>/dev/null || true)"
if [[ -z "$QT_PLUGIN_SOURCE" || ! -d "$QT_PLUGIN_SOURCE" ]]; then
    QT_PLUGIN_SOURCE=/usr/lib/x86_64-linux-gnu/qt6/plugins
fi
for category in \
    platforms imageformats iconengines platforminputcontexts \
    xcbglintegrations tls networkinformation; do
    if [[ -d "$QT_PLUGIN_SOURCE/$category" ]]; then
        cp -a "$QT_PLUGIN_SOURCE/$category" "$APPDIR/usr/lib/qt6/plugins/"
    fi
done

cp /src/packaging/linux/AppRun "$APPDIR/AppRun"
cp /src/packaging/linux/readDoc.desktop "$APPDIR/readDoc.desktop"
cp /src/packaging/linux/readDoc.desktop \
    "$APPDIR/usr/share/applications/readDoc.desktop"
cp /src/packaging/linux/readDoc.svg "$APPDIR/readDoc.svg"
cp /src/packaging/linux/readDoc.svg \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/readDoc.svg"
cp /src/packaging/linux/THIRD_PARTY_NOTICES.md \
    "$RESOURCE_DIR/licenses/THIRD_PARTY_NOTICES.md"
ln -s readDoc.svg "$APPDIR/.DirIcon"
chmod 755 "$APPDIR/AppRun" "$APPDIR/usr/bin/readDoc" \
    "$APPDIR/usr/bin/python3" "$APPDIR/usr/bin/tesseract"

# Collect ELF dependencies recursively. glibc and graphics-driver interfaces
# intentionally remain supplied by the host for Linux compatibility.
LIB_DIR="$APPDIR/usr/lib"
declare -a queue=()
while IFS= read -r -d '' candidate; do
    queue+=("$candidate")
done < <(
    find "$APPDIR/usr/bin" -type f -print0
    find "$APPDIR/usr/lib/qt6/plugins" -type f \
        \( -name '*.so' -o -name '*.so.*' \) -print0
    find "$APPDIR/usr/lib/python3.10" -type f \
        \( -name '*.so' -o -name '*.so.*' \) -print0
)

declare -A scanned=()
cursor=0
while (( cursor < ${#queue[@]} )); do
    binary="${queue[$cursor]}"
    ((cursor += 1))
    [[ -n "${scanned[$binary]:-}" ]] && continue
    scanned[$binary]=1
    file -L "$binary" | grep -q ELF || continue

    while IFS= read -r dependency; do
        [[ -f "$dependency" ]] || continue
        soname="$(basename "$dependency")"
        case "$soname" in
            ld-linux-x86-64.so.2|libc.so.6|libpthread.so.0|libdl.so.2|\
            librt.so.1|libm.so.6|libresolv.so.2|libutil.so.1|\
            libGL.so.1|libGLX.so.0|libOpenGL.so.0|libEGL.so.1|\
            libGLdispatch.so.0|libdrm.so.2)
                continue
                ;;
        esac
        destination="$LIB_DIR/$soname"
        if [[ ! -f "$destination" ]]; then
            cp -L "$dependency" "$destination"
            queue+=("$destination")
        fi
    done < <(
        ldd "$binary" 2>/dev/null | \
            awk '/=> \/.*\(0x/{print $3} /^\/.+\(0x/{print $1}' || true
    )
done

find "$APPDIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$APPDIR/usr/lib/python3.10" -type d \
    \( -name test -o -name tests -o -name idle_test \) \
    -prune -exec rm -rf {} +

# Verify the exact bundled runtime with networking disabled before compression.
env \
    LD_LIBRARY_PATH="$APPDIR/usr/lib" \
    PYTHONHOME="$APPDIR/usr" \
    PYTHONPATH="$PYTHON_SITE" \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    "$APPDIR/usr/bin/python3" -c \
    'import fitz, ctranslate2, transformers, sentencepiece; print("Bundled Python runtime OK")'

printf '%s\n' \
    '{"id":1,"text":"Configure the Linux kernel and verify the device driver status."}' | \
env \
    LD_LIBRARY_PATH="$APPDIR/usr/lib" \
    PYTHONHOME="$APPDIR/usr" \
    PYTHONPATH="$PYTHON_SITE" \
    READDOC_RESOURCE_DIR="$RESOURCE_DIR" \
    READDOC_NMT_MODEL="$RESOURCE_DIR/model" \
    READDOC_NMT_TOKENIZER="$RESOURCE_DIR/tokenizer" \
    READDOC_NMT_BACKEND=ctranslate2 \
    READDOC_NMT_INTRA_THREADS=8 \
    READDOC_CACHE_DB=/tmp/readDoc-package-test.sqlite3 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    "$APPDIR/usr/bin/python3" "$RESOURCE_DIR/local_nmt_daemon.py" | \
    tee /tmp/readDoc-nmt-test.log
grep -q '"available": true' /tmp/readDoc-nmt-test.log
grep -q '"translated":' /tmp/readDoc-nmt-test.log

APPIMAGETOOL=/opt/appimagetool-root/AppRun

OUTPUT=/out/readDoc-1.0.0-Linux-x86_64.AppImage
rm -f "$OUTPUT" "$OUTPUT.sha256"
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$OUTPUT"
chmod 755 "$OUTPUT"
(cd /out && sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256")
file "$OUTPUT"
ls -lh "$OUTPUT" "$OUTPUT.sha256"

# AppDir is generated and very large; retain only the distributable one-file image.
rm -rf "$APPDIR"
if [[ -n "${HOST_UID:-}" && -n "${HOST_GID:-}" ]]; then
    chown "$HOST_UID:$HOST_GID" "$OUTPUT" "$OUTPUT.sha256" || true
fi
