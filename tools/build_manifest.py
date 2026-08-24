#!/usr/bin/env python3
"""
Build a company-attributed manifest of the findhomeideas.com media library
from a WordPress WXR export.

    python3 tools/build_manifest.py homeideas.WordPress.2026-08-24.xml

Writes:
    data/media-manifest.csv   one row per attachment, with its owning company
    data/companies.csv        per-company rollup (file counts + byte totals)

Attribution is resolved in tiers, and every row records which tier was used
in `company_source` so the weaker inferences stay auditable:

    wp_author        dc:creator on the attachment (the uploading company's
                     WordPress account). Authoritative.
    filename_prefix  creator was blank, but the filename begins with a known
                     company slug on a token boundary.
    filename_fuzzy   as above, but the filename slug differs slightly from the
                     account slug (dropped accents, truncation). Spot-check.
    unresolved       no company could be determined. Left as UNATTRIBUTED.

Nothing here touches the live server. It reads the export and writes CSVs.
"""
import sys, os, re, csv, html, difflib, collections

ITEM_RE = re.compile(r'<item>(.*?)</item>', re.S)
FILESIZE_RE = re.compile(r's:8:"filesize";i:(\d+);')
FILE_RE = re.compile(r's:4:"file";s:\d+:"([^"]*)"')
# e.g. "acme-cabinets-image-1-from-may-4th-2017-82621am.jpg"
NAMED_RE = re.compile(r'^(.*?)-image-\d+-(?:from|on)-')


def cdata(block, tag):
    m = re.search(r'<%s>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</%s>' % (tag, tag), block, re.S)
    return m.group(1).strip() if m else ''


def meta(block, key):
    m = re.search(
        r'<wp:meta_key><!\[CDATA\[' + re.escape(key) + r'\]\]></wp:meta_key>\s*'
        r'<wp:meta_value><!\[CDATA\[(.*?)\]\]></wp:meta_value>', block, re.S)
    return m.group(1) if m else ''


def norm(s):
    """Collapse a slug to comparable form: lowercase alphanumerics only."""
    return re.sub(r'[^a-z0-9]', '', s.lower())


def parse_authors(data):
    authors = {}
    for m in re.finditer(r'<wp:author>(.*?)</wp:author>', data, re.S):
        b = m.group(1)
        login = cdata(b, 'wp:author_login')
        if login:
            authors[login] = html.unescape(cdata(b, 'wp:author_display_name')) or login
    return authors


def parse_attachments(data):
    out = []
    for m in ITEM_RE.finditer(data):
        b = m.group(1)
        if cdata(b, 'wp:post_type') != 'attachment':
            continue
        amd = meta(b, '_wp_attachment_metadata')
        sizes = [int(x) for x in FILESIZE_RE.findall(amd)]
        # WordPress records the exact generated-variant filenames. Read them
        # rather than guessing with a "-300x200" pattern: variants of an
        # extensionless original are named like "foo-300x169." (trailing dot),
        # and a real file named "plan-10x12.jpg" would match any such guess.
        # Entries containing "/" are the original's own path, not a variant.
        variants = [f for f in FILE_RE.findall(amd) if f and '/' not in f]
        out.append({
            'size_files': '|'.join(variants),
            'post_id': cdata(b, 'wp:post_id'),
            'company_slug': cdata(b, 'dc:creator'),
            'post_parent': cdata(b, 'wp:post_parent'),
            'file': meta(b, '_wp_attached_file'),
            'url': cdata(b, 'wp:attachment_url'),
            # sizes[0] is the original; the rest are WordPress-generated variants
            'orig_bytes': sizes[0] if sizes else 0,
            'total_bytes': sum(sizes),
            'derivatives': max(0, len(sizes) - 1),
            'title': cdata(b, 'title'),
        })
    return out


def build_resolver(slugs):
    """Return fn(filename) -> (slug, source). Longest match wins."""
    by_len = sorted(slugs, key=len, reverse=True)
    normed = {norm(s): s for s in slugs}
    norm_keys = sorted(normed, key=len, reverse=True)

    def resolve(path):
        base = path.split('/')[-1].lower()

        # 1. filename carries an explicit "<company>-image-N-from-<date>" prefix
        m = NAMED_RE.match(base)
        if m:
            cand = norm(m.group(1))
            if cand:
                for k in norm_keys:                       # exact, or account slug
                    if cand == k or cand.startswith(k) or k.startswith(cand):
                        return normed[k], 'filename_prefix'
                close = difflib.get_close_matches(cand, norm_keys, n=1, cutoff=0.88)
                if close:
                    return normed[close[0]], 'filename_fuzzy'

        # 2. otherwise, a plain slug prefix on a token boundary
        for s in by_len:
            sl = s.lower()
            if base.startswith(sl) and base[len(sl):len(sl) + 1] in ('', '-', '.', '_'):
                return s, 'filename_prefix'
        return '', ''

    return resolve


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else 'data'
    os.makedirs(outdir, exist_ok=True)

    data = open(src, encoding='utf-8', errors='replace').read()
    authors = parse_authors(data)
    rows = parse_attachments(data)
    del data

    resolve = build_resolver(set(authors) | {r['company_slug'] for r in rows if r['company_slug']})

    counts = collections.Counter()
    for r in rows:
        if r['company_slug']:
            r['company_source'] = 'wp_author'
        else:
            slug, source = resolve(r['file'])
            r['company_slug'] = slug or 'UNATTRIBUTED'
            r['company_source'] = source or 'unresolved'
        r['company_name'] = authors.get(r['company_slug'], r['company_slug'])
        counts[r['company_source']] += 1

    fields = ['post_id', 'company_slug', 'company_name', 'company_source', 'file',
              'url', 'orig_bytes', 'total_bytes', 'derivatives', 'size_files',
              'post_parent', 'title']
    manifest = os.path.join(outdir, 'media-manifest.csv')
    with open(manifest, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r['company_slug'], r['file'])))

    agg = collections.defaultdict(lambda: {'files': 0, 'orig': 0, 'total': 0, 'deriv': 0})
    for r in rows:
        a = agg[(r['company_slug'], r['company_name'])]
        a['files'] += 1
        a['orig'] += r['orig_bytes']
        a['total'] += r['total_bytes']
        a['deriv'] += r['derivatives']
    companies = os.path.join(outdir, 'companies.csv')
    with open(companies, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['company_slug', 'company_name', 'file_count',
                    'generated_size_files', 'originals_bytes', 'total_bytes'])
        for (slug, name), a in sorted(agg.items(), key=lambda kv: -kv[1]['total']):
            w.writerow([slug, name, a['files'], a['deriv'], a['orig'], a['total']])

    gb = lambda n: n / 1024 ** 3
    print('attachments      : %d' % len(rows))
    print('companies        : %d' % len(agg))
    print('originals        : %.2f GB' % gb(sum(r['orig_bytes'] for r in rows)))
    print('with generated   : %.2f GB' % gb(sum(r['total_bytes'] for r in rows)))
    print('attribution      : %s' % dict(counts))
    print('wrote %s, %s' % (manifest, companies))


if __name__ == '__main__':
    main()
