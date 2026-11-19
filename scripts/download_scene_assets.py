"""Install pinned optional scene assets. Python 3.9+, standard library only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def matches(path, entry):
    return (path.is_file() and ('size' not in entry or path.stat().st_size == entry['size'])
            and digest(path) == entry['sha256'])


def destination(root, name):
    root = root.resolve()
    path = (root / name).resolve()
    if path == root or root not in path.parents:
        raise ValueError('Unsafe asset path: ' + name)
    return path


def download(url, path, entry):
    if matches(path, entry):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + '.part')
    for attempt in range(3):
        try:
            # GET the stable URL and follow redirects, including NVIDIA signed URLs.
            # Do not probe extensionless URLs using HEAD or persist expiring tokens.
            request = urllib.request.Request(url, headers={'User-Agent': 'Falcor-Scene-Assets/1.0'})
            with urllib.request.urlopen(request, timeout=90) as response, partial.open('wb') as out:
                copied = 0
                next_report = 64 * 1024 * 1024
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    out.write(block)
                    copied += len(block)
                    if copied >= next_report:
                        print('  downloaded %d MiB' % (copied // 1024 // 1024), flush=True)
                        next_report += 64 * 1024 * 1024
            if not matches(partial, entry):
                raise ValueError('Downloaded file failed SHA-256/size verification: ' + path.name)
            os.replace(partial, path)
            return
        except Exception as error:
            if attempt == 2:
                raise RuntimeError('Download failed: %s\n%s' % (url, error)) from error
            print('  retry %d/2: %s' % (attempt + 1, error), flush=True)
            time.sleep(2)


def install(name, spec, media, cache, archive_override=None, verify_only=False):
    folder = destination(media, spec['directory'])
    missing = [e for e in spec['files'] if not matches(destination(folder, e['path']), e)]
    if not missing:
        print(name + ': all files verified; nothing to download.', flush=True)
        return
    if verify_only:
        raise RuntimeError('%s: %d missing or modified files; first: %s' % (name, len(missing), missing[0]['path']))
    print('%s: installing/repairing %d files.' % (name, len(missing)), flush=True)
    if 'archive' not in spec:
        for i, entry in enumerate(missing, 1):
            print('  [%d/%d] %s' % (i, len(missing), entry['path']), flush=True)
            download(entry['url'], destination(folder, entry['path']), entry)
    else:
        archive = Path(archive_override).resolve() if archive_override else cache / spec['archive']
        if archive_override:
            if not matches(archive, spec):
                raise RuntimeError('Local archive failed SHA-256 verification: ' + str(archive))
        else:
            print('  archive: ' + str(archive), flush=True)
            download(spec['url'], archive, spec)
        with zipfile.ZipFile(archive) as z:
            for entry in missing:
                target = destination(folder, entry['path'])
                target.parent.mkdir(parents=True, exist_ok=True)
                partial = target.with_name(target.name + '.part')
                # Extract only pinned manifest entries, never arbitrary ZIP paths.
                with z.open(entry['path']) as source, partial.open('wb') as out:
                    shutil.copyfileobj(source, out, 1024 * 1024)
                if not matches(partial, entry):
                    raise RuntimeError('Extracted file failed verification: ' + entry['path'])
                os.replace(partial, target)
    print(name + ': ready (SHA-256 verified).', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', choices=['All', 'Sponza', 'EmeraldSquare'], default='All')
    parser.add_argument('--media-root', type=Path, default=ROOT / 'media')
    parser.add_argument('--cache-dir', type=Path, default=ROOT / 'build/downloads')
    parser.add_argument('--emerald-archive', type=Path, help='Use an already downloaded official ZIP')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if not args.media_root.is_dir():
        raise RuntimeError('Media directory is missing. Run setup_vs2022.bat first (Packman creates media), '
                           'or pass --media-root pointing to an existing directory.')
    manifest = json.loads((ROOT / 'scripts/scene-assets.json').read_text(encoding='utf-8'))
    for name in manifest if args.scene == 'All' else [args.scene]:
        install(name, manifest[name], args.media_root, args.cache_dir, args.emerald_archive, args.verify_only)
    print('Original and Lambert scene variants share these assets. Restart Run-Falcor after building Release.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
