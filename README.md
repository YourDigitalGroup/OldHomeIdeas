# findhomeideas.com — media library extraction & company attribution

Tooling to pull `wp-content/uploads` off the findhomeideas.com server without
using server-side disk space, and to record which company each of the 37,863
files belongs to — without modifying anything in `uploads/`.

## Quick start — the exact commands, in order

Everything runs **from your Mac**. Nothing is written on the server.

```bash
# --- 0. one time: get this repo and check your rsync ---------------------------
git clone https://github.com/YourDigitalGroup/OldHomeIdeas.git
cd OldHomeIdeas
git checkout claude/uploads-company-metadata-5lw60v
rsync --version | head -1        # says "openrsync"? -> brew install rsync

# --- 1. find the two things only the server knows ------------------------------
ssh root@184.168.20.91 "find / -name wp-config.php -not -path '*/backup*' 2>/dev/null; command -v wp || echo 'NO WP-CLI'"

# --- 2. point the tools at the site (WP_PATH = folder holding wp-config.php) ---
export SSH_USER=root
export SSH_HOST=184.168.20.91
export WP_PATH=/var/www/findhomeideas.com

# --- 3. attribution + orphan report, straight from the live database -----------
./tools/db_manifest.sh all
python3 tools/reconcile.py

# --- 4. LOOK at this before transferring 13 GB --------------------------------
head -50 data/orphans.csv
open data/companies.csv

# --- 5. download (read-only, resumable, capped at ~5 MB/s) --------------------
export REMOTE_UPLOADS=$(./tools/db_manifest.sh path)
./tools/fetch_uploads.sh check
./tools/fetch_uploads.sh rsync ./uploads

# --- 6. confirm it all arrived intact ----------------------------------------
python3 tools/verify_download.py ./uploads

# --- 7. build the per-company view (hard links, costs ~nothing) --------------
python3 tools/organize_by_company.py ./uploads ./by-company \
    --manifest data/attribution.csv
```

Step 3 needs **wp-cli** on the server. If step 1 printed `NO WP-CLI`:

```bash
ssh root@184.168.20.91 'curl -sO https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar \
  && chmod +x wp-cli.phar && mv wp-cli.phar /usr/local/bin/wp && wp --info --allow-root'
```

Only steps 5–7 are slow (about 45 minutes for the transfer). Steps 3, 5 and 6 are
all re-runnable — rsync resumes where it left off.

## What the export actually contains

`homeideas.WordPress.2026-08-24.xml` is a **media-only** export: 37,863
`attachment` items, no posts or pages.

| | |
|---|---|
| Attachments | 37,863 |
| Companies | 166 |
| Originals | **8.54 GB** |
| Originals + WordPress-generated thumbnail sizes | **13.23 GB** |
| Generated thumbnail files | 112,746 |

The good news: **the company is already recorded on every file.** Each company
has its own WordPress account, and the attachment's `dc:creator` is the account
that uploaded it. That covers 33,878 files outright. The rest are recoverable
from filename prefixes, which follow a `<company-slug>-image-N-from-<date>`
convention.

| How the company was determined | Files |
|---|---|
| `wp_author` — `dc:creator` on the attachment (authoritative) | 33,878 |
| `filename_prefix` — filename begins with a known company slug | 3,886 |
| `filename_fuzzy` — slug differs slightly (dropped accent, truncation) | 10 |
| `unresolved` | 89 |

**99.76% attributed.** Every row records which tier was used in the
`company_source` column, so the weaker inferences stay auditable rather than
silently blending in with the certain ones.

