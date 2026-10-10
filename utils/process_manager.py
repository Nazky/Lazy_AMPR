import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core.extractor import run_extract
from core.lz4_packer import generate_trace_profile, pack_stage_progress, run_lz4_pack
from core.param_parser import parse_game_info
from utils.file_ops import validate_separate_trees
from utils.state import slug


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
        mapped = pack_stage_progress(fraction, stage)
        if mapped is None:
            return
        value, status = mapped
        self.status_updated.emit(status)
        self.progress_updated.emit(value)

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
            run_extract(
                self.source_dir,
                self.output_dir,
                progress_callback=self.log_updated.emit,
                progress_percent=self.progress_updated.emit,
                status_callback=self.status_updated.emit,
            )
            self.finished.emit(True, f"Extraction completed: {self.output_dir}")
        except Exception:  # noqa: BLE001 - worker boundary reports full traceback to UI
            self.finished.emit(False, traceback.format_exc())
