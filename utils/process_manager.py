import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core.lz4_packer import generate_trace_profile, run_lz4_pack
from core.param_parser import parse_game_info
from utils.file_ops import validate_separate_trees
from utils.state import slug
from utils.subprocess_utils import hidden_child_process_kwargs


class GameWorker(QThread):
    progress_updated = Signal(int)
    status_updated = Signal(str)
    log_updated = Signal(str)
    eta_updated = Signal(str)
    pipeline_finished = Signal(bool, str)

    def __init__(self, game_dir, output_dir, settings, custom_config=None, traces_dir=None,
                 lz4_level=9, skip_verify=False, workers=None, source_read_only=False,
                 parent=None):
        super().__init__(parent)
        self.game_dir = Path(game_dir)
        self.output_dir = Path(output_dir)
        self.settings = settings
        self.custom_config = Path(custom_config) if custom_config else None
        self.traces_dir = Path(traces_dir) if traces_dir else None
        self.lz4_level = lz4_level
        self.skip_verify = skip_verify
        self.workers = workers
        self.source_read_only = source_read_only
        self._cancelled = False
        self._active_process = None

    def cancel(self):
        self._cancelled = True
        process = self._active_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _set_active_process(self, process):
        self._active_process = process
        if process is not None and self._cancelled and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _pack_progress(self, fraction, stage):
        stage = stage.casefold()
        if stage == "pack":
            value = 15 + fraction * 70
            status = "Packing LZ4 (AMPR) directly from source…"
        elif stage == "verify":
            value = 85 + fraction * 7
            status = "Verifying packed chunks…"
        elif stage == "compare":
            value = 92 + fraction * 6
            status = "Comparing against source…"
        elif stage == "loose":
            value = 98 + fraction
            status = "Placing loose files…"
        elif stage == "hash-source":
            value = 15
            status = "Recording source SHA-256 hashes…"
        elif stage == "hash-output":
            value = 99
            status = "Recording output SHA-256 hashes…"
        else:
            return
        self.status_updated.emit(status)
        self.progress_updated.emit(int(value))

    def run(self):
        try:
            if not self.game_dir.is_dir():
                raise FileNotFoundError(f"Game folder not found: {self.game_dir}")
            validate_separate_trees(self.game_dir, self.output_dir)
            self.log_updated.emit(f"--- Processing {self.game_dir.name} ---")
            self.status_updated.emit("Reading game info…")
            self.progress_updated.emit(2)
            info = parse_game_info(self.game_dir)
            self.log_updated.emit(f"Title: {info['title']} | ID: {info['title_id']}")

            if self._cancelled:
                self.pipeline_finished.emit(False, "Cancelled by user.")
                return

            self.progress_updated.emit(15)

            if self._cancelled:
                self.pipeline_finished.emit(False, "Cancelled by user.")
                return

            self.status_updated.emit("Packing LZ4 (AMPR) directly from source…")

            run_lz4_pack(
                source_dir=self.game_dir,
                output_dir=self.output_dir,
                settings=self.settings,
                custom_config=self.custom_config,
                traces_dir=self.traces_dir,
                game_name=self.game_dir.name,
                lz4_level=self.lz4_level,
                skip_verify=self.skip_verify,
                workers=self.workers,
                source_read_only=self.source_read_only,
                block_size_kib=int(self.settings.get("block_size_kib", 128)),
                progress_callback=self.log_updated.emit,
                progress_fraction=self._pack_progress,
                eta_callback=self.eta_updated.emit,
                cancel_check=lambda: self._cancelled,
                process_callback=self._set_active_process,
            )

            self.progress_updated.emit(100)
            self.pipeline_finished.emit(True, "AMPR packing completed successfully.")
        except Exception:  # noqa: BLE001 - worker boundary reports full traceback to UI
            self.pipeline_finished.emit(False, traceback.format_exc())


