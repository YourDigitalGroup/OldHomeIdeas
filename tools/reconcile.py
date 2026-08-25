#!/usr/bin/env python3
"""
Reconcile the three views of the media library and emit the authoritative
attribution table.

    python3 tools/reconcile.py

Inputs (produced by tools/db_manifest.sh):
    data/db-manifest.tsv    live database: every attachment row + its company
    data/disk-listing.tsv   every file actually present in uploads/
    data/media-manifest.csv the XML export (fallback, and the thumbnail names)

Outputs:
    data/attribution.csv    one row per FILE ON DISK, with its owning company --
                            originals and thumbnails alike. This is the file to
                            use; it supersedes media-manifest.csv.
    data/orphans.csv        files on disk with no media-library row at all

Why three sources: the database knows who owns what but not what is on disk; the
disk knows what exists but not who owns it; the export knows the generated
thumbnail names, which is how a thumbnail gets attributed to the same company as
its original. Read-only -- nothing is uploaded or changed.
"""
import csv, os, sys, collections

DB = 'data/db-manifest.tsv'
DISK = 'data/disk-listing.tsv'
XML = 'data/media-manifest.csv'


def load_db():
    """post_id -> {company...}, keyed also by file path."""
    if not os.path.exists(DB):
        return {}, {}
    rows = []
    with open(DB, encoding='utf-8', errors='replace') as f:
        r = csv.DictReader(f, delimiter='\t')
        for d in r:
            rows.append(d)
    by_file = {d['file']: d for d in rows if d.get('file')}
    return rows, by_file


def load_xml():
    if not os.path.exists(XML):
        return {}, {}
    by_file, variant_owner = {}, {}
    for d in csv.DictReader(open(XML, encoding='utf-8')):
        if not d['file']:
            continue
        by_file[d['file']] = d
        folder = os.path.dirname(d['file'])
        for v in (d.get('size_files') or '').split('|'):
            if v:
                variant_owner[os.path.join(folder, v)] = d['file']
    return by_file, variant_owner


def main():
    missing = [p for p in (DB, DISK) if not os.path.exists(p)]
    if missing:
        sys.exit('missing input(s): %s\nrun ./tools/db_manifest.sh all first'
                 % ', '.join(missing))

    db_rows, db_by_file = load_db()
    xml_by_file, variant_owner = load_xml()

    disk = []
    with open(DISK, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            path, _, size = line.rpartition('\t')
            if path:
                disk.append((path, int(size) if size.isdigit() else 0))

    out = []
    stats = collections.Counter()
    orphans = []

    for path, size in disk:
        # a thumbnail inherits its original's company
        origin = variant_owner.get(path)
        is_variant = origin is not None
        key = origin or path

        rec = db_by_file.get(key)
        if rec:
            slug, name, source = rec['company_slug'], rec['company_name'], rec['company_source']
        else:
            x = xml_by_file.get(key)
            if x:
                slug, name, source = x['company_slug'], x['company_name'], 'xml_' + x['company_source']
            else:
                slug, name, source = 'UNATTRIBUTED', 'UNATTRIBUTED', 'orphan_not_in_library'
                orphans.append((path, size))

        if is_variant and source != 'orphan_not_in_library':
            source += '+thumbnail'
        stats[source] += 1
        out.append({'file': path, 'bytes': size, 'company_slug': slug,
                    'company_name': name, 'company_source': source,
                    'is_thumbnail': int(is_variant)})

    with open('data/attribution.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['file', 'bytes', 'company_slug',
                                          'company_name', 'company_source', 'is_thumbnail'])
        w.writeheader()
        w.writerows(sorted(out, key=lambda r: (r['company_slug'], r['file'])))

    with open('data/orphans.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['file', 'bytes'])
        w.writerows(sorted(orphans, key=lambda t: -t[1]))

    gb = lambda n: n / 1024 ** 3
    total = sum(s for _, s in disk)
    orphan_bytes = sum(s for _, s in orphans)
    attributed = len(out) - len(orphans)

    print('database rows      : %d' % len(db_rows))
    print('files on disk      : %d  (%.2f GB)' % (len(disk), gb(total)))
    print('attributed         : %d  (%.1f%%)' % (attributed, 100.0 * attributed / max(1, len(disk))))
    print('orphans (no row)   : %d  (%.2f GB)' % (len(orphans), gb(orphan_bytes)))
    print()
    for src, n in stats.most_common():
        print('  %-32s %7d' % (src, n))

    # anything the DB lists that never made it to disk is a broken media item
    on_disk = {p for p, _ in disk}
    gone = [d for d in db_rows if d.get('file') and d['file'] not in on_disk]
    print('\nin database, not on disk: %d  (broken media items)' % len(gone))
    for d in gone[:10]:
        print('   %s  [%s]' % (d['file'], d['company_name']))

    print('\nwrote data/attribution.csv, data/orphans.csv')


if __name__ == '__main__':
    main()
