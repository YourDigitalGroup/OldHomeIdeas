#!/usr/bin/env bash
#
# Pull wp-content/uploads off the server WITHOUT using server-side disk space.
#
# None of these methods create an archive, staging copy, or temp file on the
# server. Bytes stream straight from the existing files to your machine, so the
# server never needs the ~13 GB of free space that zipping would demand. No file
# in uploads/ is read-only-violated, renamed, or modified.
#
# Usage:  ./tools/fetch_uploads.sh <method> [dest]
# Methods: rsync | rsync-originals | tar | lftp | wget
#
set -euo pipefail

# ---- configure ---------------------------------------------------------------
SSH_USER="${SSH_USER:-youruser}"
SSH_HOST="${SSH_HOST:-findhomeideas.com}"
REMOTE_UPLOADS="${REMOTE_UPLOADS:-/var/www/findhomeideas.com/wp-content/uploads}"
FTP_USER="${FTP_USER:-$SSH_USER}"
FTP_HOST="${FTP_HOST:-$SSH_HOST}"
# ------------------------------------------------------------------------------

METHOD="${1:-rsync}"
DEST="${2:-./uploads}"
mkdir -p "$DEST"

# WordPress-generated thumbnails look like  name-300x200.jpg. Skipping them takes
# the transfer from ~13.2 GB to ~8.5 GB. They are all regenerable on any WP site
# (wp media regenerate), so they are usually not worth archiving.
THUMB_GLOB='*-[0-9]*x[0-9]*.*'

case "$METHOD" in

  rsync)
    # Best default: resumable, verifies as it goes, re-runnable to pick up new
    # files. --partial keeps half-transferred files so a dropped connection
    # resumes instead of restarting.
    exec rsync -avh --progress --partial --inplace \
      "${SSH_USER}@${SSH_HOST}:${REMOTE_UPLOADS}/" "$DEST/"
    ;;

  rsync-originals)
    # Same, minus the generated thumbnail sizes.
    # NOTE: this glob would also skip a genuine file named like "plan-10x12.jpg".
    # Run tools/verify_download.py afterward to see exactly what was skipped.
    exec rsync -avh --progress --partial --inplace \
      --exclude="$THUMB_GLOB" \
      "${SSH_USER}@${SSH_HOST}:${REMOTE_UPLOADS}/" "$DEST/"
    ;;

  tar)
    # Fastest single-pass copy: one stream, no per-file round trips. Not
    # resumable, so prefer rsync unless the link is solid. No compression --
    # JPEGs and PNGs are already compressed, so -z would burn CPU for ~nothing.
    exec ssh "${SSH_USER}@${SSH_HOST}" \
      "tar -C '$(dirname "$REMOTE_UPLOADS")' -cf - '$(basename "$REMOTE_UPLOADS")'" \
      | tar -C "$DEST/.." -xvf -
    ;;

  lftp)
    # Use this when FTP is all you have. -P 8 pulls 8 files in parallel, which
    # matters a lot for 37k small files; -c continues an interrupted mirror.
    exec lftp -u "$FTP_USER" "$FTP_HOST" -e \
      "set ftp:ssl-force true; set net:timeout 20; \
       mirror -c -P 8 --verbose '$REMOTE_UPLOADS' '$DEST'; bye"
    ;;

  wget)
    # No shell access at all: fetch over HTTPS straight from the manifest.
    # Only retrieves files the manifest knows about (37,863 originals) and only
    # those publicly reachable. -nc skips anything already downloaded.
    python3 -c "
import csv,sys
for r in csv.DictReader(open('data/media-manifest.csv')):
    if r['url']: print(r['url'])
" > "$DEST/../urls.txt"
    exec wget -nc -c -x -nH --cut-dirs=2 -P "$DEST" -i "$DEST/../urls.txt"
    ;;

  *)
    echo "unknown method: $METHOD" >&2
    sed -n '2,12p' "$0" >&2
    exit 2
    ;;
esac
