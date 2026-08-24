#!/usr/bin/env bash
#
# OPTIONAL: stamp the owning company into each image's embedded XMP/IPTC fields,
# on your LOCAL COPY only.
#
#   ./tools/tag_metadata.sh ./uploads
#
# Only worth doing if these images will get separated from the folder tree and
# the manifest -- handed to a client, dropped into a DAM, re-uploaded elsewhere.
# The folder tree from organize_by_company.py already answers "whose file is
# this?" for everything else, and costs nothing.
#
# Read this before running:
#   * Embedding REWRITES each file. Checksums change, so do this AFTER
#     verify_download.py has confirmed the download is complete and intact.
#   * NEVER point this at a mounted/synced copy of the live server. It is for
#     your local archive. The server's uploads/ stays untouched.
#   * Only container formats with metadata support are written: JPEG, PNG, TIFF,
#     WebP. ZIP/SVG/extensionless-non-image files are skipped by exiftool.
#   * ~33,000 of these files have no file extension. exiftool identifies them by
#     content, so they are still handled, but check the failure count at the end.
#
set -euo pipefail

UPLOADS="${1:-./uploads}"
MANIFEST="${2:-data/media-manifest.csv}"
TAGCSV="$(mktemp -t tagmap.XXXXXX.csv)"
trap 'rm -f "$TAGCSV"' EXIT

command -v exiftool >/dev/null || { echo "exiftool not installed (brew install exiftool / apt install libimage-exiftool-perl)" >&2; exit 1; }

# Build an exiftool-consumable CSV: one row per file, keyed by SourceFile.
#   Creator / Credit  -- standard XMP+IPTC "who does this belong to" fields that
#                        Bridge, Lightroom, Photo Mechanic and most DAMs display
#   Source            -- the company's WordPress account slug (stable key)
#   Label             -- how the attribution was determined, so a weak inference
#                        stays visible after the CSV is gone
python3 - "$UPLOADS" "$MANIFEST" "$TAGCSV" <<'PY'
import csv, os, sys
uploads, manifest, out = sys.argv[1:4]
n = 0
with open(out, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['SourceFile', 'XMP:Creator', 'IPTC:Credit', 'XMP:Source', 'XMP:Label'])
    for r in csv.DictReader(open(manifest, encoding='utf-8')):
        if not r['file'] or r['file'].startswith('http'):
            continue
        p = os.path.join(uploads, r['file'])
        if not os.path.exists(p):
            continue
        w.writerow([p, r['company_name'], r['company_name'],
                    r['company_slug'], 'attribution:' + r['company_source']])
        n += 1
print('%d files queued for tagging' % n, file=sys.stderr)
PY

# -m   ignore minor format warnings instead of refusing the file
# -P   preserve original filesystem modification date
exiftool -csv="$TAGCSV" -m -P -overwrite_original "$UPLOADS"

echo
echo "Spot-check one file:"
echo "  exiftool -XMP:Creator -IPTC:Credit -XMP:Source -XMP:Label <somefile>"
