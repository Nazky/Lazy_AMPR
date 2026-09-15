import os
import shutil
from pathlib import Path


def validate_separate_trees(source: Path, output: Path) -> None:
    """Reject source/output layouts that could overwrite the input tree."""
    source = Path(source).resolve()
    output = Path(output).resolve()
    if source == output:
        raise ValueError("Output folder must be different from the source folder.")
    if output.is_relative_to(source):
        raise ValueError("Output folder cannot be inside the source folder.")
    if source.is_relative_to(output):
        raise ValueError("Output folder cannot contain the source folder.")

def detect_games(path: Path, max_depth: int = 4):
    """
    Recursively find PS5 game folders starting from path.
    A game folder contains param.json or sce_sys/param.json.
    Returns list of Path objects, sorted alphabetically.
    """
    path = Path(path)
    if not path.is_dir():
        return []

    # Check if the path itself is a game
    if (path / "param.json").exists() or (path / "sce_sys" / "param.json").exists():
        return [path]

    games = []
    seen = set()

    def _scan(folder: Path, depth: int):
        if depth > max_depth:
            return
        try:
            for child in sorted(folder.iterdir()):
                if not child.is_dir():
                    continue
                # Skip hidden folders and common non-game dirs
                if child.name.startswith("."):
                    continue
                # Check if this child is a game
                if (child / "param.json").exists() or (child / "sce_sys" / "param.json").exists():
                    real = child.resolve()
                    if real not in seen:
                        seen.add(real)
                        games.append(child)
                else:
                    # Recurse into subfolders
                    _scan(child, depth + 1)
        except (OSError, PermissionError):
            pass

    _scan(path, 0)
    return games

def _link_or_copy(src, dst):
    """Hardlink when possible (instant, zero space); real copy across devices."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)

def copy_tree_with_progress(src: Path, dst: Path, progress_cb=None):
    """Mirror src into dst (4 MiB chunk progress), hardlinking instead of copying when possible."""
    src, dst = Path(src), Path(dst)
    files, total = [], 0
    for dirpath, _, filenames in os.walk(src):
        for fn in filenames:
            p = Path(dirpath) / fn
            try: sz = p.stat().st_size
            except OSError: sz = 0
            files.append(p); total += sz

    done = 0
    dst.mkdir(parents=True, exist_ok=True)
    for p in files:
        target = dst / p.relative_to(src)
        if target.exists():
            done += p.stat().st_size
            if progress_cb and total: progress_cb(done / total)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        st = p.stat()
        if st.st_size > 64 * 1024 * 1024:
            _link_or_copy(p, target)          # big files: hardlink instantly
            done += st.st_size
        else:
            with open(p, "rb") as fs, open(target, "wb") as fd:   # small files: chunked copy
                while chunk := fs.read(4 * 1024 * 1024):
                    fd.write(chunk)
                    done += len(chunk)
                    if progress_cb and total: progress_cb(done / total)
            continue
        if progress_cb and total: progress_cb(done / total)
    return total
