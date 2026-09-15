import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.ampr_index import HEADER_STRUCT, RECORD_STRUCT
from core.ampr_runtime import (
    RUNTIME_PATH,
    RUNTIME_RELATIVE,
    RUNTIME_SHA256,
    install_ampr_runtime,
)
from core.lz4_packer import run_lz4_pack
from external.ampr_emu.tools.ampr_pack_format import load_manifest


class AmprRuntimeTests(unittest.TestCase):
    def test_bundled_bytes_match_user_selected_hash(self):
        self.assertEqual(hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest(), RUNTIME_SHA256)

    def test_absent_marker_does_not_install_or_require_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('core.ampr_runtime.RUNTIME_PATH', root / 'missing'):
                self.assertEqual(install_ampr_runtime(root, root / 'out'), {})
            self.assertFalse((root / 'out').exists())

    def test_missing_or_tampered_bundle_fails_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / 'source', root / 'output'
            (source / 'fakelib').mkdir(parents=True)
            (source / RUNTIME_RELATIVE).write_bytes(b'original')
            (output / 'fakelib').mkdir(parents=True)
            (output / RUNTIME_RELATIVE).write_bytes(b'previous')
            replacement = root / 'replacement'
            for data in (None, b'incorrect'):
                if data is not None:
                    replacement.write_bytes(data)
                with patch('core.ampr_runtime.RUNTIME_PATH', replacement), \
                        self.assertRaises((FileNotFoundError, ValueError)):
                    install_ampr_runtime(source, output)
                self.assertEqual((output / RUNTIME_RELATIVE).read_bytes(), b'previous')

    def test_pack_uses_replacement_metadata_preserves_source_and_breaks_old_hardlink(self):
        for read_only in (False, True):
            with self.subTest(read_only=read_only), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, output = root / 'source', root / 'output'
                (source / 'fakelib').mkdir(parents=True)
                (source / RUNTIME_RELATIVE).write_bytes(b'old runtime')
                (source / 'fakelib/other.sprx').write_bytes(b'keep other library')
                (source / 'ampr_emu.index').write_bytes(b'old source index')
                (source / 'assets').mkdir()
                (source / 'assets/data.uasset').write_bytes(b'asset' * 20000)
                before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
                (output / 'fakelib').mkdir(parents=True)
                os.link(source / RUNTIME_RELATIVE, output / RUNTIME_RELATIVE)
                run_lz4_pack(source, output, {'lz4_level': 1, 'auto_loose_large': False,
                                             'use_hardlinks': True}, source_read_only=read_only, workers=1)
                self.assertEqual(before, {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()})
                self.assertFalse(os.path.samefile(source / RUNTIME_RELATIVE, output / RUNTIME_RELATIVE))
                self.assertEqual(hashlib.sha256((output / RUNTIME_RELATIVE).read_bytes()).hexdigest(), RUNTIME_SHA256)
                self.assertEqual((output / 'fakelib/other.sprx').read_bytes(), b'keep other library')
                manifest = load_manifest(output / 'ampr_assets.index')
                for file_id, record in enumerate(manifest.files, 1):
                    if manifest.file_path(file_id) == '/app0/' + RUNTIME_RELATIVE:
                        self.assertEqual(record.logical_size, RUNTIME_PATH.stat().st_size)
                        self.assertEqual(record.flags & 1, 0)
                        raw = (output / 'ampr_emu.index').read_bytes()
                        size = RECORD_STRUCT.unpack_from(raw, HEADER_STRUCT.size + (file_id - 1) * RECORD_STRUCT.size)[2]
                        self.assertEqual(size, record.logical_size)
                        break
                else:
                    self.fail('runtime missing from manifest')
                evidence = next(output.with_name('output.build-diagnostics').glob('build-*'))
                replacements = json.loads((evidence / 'intentional-replacements.json').read_text())
                self.assertEqual(replacements[RUNTIME_RELATIVE.casefold()], RUNTIME_SHA256)
                self.assertTrue((evidence / 'status.txt').read_text().startswith('Complete'))
