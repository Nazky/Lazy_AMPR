"""Rebuild an original game tree from an AMPR-packed folder (GUI-free)."""
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from utils.file_ops import validate_separate_trees
from utils.subprocess_utils import hidden_child_process_kwargs
from utils.tool_runner import command_for

EXTRACT_SKIP_NAMES = {"ampr_assets.index", "ampr_assets.index.crc",
                      "ampr_assets.index.runtime", "ampr_emu.index"}

PROGRESS_RE = re.compile(r"\[(\w+)\s+(\d+)%\]")


def is_pack_artifact(rel_posix: str) -> bool:
    """True for files that are pack by-products, not part of the original game tree."""
    parts = rel_posix.split("/")
    name = parts[-1]
    if name in EXTRACT_SKIP_NAMES:
        return True
    if name.startswith("ampr_assets-") and name.endswith(".pak"):
        return True
    if name.endswith(("_auto_profile.toml", "_custom_override.toml", "_trace_profile.toml")):
        return True
    return parts[0] in {"decrypted", "working"}


def run_extract(source_dir, output_dir,
                progress_callback: Callable[[str], None] | None = None,
                progress_percent: Callable[[int], None] | None = None,
                status_callback: Callable[[str], None] | None = None,
                cancel_check: Callable[[], bool] | None = None,
                process_callback: Callable[[subprocess.Popen | None], None] | None = None) -> Path:
    from core.lz4_packer import TOOL_CWD, TOOLS_DIR

    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    log = progress_callback or (lambda line: None)
    percent = progress_percent or (lambda value: None)
    status = status_callback or (lambda text: None)

    def check_cancelled():
        if cancel_check and cancel_check():
            raise RuntimeError("Cancelled by user.")

    validate_separate_trees(source_dir, output_dir)
    idx = source_dir / "ampr_assets.index"
    if not idx.is_file():
        raise FileNotFoundError(f"ampr_assets.index not found in {source_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) Unpack the .pak volumes (0–70%)
    status("Extracting packed assets…")
    cmd_variants = [
        [*command_for(TOOLS_DIR / "ampr_pack.py"), "unpack",
         "--index", str(idx), "--output", str(output_dir)],
        [*command_for(TOOLS_DIR / "ampr_pack.py"), "unpack",
         "--index", str(idx), "--out", str(output_dir)],
    ]
    last_err = ""
    ok = False
    for cmd in cmd_variants:
        check_cancelled()
        with subprocess.Popen(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace",
                              cwd=str(TOOL_CWD),
                              **hidden_child_process_kwargs()) as proc:
            if process_callback:
                process_callback(proc)
            try:
                if proc.stdout is None:
                    raise RuntimeError("Unpack process did not expose an output stream")
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    log(line)
                    m = PROGRESS_RE.search(line)
                    if m:
                        percent(int(int(m.group(2)) * 0.7))
                proc.wait()
            finally:
                if process_callback:
                    process_callback(None)
            check_cancelled()
            if proc.returncode == 0:
                ok = True
                break
            last_err = f"return code {proc.returncode}"
    if not ok:
        raise RuntimeError(f"ampr_pack unpack failed ({last_err}). "
                           f"Check the log for the CLI usage error.")

    # 2) Rebuild the original tree: copy loose (non-packed) files (70–100%)
    status("Copying loose files…")
    files = []
    for dirpath, dirnames, filenames in os.walk(source_dir):
        dirnames.sort()
        rel_dir = Path(dirpath).relative_to(source_dir).as_posix()
        if rel_dir != "." and rel_dir.split("/")[0] not in {"decrypted", "working"}:
            (output_dir / rel_dir).mkdir(parents=True, exist_ok=True)
        for fn in sorted(filenames):
            full = Path(dirpath) / fn
            rel = full.relative_to(source_dir).as_posix()
            if is_pack_artifact(rel):
                continue
            files.append((full, output_dir / rel))
    for i, (src, dst) in enumerate(files, 1):
        check_cancelled()
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        percent(70 + int(i / max(1, len(files)) * 30))

    percent(100)
    return output_dir
