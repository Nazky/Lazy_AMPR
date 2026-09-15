import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.build_diagnostics import BuildDiagnostics


class BuildDiagnosticsTests(unittest.TestCase):
    def test_frozen_entry_point_uses_utf8_for_json_paths(self):
        command = MagicMock()
        command.main.return_value = 0
        stdout, stderr = MagicMock(), MagicMock()
        entry = Path(__file__).resolve().parents[1] / 'worker_ampr_pack.py'
        with patch.dict(sys.modules, {'ampr_pack': command}), \
                patch('sys.stdout', stdout), patch('sys.stderr', stderr), \
                self.assertRaises(SystemExit) as result:
            runpy.run_path(str(entry), run_name='__main__')
        self.assertEqual(result.exception.code, 0)
        stdout.reconfigure.assert_called_once_with(encoding='utf-8')
        stderr.reconfigure.assert_called_once_with(encoding='utf-8')

    def test_missing_or_changed_loose_file_is_rejected(self):
        for output_data in (None, b'changed'):
            with self.subTest(output_data=output_data), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, output = root / 'source', root / 'output'
                source.mkdir()
                output.mkdir()
                (source / 'eboot.bin').write_bytes(b'original')
                if output_data is not None:
                    (output / 'eboot.bin').write_bytes(output_data)
                (output / 'ampr_assets.index').write_bytes(b'AMPRPAK4' + b'\0' * 4)
                audit = BuildDiagnostics(source, output, [], root, lambda: None, None)
                audit.source_hashes = audit.hash_tree(source, 'source-tree.sha256')
                (audit.path / 'build-environment.txt').write_text('{}')
                listing = json.dumps([{'path': '/app0/eboot.bin', 'packed': False}])
                with patch.object(audit, 'tool', side_effect=['inspection', listing]), \
                        self.assertRaisesRegex(RuntimeError, 'loose-file audit failed'):
                    audit.finish()
                self.assertIn('eboot.bin', (audit.path / 'status.txt').read_text())
                self.assertNotIn(audit.path, output.rglob('*'))

    def test_cancelled_hash_is_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            (source / 'file').write_bytes(b'data')
            def cancel():
                raise RuntimeError('cancelled')
            audit = BuildDiagnostics(source, root / 'output', [], root, cancel, None)
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                audit.hash_tree(source, 'source-tree.sha256')
            self.assertTrue((audit.path / 'status.txt').read_text().startswith('Incomplete'))
