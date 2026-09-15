"""The user-selected AMPR runtime, pinned and installed only in game outputs."""
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

RUNTIME_RELATIVE = 'fakelib/libSceAmpr.sprx'
RUNTIME_SHA256 = '69e6c4d5e4f5fb83c9e01815db5861c4c75734acbf4595cafa50d4c218116d1a'
RUNTIME_PATH = Path(__file__).resolve().parents[1] / 'resources' / RUNTIME_RELATIVE


def install_ampr_runtime(source, output):
    """Return metadata overrides; never modify the original game or a hardlink."""
    if not (source / RUNTIME_RELATIVE).is_file():
        return {}
    if not RUNTIME_PATH.is_file():
        raise FileNotFoundError(f'Required bundled AMPR runtime is missing: {RUNTIME_PATH}')
    if hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest() != RUNTIME_SHA256:
        raise ValueError('Bundled AMPR runtime SHA-256 mismatch; refusing to use a different library.')
    destination = output / RUNTIME_RELATIVE
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.ampr-runtime-', dir=destination.parent)
    os.close(handle)
    try:
        shutil.copy2(RUNTIME_PATH, temporary)
        if hashlib.sha256(Path(temporary).read_bytes()).hexdigest() != RUNTIME_SHA256:
            raise ValueError('Copied AMPR runtime SHA-256 mismatch.')
        os.replace(temporary, destination)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    return {RUNTIME_RELATIVE: destination}
