#!/usr/bin/env bash
#
# Pull wp-content/uploads off the server WITHOUT using server-side disk space.
#
# None of these methods create an archive, staging copy, or temp file on the
# server. Bytes stream straight from the existing files to your machine, so the
# server never needs the ~13 GB of free space that zipping would demand. No file
# in uploads/ is read-only-violated, renamed, or modified.
#
# Run this FROM YOUR MAC, not from inside an ssh session. rsync/lftp/tar open the
# connection themselves and pull toward you. Running them on the server would put
# the copy back on the server, which is the space problem you're avoiding.
#
# Usage:  ./tools/fetch_uploads.sh <method> [dest]
# Methods: check | rsync | rsync-originals | tar | lftp | wget
#
# Start with `check` -- it confirms the remote path and reports the real size
# before you commit to a multi-hour transfer.
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

# This is a live production site. Pulling 13 GB flat-out competes with real
# visitors for the VPS's uplink and disk. BWLIMIT caps the transfer (KB/s);
# 5000 = ~5 MB/s, which still finishes 13 GB in about 45 minutes. Set
# BWLIMIT=0 to disable the cap.
BWLIMIT="${BWLIMIT:-5000}"
RSYNC_OPTS=(-avh --progress --partial --inplace)
[ "$BWLIMIT" != "0" ] && RSYNC_OPTS+=("--bwlimit=$BWLIMIT")

case "$METHOD" in

  check)
    # Read-only sanity check before committing to a long transfer: does the path
    # exist, how big is it really, and does this server even have rsync?
    ssh "${SSH_USER}@${SSH_HOST}" bash -s <<EOF
set -e
if [ ! -d "$REMOTE_UPLOADS" ]; then
  echo "NOT FOUND: $REMOTE_UPLOADS"
  echo "Looking for wp-content/uploads in the usual places:"
  ls -d ~/public_html/wp-content/uploads /var/www/*/wp-content/uploads \
        /home/*/public_html/wp-content/uploads /usr/share/nginx/*/wp-content/uploads \
        2>/dev/null || echo "  (none found -- check your host's control panel for the docroot)"
  exit 1
fi
echo "path   : $REMOTE_UPLOADS"
echo -n "size   : "; du -sh "$REMOTE_UPLOADS" | cut -f1
echo -n "files  : "; find "$REMOTE_UPLOADS" -type f | wc -l
echo -n "free   : "; df -h "$REMOTE_UPLOADS" | awk 'NR==2{print \$4" available"}'
echo -n "rsync  : "; command -v rsync || echo "NOT INSTALLED -- use the lftp method instead"
EOF
    ;;

  rsync)
    # Best default: resumable, verifies as it goes, re-runnable to pick up new
    # files. --partial keeps half-transferred files so a dropped connection
    # resumes instead of restarting.
    exec rsync "${RSYNC_OPTS[@]}" \
      "${SSH_USER}@${SSH_HOST}:${REMOTE_UPLOADS}/" "$DEST/"
    ;;

  rsync-originals)
    # Same, minus the generated thumbnail sizes.
    # NOTE: this glob would also skip a genuine file named like "plan-10x12.jpg".
    # Run tools/verify_download.py afterward to see exactly what was skipped.
    exec rsync "${RSYNC_OPTS[@]}" --exclude="$THUMB_GLOB" \
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
    cat >&2 <<'USAGE'
unknown method.

  ./tools/fetch_uploads.sh check             confirm the remote path and size
  ./tools/fetch_uploads.sh rsync ./uploads   everything, resumable (start here)
  ./tools/fetch_uploads.sh rsync-originals   skip thumbnails: 8.5 GB not 13.2 GB
  ./tools/fetch_uploads.sh tar ./uploads     one fast pass, not resumable
  ./tools/fetch_uploads.sh lftp ./uploads    FTP only, no shell access
  ./tools/fetch_uploads.sh wget ./uploads    no server access at all, over HTTPS

Run from your Mac, not from inside an ssh session.
Set SSH_USER, SSH_HOST and REMOTE_UPLOADS first.
USAGE
    exit 2
    ;;
esac
