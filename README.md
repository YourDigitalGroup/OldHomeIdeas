# findhomeideas.com — media library extraction & company attribution

Tooling to pull `wp-content/uploads` off the findhomeideas.com server without
using server-side disk space, and to record which company each of the 37,863
files belongs to — without modifying anything in `uploads/`.

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
with no company anywhere in the name. They *do* have a `post_parent`, so if you
run a **second export with "All content" selected**, the parent post's author
resolves them. See [Closing the last 89](#closing-the-last-89).

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

### 2. How to download 13 GB without server-side space

The reason you can't zip it is that zipping needs room for a second copy of
everything. The fix is to never create that copy — stream the bytes straight
off disk to your machine:

```bash
export SSH_USER=youruser SSH_HOST=findhomeideas.com
export REMOTE_UPLOADS=/var/www/findhomeideas.com/wp-content/uploads

./tools/fetch_uploads.sh rsync ./uploads
```

`rsync` reads the existing files and writes nothing on the server. It's
resumable (`--partial`), re-runnable to pick up new files, and verifies as it
goes. If you only have FTP, `./tools/fetch_uploads.sh lftp` mirrors with 8
parallel connections, which matters a lot across 37k small files. `tar` streams
in one pass (fastest, not resumable), and `wget` pulls from the manifest URLs
over HTTPS if you have no shell access at all.

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
python3 tools/organize_by_company.py ./uploads ./by-company --include-sizes
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
# 1. Rebuild the manifest from the export (already committed, but reproducible)
python3 tools/build_manifest.py homeideas.WordPress.2026-08-24.xml

# 2. Pull the media down — nothing is written on the server
export SSH_USER=youruser SSH_HOST=findhomeideas.com
export REMOTE_UPLOADS=/var/www/findhomeideas.com/wp-content/uploads
./tools/fetch_uploads.sh rsync ./uploads

# 3. Confirm it all arrived intact
python3 tools/verify_download.py ./uploads

# 4. Build the per-company view (hard links, ~free)
python3 tools/organize_by_company.py ./uploads ./by-company --include-sizes

# 5. Only if the files need to travel alone — local copy only
./tools/tag_metadata.sh ./uploads
```

`uploads/` and `by-company/` are gitignored. Keep the manifest in git; put the
media in object storage.

## Closing the last 89

Those Vimeo thumbnails need the parent posts, which a media-only export omits.
In WordPress: **Tools → Export → All content**. The new file will be larger but
it carries the posts those attachments hang off, and each post's `dc:creator` is
the company. `build_manifest.py` reads that export the same way — the
`post_parent` column is already in the manifest waiting to be joined against it.

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
