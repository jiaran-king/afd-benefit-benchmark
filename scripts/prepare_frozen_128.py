"""Derive the exact C12/128 payload from the existing frozen-256 Release file."""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def prepare(parent_file, output):
    data = ROOT / 'datasets/frozen-128'
    expected = json.loads((data / 'manifest.json').read_text())
    parent = json.loads((ROOT / 'datasets/frozen-256/manifest.json').read_text())
    with gzip.open(data / 'request-index.csv.gz', 'rt') as f:
        index = {r['id']: r for r in csv.DictReader(f)}
    assert not output.exists(), 'Output directory exists; do not overwrite frozen inputs'
    assert parent_file.is_file(), 'Pass the uncompressed frozen-256 Release file'
    output.mkdir(parents=True)
    parent_sha, subset_sha = hashlib.sha256(), hashlib.sha256()
    seen, size = set(), 0
    temporary = output / 'requests.jsonl.partial'
    try:
        with parent_file.open('rb') as source, temporary.open('xb') as dest:
            for line in source:
                parent_sha.update(line)
                match = re.search(rb'"id"\s*:\s*"([^"\n]+)"', line[:256])
                assert match, 'Unexpected parent record header'
                rid = match[1].decode()
                if rid not in index:
                    continue
                assert rid not in seen
                assert hashlib.sha256(line).hexdigest() == index[rid]['original_line_sha256']
                dest.write(line)
                subset_sha.update(line)
                size += len(line)
                seen.add(rid)
        assert parent_sha.hexdigest() == parent['request_sha256'] == expected['frozen_parent_request_sha256']
        assert seen == set(index) and len(seen) == 3725
        assert subset_sha.hexdigest() == expected['request_sha256'] and size == expected['request_bytes']
        temporary.rename(output / 'requests.jsonl')
        for name in ['manifest.json', 'priorities.json', 'route-afd.json', 'route-nonafd.json', 'request-index.csv.gz']:
            shutil.copyfile(data / name, output / name)
        result = dict(status='passed', requests=len(seen), sessions=128,
            request_sha256=subset_sha.hexdigest(), parent_request_sha256=parent_sha.hexdigest(), bytes=size,
            scope='Exact frozen bytes and complete source sessions; no retokenization or hardware execution.')
        (output / 'subset-audit.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
        return result
    except Exception:
        # Preserve a partial file for inspection; never present it as frozen input.
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True, help='Uncompressed existing frozen-256 requests.jsonl')
    parser.add_argument('--output', type=Path, required=True, help='A new local output directory')
    args = parser.parse_args()
    prepare(args.parent, args.output)
