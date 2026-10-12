"""Exercise data integrity boundaries using local compressed fixtures, without network."""
import gzip
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "download_datasets", Path(__file__).resolve().parents[1] / "scripts/download_datasets.py")
downloader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(downloader)


class DatasetDownloadTests(unittest.TestCase):
    def fixture(self):
        original = b'{"conversations":[]}\n'
        packed = gzip.compress(original, mtime=0)
        asset = {"filename": "fixture.json.gz", "url": "https://example.invalid/fixture.json.gz",
                 "bytes": len(packed), "sha256": hashlib.sha256(packed).hexdigest(),
                 "uncompressed": {"path": "raw/fixture.json", "bytes": len(original),
                                  "sha256": hashlib.sha256(original).hexdigest()}}
        return original, packed, asset

    def test_download_and_verified_reuse_without_network(self):
        original, packed, asset = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(downloader, "urlopen", return_value=io.BytesIO(packed)) as request:
                path = downloader.download(asset, Path(tmp))
                self.assertEqual(path.read_bytes(), original)
                downloader.download(asset, Path(tmp))
                self.assertEqual(request.call_count, 1)

    def test_corrupt_or_truncated_download_never_published(self):
        _, packed, asset = self.fixture()
        for payload in (packed[:-5], b"x" * len(packed)):
            with self.subTest(payload_length=len(payload)), tempfile.TemporaryDirectory() as tmp:
                with patch.object(downloader, "urlopen", return_value=io.BytesIO(payload)):
                    with self.assertRaises(ValueError):
                        downloader.download(asset, Path(tmp))
                self.assertFalse((Path(tmp) / "raw/fixture.json").exists())
                self.assertEqual(list((Path(tmp) / "raw").iterdir()), [])

    def test_original_hash_checked_even_when_archive_matches(self):
        _, packed, asset = self.fixture()
        asset["uncompressed"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(downloader, "urlopen", return_value=io.BytesIO(packed)):
                with self.assertRaises(ValueError):
                    downloader.download(asset, Path(tmp))
            self.assertFalse((Path(tmp) / "raw/fixture.json").exists())

    def test_existing_different_file_is_not_overwritten(self):
        _, _, asset = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw/fixture.json"
            path.parent.mkdir()
            path.write_bytes(b"existing")
            with patch.object(downloader, "urlopen") as request:
                with self.assertRaises(ValueError):
                    downloader.download(asset, Path(tmp))
                request.assert_not_called()
            self.assertEqual(path.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
