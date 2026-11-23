import json
from pathlib import Path
import tempfile
import unittest

from detection.artifacts import package, safe_relative, sha, unpack


class ArtifactTests(unittest.TestCase):
    def test_rejects_traversal_private_and_windows_paths(self):
        for name in ['../escape', '/absolute', 'D:/outside', 'a\\b', '.env.database', 'a/../b', '.git/config']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_relative(name)

    def test_restore_preserves_bytes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'producer'; source.mkdir()
            (source/'sample.txt').write_bytes(b'labels\r\n0 0.5 0.5 0.2 0.2\r\n')
            bundle = source/'artifacts.zip.xz'
            metadata = package(source, [source/'sample.txt'], bundle)
            target = root/'consumer'
            result = unpack(bundle, target, metadata['sha256'])
            self.assertEqual(result['verified_files'], 1)
            self.assertEqual(sha(target/'sample.txt'), sha(source/'sample.txt'))
            (target/'sample.txt').write_text('local changes')
            with self.assertRaises(ValueError):
                unpack(bundle, target, metadata['sha256'])
            self.assertEqual((target/'sample.txt').read_text(), 'local changes')

    def test_wrong_archive_hash_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root/'not-an-archive.xz'; bundle.write_bytes(b'git lfs pointer')
            with self.assertRaises(ValueError):
                unpack(bundle, root/'consumer', '0'*64)
            self.assertFalse((root/'consumer').exists())