The 89 unresolved files are all Vimeo video thumbnails (`vimeo-1149744418-video-image`)
with no company anywhere in the name. They *do* have a `post_parent`, so the
parent post's author resolves them — and with root on the VPS you can reach that
with one SQL join instead of a second export. See
[Better: skip the export, query the database](#better-skip-the-export-query-the-database),
which also gets you to 100% and finds files no export can see.

### Two data quirks worth knowing before you sync anything

1. **33,020 files have no file extension.** Their thumbnails are named with a
   trailing dot — `vimeo-1149744418-video-image-300x169.` — which is why the
   tooling reads the exact variant filenames out of WordPress's stored metadata
   instead of pattern-matching for `-300x200.jpg`. A regex guess silently misses
   all of them.
2. **11 attachments point at absolute `gravity_forms/` URLs**, outside the normal
   `YYYY/MM/` tree. They're form upload submissions, not gallery media.

## Answering the three questions

### 1. No, the uploads are not in GitHub — and they shouldn't be

This repo contains exactly one file in its history: the export zip you uploaded.
There is no `uploads/` folder in any commit or branch. FTP access to the server
and a GitHub repo are unconnected — setting up FTP doesn't make the server's
files appear here, and nothing has ever pushed them.

That's the right outcome anyway. 13 GB of binaries in git would be unusable:
git stores every version forever, so a single bad commit doubles it permanently,
and GitHub's hard limits (100 MB per file, ~5 GB recommended per repo) rule it
out. Git is for the *manifest*; the media belongs in object storage (S3, B2,
Google Drive) or on a NAS.

**And GitHub can't serve as the transfer route either.** To push the files to
GitHub, something first has to *pull them off the server* — the identical
problem — and then a git repo containing them needs roughly double the space
locally (working tree plus `.git` objects), so ~26 GB for a 13 GB library. Git
LFS doesn't rescue it: GitHub Free includes 1 GB of LFS storage and 1 GB of
bandwidth per month against a 13 GB library. GitHub is a step *after* the
download, not a substitute for it — and for media, not a step worth taking.

### 2. How to download 13 GB without server-side space

The reason you can't zip it is that zipping needs room for a second copy of
everything. The fix is to never create that copy — stream the bytes straight
off disk to your machine.

**Run these from your Mac, not from inside an SSH session.** `rsync`, `lftp` and
`tar` open the connection themselves and pull toward you. Running them *on* the
server would put the copy back on the server — the exact problem you're avoiding.

```bash
export SSH_USER=root SSH_HOST=184.168.20.91
export REMOTE_UPLOADS=$(./tools/db_manifest.sh path)   # ask WordPress, don't guess

./tools/fetch_uploads.sh check            # confirm the path and real size first
./tools/fetch_uploads.sh rsync ./uploads
```

`check` is read-only: it verifies the path exists (and suggests candidates if it
doesn't), reports the true size and file count, shows free space, and confirms
the server actually has `rsync`. Worth 20 seconds before a multi-hour transfer.

The transfer is **bandwidth-capped to ~5 MB/s by default** (`BWLIMIT`, in KB/s).
This is a live site, and pulling 13 GB flat-out competes with real visitors for
the VPS's uplink and disk. 5 MB/s still finishes in about 45 minutes. Override
with `BWLIMIT=0 ./tools/fetch_uploads.sh rsync ./uploads` if you don't care.

On macOS 15 (Sequoia) Apple replaced `rsync` with `openrsync`, which doesn't
support `--partial`/`--inplace`. Check with `rsync --version`; if it's openrsync,
`brew install rsync` — or use the `tar` method.

`rsync` reads the existing files and writes nothing on the server. It's
resumable (`--partial`), re-runnable to pick up new files, and verifies as it
goes. `tar` streams in one pass (fastest, but not resumable), `lftp` mirrors over
FTP with 8 parallel connections, and `wget` pulls from the manifest URLs over
HTTPS — the last two matter less now that you have root, but they're there.

**Take the originals only and you move 8.54 GB instead of 13.23 GB.** The 112,746
thumbnails are all regenerable on any WordPress install with
`wp media regenerate`:

```bash
./tools/fetch_uploads.sh rsync-originals ./uploads
```

Then confirm the transfer actually finished before you touch anything on the
server:

```bash
python3 tools/verify_download.py ./uploads
```

It reports files missing from disk, files whose size disagrees with WordPress's
record (truncated transfers), and files on disk the manifest doesn't describe.

### 3. My recommendation: folders + manifest, not renaming, not embedded metadata

You asked whether to encode the company in the filename or in file metadata.
I'd do **neither to the files on the server**, and use a third option locally.

**Don't rename anything on the server.** Every filename in `uploads/` is a live
URL. Renaming breaks the image on every page that references it, breaks the
`_wp_attached_file` row in the database, and breaks Google's index of those
image URLs. This is also the thing you said you didn't want to do — you're right.

**Don't embed metadata on the server either.** Writing XMP/IPTC rewrites the file
bytes in place. That's a 37,863-file write operation against your live media
library to record something you already know from the database, and a crash
mid-run leaves you with corrupted images and no backup — on a server that
doesn't have the space to hold one.

**Do sort a local copy into per-company folders, backed by a CSV manifest.**

```bash
python3 tools/organize_by_company.py ./uploads ./by-company \
    --manifest data/attribution.csv
```

```
by-company/
  Mahlander's Appliance & Lighting/
    2023-01__mahlanders-image-1-from-may-4th-2017-82621am.jpg
    ...
  Montgomery's/
  _UNATTRIBUTED/
```

This uses **hard links** by default, so the company-sorted tree costs
essentially nothing — two directory entries pointing at the same bytes on disk.
In testing, a 57 MB `uploads/` tree gained a full by-company view for 340 KB.
The original tree stays byte-for-byte identical; nothing is renamed, rewritten,
or moved.

Why this beats filename-encoding even on the copy:

- **Reversible.** Delete `by-company/` and you've lost nothing. A rename is a
  one-way door — the original filename is the only join key back to the
  WordPress database, and prefixing destroys it.
- **Filenames are already long.** `mahlanders-appliance-lighting-image-1-from-may-4th-2017-82621am.jpg`
  is 68 characters. Prefixing the company again pushes files toward Windows'
  260-character path limit, and many *already* start with the company slug — you'd
  be writing it twice.
- **Company names don't survive filenames.** `Ferguson Bath, Kitchen & Lighting
  Gallery` and `Superior Garage Décor & More` have commas, ampersands and accents
  that get mangled into slugs. A folder name holds the real name; a CSV column
  holds it exactly.
- **A CSV answers questions a filename can't** — "everything from this company
  over 2 MB", "which files are only inferred, not certain" — in one sort.

The manifest is the source of truth either way:

- **`data/companies.csv`** — 166 companies, file counts and byte totals. Open it
  first; it's the one-page view.
- **`data/media-manifest.csv`** — one row per file: company, how that company was
  determined, path, URL, size, and the exact generated thumbnail names.

**The one case for embedded metadata** is if these images will get separated
from both the folders and the CSV — handed to a client, loaded into a DAM,
re-uploaded elsewhere. Then embedding travels with the file. `tools/tag_metadata.sh`
does that with exiftool, writing `XMP:Creator`, `IPTC:Credit`, `XMP:Source` and an
`XMP:Label` noting how the attribution was derived. Run it on your **local copy
only**, and only after `verify_download.py` passes — it rewrites every file.

## Suggested order

```bash
export SSH_USER=root SSH_HOST=184.168.20.91
export WP_PATH=/var/www/findhomeideas.com

# 1. Authoritative attribution + orphan report, straight from the live DB
./tools/db_manifest.sh all
python3 tools/reconcile.py
#    Read data/orphans.csv before transferring — you may not want all of it.

# 2. Pull the media down — nothing is written on the server, capped at 5 MB/s
export REMOTE_UPLOADS=$(./tools/db_manifest.sh path)
./tools/fetch_uploads.sh check
./tools/fetch_uploads.sh rsync ./uploads

# 3. Confirm it all arrived intact
python3 tools/verify_download.py ./uploads

# 4. Build the per-company view (hard links, ~free)
python3 tools/organize_by_company.py ./uploads ./by-company \
    --manifest data/attribution.csv

# 5. Only if the files need to travel alone — local copy only
./tools/tag_metadata.sh ./uploads
```

`uploads/` and `by-company/` are gitignored. Keep the manifest in git; put the
media in object storage.

## Better: skip the export, query the database

With root on the VPS, the XML export stops being the best source — it's a
snapshot with gaps, and the live database is the actual truth. Querying it
directly fixes three things no export can:

1. **The 89 unattributed Vimeo thumbnails.** They have a `post_parent` but no
   author of their own. One SQL join reaches the parent post's author. No second
   export needed.
2. **Attachments the export omitted.** A media-only WXR skips rows in unexpected
   states; the database lists all of them.
3. **Orphans — the interesting one.** Files sitting in `uploads/` with no
   media-library row *at all*. In a folder accumulating since 2017 there are
   usually plenty, and they are invisible to any export by definition. You're
   about to pay to transfer and store them, so it's worth knowing what they are
   before you do.

```bash
export SSH_USER=root SSH_HOST=184.168.20.91
export WP_PATH=/var/www/findhomeideas.com     # folder containing wp-config.php

./tools/db_manifest.sh all      # -> data/db-manifest.tsv, data/disk-listing.tsv
python3 tools/reconcile.py      # -> data/attribution.csv, data/orphans.csv
```

Both are read-only — `SELECT` and `find`, nothing written on the server, output
streamed to your Mac. `db_manifest.sh` reads credentials from `wp-config.php` via
wp-cli (no passwords in the scripts) and resolves the real table prefix rather
than assuming `wp_`.

**`data/attribution.csv` is the file to actually use.** It supersedes
`media-manifest.csv`: one row per file *on disk* — originals and thumbnails
alike, since a thumbnail inherits its original's company — with the company and
how it was determined. `reconcile.py` also flags rows in the database whose file
is missing from disk, which are broken media items on the live site.

Don't know `WP_PATH`? `ssh root@184.168.20.91 "find / -name wp-config.php -not -path '*/backup*' 2>/dev/null"`

## Verify the attribution yourself

The 10 fuzzy matches are all one company — files named
`superior-garage-decor-more-*` against the account slug `superior-garage-dcor-more`,
where the `é` in "Décor" was dropped when WordPress generated the login. Worth
the 30 seconds to confirm:

```bash
python3 -c "
import csv
for r in csv.DictReader(open('data/media-manifest.csv')):
    if r['company_source'] == 'filename_fuzzy':
        print(r['file'], '->', r['company_slug'])"
```
