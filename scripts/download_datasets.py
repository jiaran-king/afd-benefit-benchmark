"""Download versioned raw/frozen datasets and verify compressed and original bytes."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "datasets/releases/2026-10-12.json"
CHUNK = 8 * 1024 * 1024


def verify(path, expected):
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(CHUNK), b""):
            count += len(data)
            digest.update(data)
    if count != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
        raise ValueError(f"Size/SHA256 mismatch: {path.name}")


def download(asset, output):
    output = output.resolve()
    destination = output / asset["uncompressed"]["path"]
    if not destination.resolve().is_relative_to(output):
        raise ValueError("Dataset destination must stay inside the output directory")
    if destination.exists():
        verify(destination, asset["uncompressed"])
        print(f"Already verified: {destination}", flush=True)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=destination.parent) as tmp:
        archive = Path(tmp) / "payload.gz"
        request = Request(asset["url"], headers={"User-Agent": "afd-benefit-benchmark/1"})
        size = 0
        print(f"Downloading: {asset['filename']}", flush=True)
        with urlopen(request, timeout=60) as response, archive.open("xb") as dst:
            for data in iter(lambda: response.read(CHUNK), b""):
                size += len(data)
                if size > asset["bytes"]:
                    raise ValueError("Downloaded file exceeds the frozen asset size")
                dst.write(data)
        verify(archive, asset)
        unpacked = Path(tmp) / "verified-payload"
        size = 0
        with gzip.open(archive, "rb") as source, unpacked.open("xb") as dst:
            for data in iter(lambda: source.read(CHUNK), b""):
                size += len(data)
                if size > asset["uncompressed"]["bytes"]:
                    raise ValueError("Uncompressed file exceeds the frozen source size")
                dst.write(data)
        verify(unpacked, asset["uncompressed"])
        # Publish only verified bytes, without overwriting a concurrently created file.
        os.link(unpacked, destination)
    print(f"Verified: {destination}", flush=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("raw", "frozen", "all"), default="frozen")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    names = ("raw", "frozen") if args.dataset == "all" else (args.dataset,)
    for name in names:
        download(manifest["datasets"][name], args.output_dir)


if __name__ == "__main__":
    main()