class ProfileWorker(QThread):
    """Auto-create a TOML config from traces found for a game."""
    profile_finished = Signal(bool, str, str)   # ok, toml_name, message

    def __init__(self, traces_dir, toml_dir, title_id, game_name, parent=None):
        super().__init__(parent)
        self.traces_dir = Path(traces_dir)
        self.toml_dir = Path(toml_dir)
        self.title_id = title_id
        self.game_name = game_name

    def run(self):
        try:
            name = f"{self.title_id or slug(self.game_name)}.toml"
            generate_trace_profile(self.traces_dir, self.toml_dir / name, self.game_name)
            self.profile_finished.emit(True, name, f"Auto-generated {name} from traces")
        except Exception as e:  # noqa: BLE001 - worker boundary reports message to UI
            self.profile_finished.emit(False, "", str(e))
        
EXTRACT_SKIP_NAMES = {"ampr_assets.index", "ampr_assets.index.crc",
                      "ampr_assets.index.runtime", "ampr_emu.index"}


def _is_pack_artifact(rel_posix: str) -> bool:
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


class ExtractWorker(QThread):
    progress_updated = Signal(int)
    status_updated = Signal(str)
    log_updated = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, source_dir, output_dir, parent=None):
        super().__init__(parent)
        self.source_dir = Path(source_dir)
        self.output_dir = Path(output_dir)

    def run(self):
        try:
            import os
            import re
            import shutil
            import subprocess

            from core.lz4_packer import TOOL_CWD, TOOLS_DIR
            from utils.file_ops import validate_separate_trees
            from utils.tool_runner import command_for
            prog_re = re.compile(r"\[(\w+)\s+(\d+)%\]")

            validate_separate_trees(self.source_dir, self.output_dir)
            idx = self.source_dir / "ampr_assets.index"
            if not idx.is_file():
                raise FileNotFoundError(f"ampr_assets.index not found in {self.source_dir}")
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # 1) Unpack the .pak volumes (0–70%)
            self.status_updated.emit("Extracting packed assets…")
            cmd_variants = [
                [*command_for(TOOLS_DIR / "ampr_pack.py"), "unpack",
                 "--index", str(idx), "--output", str(self.output_dir)],
                [*command_for(TOOLS_DIR / "ampr_pack.py"), "unpack",
                 "--index", str(idx), "--out", str(self.output_dir)],
            ]
            last_err = ""
            ok = False
            for cmd in cmd_variants:
                with subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True,
                                      encoding="utf-8", errors="replace",
                                      cwd=str(TOOL_CWD),
                                      **hidden_child_process_kwargs()) as proc:
                    if proc.stdout is None:
                        raise RuntimeError("Unpack process did not expose an output stream")
                    for line in proc.stdout:
                        line = line.strip()
                        if not line:
                            continue
                        self.log_updated.emit(line)
                        m = prog_re.search(line)
                        if m:
                            self.progress_updated.emit(int(int(m.group(2)) * 0.7))
                    proc.wait()
                    if proc.returncode == 0:
                        ok = True
                        break
                    last_err = f"return code {proc.returncode}"
            if not ok:
                raise RuntimeError(f"ampr_pack unpack failed ({last_err}). "
                                   f"Check the log for the CLI usage error.")

            # 2) Rebuild the original tree: copy loose (non-packed) files (70–100%)
            self.status_updated.emit("Copying loose files…")
            files = []
            for dirpath, dirnames, filenames in os.walk(self.source_dir):
                dirnames.sort()
                rel_dir = Path(dirpath).relative_to(self.source_dir).as_posix()
                if rel_dir != "." and rel_dir.split("/")[0] not in {"decrypted", "working"}:
                    (self.output_dir / rel_dir).mkdir(parents=True, exist_ok=True)
                for fn in sorted(filenames):
                    full = Path(dirpath) / fn
                    rel = full.relative_to(self.source_dir).as_posix()
                    if _is_pack_artifact(rel):
                        continue
                    files.append((full, self.output_dir / rel))
            for i, (src, dst) in enumerate(files, 1):
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                self.progress_updated.emit(70 + int(i / max(1, len(files)) * 30))

            self.progress_updated.emit(100)
            self.finished.emit(True, f"Extraction completed: {self.output_dir}")
        except Exception:  # noqa: BLE001 - worker boundary reports full traceback to UI
            import traceback
            self.finished.emit(False, traceback.format_exc())
