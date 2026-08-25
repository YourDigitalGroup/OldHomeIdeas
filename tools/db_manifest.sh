#!/usr/bin/env bash
#
# Pull attribution straight from the live WordPress database instead of the XML
# export. Requires shell access on the server (you have root on the VPS).
#
# Why bother when data/media-manifest.csv already exists: the export is a
# snapshot with gaps. The database is the actual source of truth, and querying it
# fixes three things the export cannot:
#
#   1. The 89 Vimeo thumbnails. They have a post_parent but no author of their
#      own. One SQL join reaches the parent post's author -- no second export.
#   2. Files the export omitted entirely. A media-only WXR skips attachments in
#      unexpected states; the DB lists every row.
#   3. Orphans. Files sitting in uploads/ that no longer have a media-library
#      row at all -- a real thing in a folder that has accumulated since 2017,
#      and invisible to any export by definition.
#
# RUN FROM YOUR MAC. Every mode is read-only (SELECT and find), writes nothing on
# the server, and streams its output to a local file.
#
# Usage:
#   ./tools/db_manifest.sh path        discover the real uploads path
#   ./tools/db_manifest.sh manifest    -> data/db-manifest.tsv
#   ./tools/db_manifest.sh listing     -> data/disk-listing.tsv
#   ./tools/db_manifest.sh all         all three
#
set -euo pipefail

SSH_USER="${SSH_USER:-root}"
SSH_HOST="${SSH_HOST:-184.168.20.91}"
# WordPress root on the server (the folder holding wp-config.php).
# Don't know it? ssh in and: find / -name wp-config.php -not -path '*/backup*' 2>/dev/null
WP_PATH="${WP_PATH:-/var/www/findhomeideas.com}"

MODE="${1:-all}"
mkdir -p data

# wp-cli reads credentials from wp-config.php, so no passwords live in this file.
# --allow-root is needed when running as root; harmless otherwise.
WP="cd '$WP_PATH' && wp --allow-root --skip-plugins --skip-themes"

do_path() {
  echo "== uploads path (authoritative, straight from WordPress) ==" >&2
  ssh "${SSH_USER}@${SSH_HOST}" "$WP eval 'echo wp_get_upload_dir()[\"basedir\"], PHP_EOL;'"
}

do_manifest() {
  echo "== attribution from the database ==" >&2

  # Resolve the table prefix once rather than assuming wp_. On a site this old it
  # is very often something else.
  local pfx
  pfx="$(ssh "${SSH_USER}@${SSH_HOST}" "$WP db prefix" | tr -d '\r\n')"
  [ -n "$pfx" ] || { echo "could not read the DB table prefix" >&2; exit 1; }
  echo "table prefix: $pfx" >&2

  # COALESCE walks the fallback chain: the attachment's own author first, then
  # the author of the post it hangs off -- which is what resolves the 89.
  # TSV, not CSV: company names like "Ferguson Bath, Kitchen & Lighting Gallery"
  # contain commas.
  local sql
  sql="SELECT
      a.ID AS post_id,
      COALESCE(NULLIF(ua.user_login,''), up.user_login, 'UNATTRIBUTED')     AS company_slug,
      COALESCE(NULLIF(ua.display_name,''), up.display_name, 'UNATTRIBUTED') AS company_name,
      CASE
        WHEN ua.ID IS NOT NULL THEN 'db_attachment_author'
        WHEN up.ID IS NOT NULL THEN 'db_parent_author'
        ELSE 'db_unresolved'
      END AS company_source,
      COALESCE(pm.meta_value,'') AS file,
      a.post_parent,
      a.post_mime_type,
      a.post_date
    FROM ${pfx}posts a
    LEFT JOIN ${pfx}postmeta pm ON pm.post_id = a.ID AND pm.meta_key = '_wp_attached_file'
    LEFT JOIN ${pfx}users    ua ON ua.ID = a.post_author
    LEFT JOIN ${pfx}posts     p ON  p.ID = a.post_parent
    LEFT JOIN ${pfx}users    up ON up.ID = p.post_author
    WHERE a.post_type = 'attachment'
    ORDER BY company_slug, file;"

  # Pass the SQL on stdin so no quoting survives two levels of shell.
  printf '%s\n' "$sql" \
    | ssh "${SSH_USER}@${SSH_HOST}" "$WP db query" > data/db-manifest.tsv
  echo "wrote data/db-manifest.tsv ($(wc -l < data/db-manifest.tsv) lines)" >&2
}

do_listing() {
  echo "== every file actually on disk ==" >&2
  local base
  base="$(do_path 2>/dev/null | tr -d '\r')"
  [ -n "$base" ] || { echo "could not determine uploads path" >&2; exit 1; }
  # -printf keeps this to one pass and no stat storm; output streams to your Mac,
  # so nothing is written on the server.
  ssh "${SSH_USER}@${SSH_HOST}" "find '$base' -type f -printf '%P\t%s\n'" > data/disk-listing.tsv
  echo "wrote data/disk-listing.tsv ($(wc -l < data/disk-listing.tsv) files)" >&2
}

case "$MODE" in
  path)     do_path ;;
  manifest) do_manifest ;;
  listing)  do_listing ;;
  all)      do_path; do_manifest; do_listing
            echo; echo "Now reconcile the three sources:" >&2
            echo "  python3 tools/reconcile.py" >&2 ;;
  *) sed -n '20,26p' "$0" >&2; exit 2 ;;
esac
