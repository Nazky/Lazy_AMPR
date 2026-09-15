"""Per-build evidence stored outside the deployable game tree."""
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from utils.subprocess_utils import hidden_child_process_kwargs
from version import VERSION


class BuildDiagnostics:
    def __init__(self, source, output, tool_command, tool_cwd, cancel, report):
        self.source = Path(source)
        self.output = Path(output)
        base = self.output.parent / (self.output.name + '.build-diagnostics')
        base.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix='build-', dir=base))
        self.command = tool_command
        self.cwd = tool_cwd
        self.cancel = cancel
        self.report = report or (lambda message: None)
        self.source_hashes = {}
        self.replacement_hashes = {}
        self.report(f'[INFO] Build diagnostics: {self.path}')
        (self.path / 'status.txt').write_text('Incomplete: build has not finished.\n', encoding='utf-8')

    def hash_file(self, path):
        digest = hashlib.sha256()
        with Path(path).open('rb') as stream:
            while True:
                self.cancel()
                block = stream.read(8 * 1024 * 1024)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest()

    def hash_tree(self, root, filename):
        hashes = {}
        files = sorted(p for p in root.rglob('*') if p.is_file())
        with (self.path / filename).open('w', encoding='utf-8', newline='\n') as result:
            for number, path in enumerate(files, 1):
                relative = path.relative_to(root).as_posix()
                value = self.hash_file(path)
                hashes[relative] = value
                # JSON escaping preserves filenames containing newlines.
                result.write(f'{value}  {json.dumps(relative, ensure_ascii=False)}\n')
                self.report(f'[HASH] {filename}: {number}/{len(files)} files: {relative}')
        return hashes

    def tool(self, *args):
        self.cancel()
        completed = subprocess.run(
            [*self.command, *args], cwd=self.cwd, capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=120,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'},
            check=False,
            **hidden_child_process_kwargs(),
        )
        if completed.returncode:
            raise RuntimeError(f'Diagnostics command failed: {args}: {completed.stderr}')
        return completed.stdout

    def capture_inputs(self, index, profile, workers, level, skip_verify):
        self.source_hashes = self.hash_tree(self.source, 'source-tree.sha256')
        shutil.copy2(profile, self.path / 'profile.toml')
        index_hash = self.hash_file(index)
        profile_hash = self.hash_file(profile)
        (self.path / 'ampr-index.sha256').write_text(index_hash + '\n', encoding='utf-8')
        (self.path / 'profile.sha256').write_text(profile_hash + '\n', encoding='utf-8')
        packages = {}
        for name in ('lz4', 'PySide6', 'FATtools', 'toml', 'pyinstaller'):
            try:
                packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                packages[name] = 'metadata unavailable in this build'
        worker_internal = Path(self.command[-1]).parent / '_internal'
        worker_packages = {d.metadata['Name']: d.version for d in
                           importlib.metadata.distributions(path=[str(worker_internal)])}
        packer_sources = {p.name: self.hash_file(p) for p in
                          Path(self.command[-1]).parent.glob('ampr_pack*.py')}
        evidence = {
            'lazy_ampr_version': VERSION,
            'os': platform.platform(),
            'python': sys.version,
            'rust': 'not used by this pipeline',
            'packages': packages,
            'packer_version': self.tool('--version').strip(),
            'packer_packages': worker_packages,
            'packer_source_sha256': packer_sources,
            'packer_sha256': self.hash_file(self.command[-1]),
            'packer_commit': 'not recorded; available tool/source hashes recorded instead',
            'source_root': str(self.source.resolve()),
            'output_root': str(self.output.resolve()),
            'ampr_index_sha256': index_hash,
            'profile_sha256': profile_hash,
            'worker_count': workers,
            'compression_level': level,
            'verification_skipped': skip_verify,
        }
        (self.path / 'build-environment.txt').write_text(json.dumps(evidence, indent=2), encoding='utf-8')

    def record_replacements(self, replacements):
        self.replacement_hashes = {name.casefold(): self.hash_file(path)
                                   for name, path in replacements.items()}
        (self.path / 'intentional-replacements.json').write_text(
            json.dumps(self.replacement_hashes, indent=2), encoding='utf-8')

    def finish(self):
        index = self.output / 'ampr_assets.index'
        inspect = self.tool('inspect', '--index', str(index))
        listing = self.tool('list', '--index', str(index), '--json')
        (self.path / 'pack-inspect.txt').write_text(inspect, encoding='utf-8')
        (self.path / 'pack-list.json').write_text(listing, encoding='utf-8')
        rows = json.loads(listing)
        for packed, name in ((True, 'packed-files.txt'), (False, 'loose-files.txt')):
            paths = [row['path'] for row in rows if row['packed'] == packed]
            (self.path / name).write_text('\n'.join(paths) + '\n', encoding='utf-8')
        output_hashes = self.hash_tree(self.output, 'output-files.sha256')
        failures = []
        for row in rows:
            if row['packed']:
                continue
            relative = row['path'].removeprefix('/app0/')
            if relative.casefold() in self.replacement_hashes:
                target = self.output / relative
                if not target.is_file() or self.hash_file(target) != self.replacement_hashes[relative.casefold()]:
                    failures.append(relative)
                continue
            if relative not in self.source_hashes or output_hashes.get(relative) != self.source_hashes[relative]:
                failures.append(relative)
        with index.open('rb') as stream:
            format_header = stream.read(12)
        (self.path / 'pack-format.txt').write_text(format_header.hex() + '\n', encoding='utf-8')
        environment_path = self.path / 'build-environment.txt'
        environment = json.loads(environment_path.read_text(encoding='utf-8'))
        environment['ampr_pack_format_header'] = format_header.hex()
        environment['ampr_pack_format_magic'] = format_header[:8].decode('ascii', errors='replace')
        environment['ampr_pack_format_version'] = int.from_bytes(format_header[8:12], 'little')
        environment_path.write_text(json.dumps(environment, indent=2), encoding='utf-8')
        if failures:
            (self.path / 'status.txt').write_text('FAILED: loose files differ or are missing:\n' + '\n'.join(failures), encoding='utf-8')
            raise RuntimeError(f'Output loose-file audit failed; see {self.path / "status.txt"}')
        (self.path / 'status.txt').write_text('Complete. All manifest loose files match source SHA-256 or recorded intentional replacements.\n', encoding='utf-8')
