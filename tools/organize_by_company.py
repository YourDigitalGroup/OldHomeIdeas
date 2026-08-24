#!/usr/bin/env python3
"""
Build a by-company/ view of a downloaded uploads/ tree.

    python3 tools/organize_by_company.py ./uploads ./by-company

By default this creates HARD LINKS, which means the company-sorted tree costs
essentially zero extra disk (two directory entries pointing at the same bytes)
and the original uploads/ tree is left byte-for-byte untouched. Nothing is
renamed, rewritten, or moved unless you explicitly ask for --copy or --move.

    by-company/
      Montgomery's/
        2023-01__montgomerys-image-1-from-may-4th-2017-82621am.jpg
        ...
      Mahlander's Appliance & Lighting/
      _UNATTRIBUTED/

Options:
    --mode link|symlink|copy|move   default: link
    --include-sizes                 also bring the -300x200 thumbnail variants
    --flat-names                    prefix each file with its year-month folder
                                    so same-named files from different months
                                    cannot collide (default: on)
    --dry-run                       report what would happen, change nothing
"""
import argparse, csv, os, re, sys, collections


def safe_dirname(name):
    """Filesystem-safe company folder name, readable by a human."""
    name = re.sub(r'[/\\:*?"<>|]', '-', name).strip().strip('.')
    return name or 'UNNAMED'


def place(src, dst, mode, dry):
    if dry:
        return 'would-' + mode
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        return 'exists'
    try:
        if mode == 'link':
            os.link(src, dst)
        elif mode == 'symlink':
            os.symlink(os.path.relpath(src, os.path.dirname(dst)), dst)
        elif mode == 'copy':
            import shutil; shutil.copy2(src, dst)
        elif mode == 'move':
            import shutil; shutil.move(src, dst)
    except OSError as e:
        # hard links fail across filesystems -- fall back rather than abort
        if mode == 'link' and e.errno == 18:
            import shutil; shutil.copy2(src, dst)
            return 'copied-xdev'
        raise
    return mode


def main():
    p = argparse.ArgumentParser()
    p.add_argument('uploads', help='local copy of wp-content/uploads')
    p.add_argument('dest', nargs='?', default='./by-company')
    p.add_argument('--manifest', default='data/media-manifest.csv')
    p.add_argument('--mode', choices=['link', 'symlink', 'copy', 'move'], default='link')
    p.add_argument('--include-sizes', action='store_true')
    p.add_argument('--no-flat-names', dest='flat', action='store_false', default=True)
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()

    rows = list(csv.DictReader(open(a.manifest, encoding='utf-8')))
    stats = collections.Counter()
    missing = []

    for r in rows:
        rel = r['file']
        if not rel or rel.startswith('http'):
            stats['skipped-no-path'] += 1
            continue
        if not os.path.exists(os.path.join(a.uploads, rel)):
            missing.append(rel)
            continue

        company = safe_dirname(r['company_name'] if r['company_slug'] != 'UNATTRIBUTED'
                               else '_UNATTRIBUTED')
        group = [rel]
        if a.include_sizes and r.get('size_files'):
            # exact variant names recorded by WordPress, alongside the original
            folder = os.path.dirname(rel)
            group += [os.path.join(folder, v) for v in r['size_files'].split('|') if v]

        for g in group:
            src = os.path.join(a.uploads, g)
            if not os.path.exists(src):
                stats['variant-not-on-disk'] += 1
                continue
            if a.flat:
                # 2023/01/foo.jpg -> "2023-01__foo.jpg", so months can't collide
                prefix = os.path.dirname(g).replace(os.sep, '-') + '__'
                dst = os.path.join(a.dest, company, prefix + os.path.basename(g))
            else:
                dst = os.path.join(a.dest, company, g)
            stats[place(src, dst, a.mode, a.dry_run)] += 1

    print('manifest rows      : %d' % len(rows))
    print('placed             : %s' % dict(stats))
    print('in manifest, not on disk: %d' % len(missing))
    for m in missing[:10]:
        print('   missing:', m)
    if len(missing) > 10:
        print('   ... and %d more (see verify_download.py for the full list)' % (len(missing) - 10))


if __name__ == '__main__':
    sys.exit(main())
