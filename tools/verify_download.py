#!/usr/bin/env python3
"""
Reconcile a downloaded uploads/ tree against the manifest.

    python3 tools/verify_download.py ./uploads

Confirms the transfer actually completed before you decide anything on the
server is safe to touch. Reports, per company:

  * files the manifest lists that are not on disk (incomplete download)
  * files whose size on disk disagrees with WordPress's recorded size
    (truncated / half-transferred)
  * files on disk that the manifest does not list (thumbnails, plugin dirs,
    backups -- worth a look before you assume uploads/ is fully described)

Read-only. Touches nothing.
"""
import csv, os, sys, collections


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    uploads = sys.argv[1]
    manifest = sys.argv[2] if len(sys.argv) > 2 else 'data/media-manifest.csv'

    rows = [r for r in csv.DictReader(open(manifest, encoding='utf-8'))
            if r['file'] and not r['file'].startswith('http')]
    expected = {r['file']: r for r in rows}

    on_disk = set()
    disk_bytes = 0
    for root, _, files in os.walk(uploads):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, uploads)
            on_disk.add(rel)
            try:
                disk_bytes += os.path.getsize(full)
            except OSError:
                pass

    missing, mismatched = [], []
    for rel, r in expected.items():
        full = os.path.join(uploads, rel)
        if not os.path.exists(full):
            missing.append(r)
            continue
        want = int(r['orig_bytes'] or 0)
        got = os.path.getsize(full)
        if want and want != got:
            mismatched.append((rel, want, got))

    # exact generated-variant paths WordPress recorded, so "extra" really means
    # unaccounted-for rather than "matched a thumbnail-shaped name"
    known_variants = set()
    for r in rows:
        folder = os.path.dirname(r['file'])
        for v in (r.get('size_files') or '').split('|'):
            if v:
                known_variants.add(os.path.join(folder, v))

    extra = on_disk - set(expected)
    thumbs = extra & known_variants
    other_extra = extra - thumbs

    gb = lambda n: n / 1024 ** 3
    print('manifest originals : %d' % len(expected))
    print('files on disk      : %d  (%.2f GB)' % (len(on_disk), gb(disk_bytes)))
    print('  of which generated sizes : %d' % len(thumbs))
    print('  not in manifest at all   : %d' % len(other_extra))
    print()
    print('MISSING (in manifest, not on disk) : %d' % len(missing))
    print('SIZE MISMATCH (likely truncated)   : %d' % len(mismatched))

    by_co = collections.Counter(r['company_name'] for r in missing)
    if by_co:
        print('\nmissing, by company:')
        for co, n in by_co.most_common(20):
            print('  %-50s %d' % (co[:48], n))
    for rel, want, got in mismatched[:15]:
        print('  mismatch %s: expected %d, got %d' % (rel, want, got))
    if other_extra:
        print('\nnot described by the manifest (sample):')
        for e in sorted(other_extra)[:15]:
            print('  ', e)

    return 1 if (missing or mismatched) else 0


if __name__ == '__main__':
    sys.exit(main())
