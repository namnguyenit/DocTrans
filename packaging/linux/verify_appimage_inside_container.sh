#!/usr/bin/env bash
set -euo pipefail

PACKAGE=/package/readDoc-1.0.0-Linux-x86_64.AppImage
TEST_PDF=/test/80-80022-8_REV_AA_Qualcomm_Linux_Interfaces_Guide.pdf
APPDIR=/tmp/readDoc-final.AppDir

(cd /package && sha256sum --check readDoc-1.0.0-Linux-x86_64.AppImage.sha256)
file "$PACKAGE"
# Type-2 AppImages contain one SquashFS magic constant in the runtime itself;
# the second occurrence is the appended filesystem superblock.
offset="$(grep -abo hsqs "$PACKAGE" | sed -n '2p' | cut -d: -f1)"
test -n "$offset"
rm -rf "$APPDIR"
unsquashfs -q -o "$offset" -d "$APPDIR" "$PACKAGE"

export LD_LIBRARY_PATH="$APPDIR/usr/lib"
export PYTHONHOME="$APPDIR/usr"
export PYTHONPATH="$APPDIR/usr/lib/python3.10/site-packages"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export READDOC_RESOURCE_DIR="$APPDIR/usr/share/readDoc"
export READDOC_NMT_MODEL="$READDOC_RESOURCE_DIR/model"
export READDOC_NMT_TOKENIZER="$READDOC_RESOURCE_DIR/tokenizer"
export READDOC_NMT_BACKEND=ctranslate2
export READDOC_NMT_INTRA_THREADS=8
export READDOC_CACHE_DB=/tmp/readDoc-final-test.sqlite3

"$APPDIR/usr/bin/python3" -c \
    'import fitz, ctranslate2, transformers, sentencepiece; print("Final AppImage Python imports OK")'

"$APPDIR/usr/bin/python3" \
    "$READDOC_RESOURCE_DIR/extract_pdf.py" --json "$TEST_PDF" \
    > /tmp/readDoc-final-layout.json
"$APPDIR/usr/bin/python3" -c \
    'import json; p=json.load(open("/tmp/readDoc-final-layout.json"))["pages"]; print("PDF pages=%d, images=%d, tables=%d" % (len(p), sum(x.count("[[READDOC_IMAGE:") for x in p), sum(x.count("[[READDOC_TABLE:") for x in p))); assert len(p)==150'

printf '%s\n' \
    '{"id":1,"text":"The kernel driver coordinates power states and concurrent requests."}' | \
    "$APPDIR/usr/bin/python3" "$READDOC_RESOURCE_DIR/local_nmt_daemon.py" | \
    tee /tmp/readDoc-final-nmt.log
grep -q '"available": true' /tmp/readDoc-final-nmt.log
grep -q '"translated":' /tmp/readDoc-final-nmt.log

set +e
QT_QPA_PLATFORM=offscreen timeout 15 \
    "$APPDIR/AppRun" --bilingual "$TEST_PDF" \
    > /tmp/readDoc-final-gui.log 2>&1
gui_status=$?
set -e
if [[ "$gui_status" -ne 124 ]]; then
    cat /tmp/readDoc-final-gui.log
    echo "GUI exited unexpectedly with status $gui_status" >&2
    exit 1
fi
if grep -Eqi 'could not load the qt platform plugin|error while loading shared libraries' \
        /tmp/readDoc-final-gui.log; then
    cat /tmp/readDoc-final-gui.log
    exit 1
fi
echo "Final AppImage GUI startup OK (held for 15 seconds)."
