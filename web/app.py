"""FastAPI web front end for headless/server use (Docker, Unraid).

Every path the browser sends is resolved and must stay inside one of the
configured browse roots (LAZY_AMPR_ROOTS), so the UI cannot reach the rest of
the container file system.
"""
import base64
import binascii
import os
import secrets
import shutil
import threading
from pathlib import Path

import tomllib
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.extractor import run_extract
from core.lz4_packer import generate_trace_profile, pack_stage_progress, run_lz4_pack
from core.param_parser import parse_game_info
from utils import net
from utils.file_ops import detect_games, validate_separate_trees
from utils.state import TOML_DIR, State, _normalized_settings, slug
from version import APP_NAME, VERSION
from web.jobs import Job, JobManager

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _env_roots() -> list[Path]:
    raw = os.environ.get("LAZY_AMPR_ROOTS", "/games,/output")
    roots = []
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if item:
            roots.append(Path(item).expanduser().resolve())
    return roots


ROOTS = _env_roots()
DEFAULT_OUTPUT = os.environ.get("LAZY_AMPR_DEFAULT_OUTPUT", "/output").strip()
AUTH_USER = os.environ.get("LAZY_AMPR_USERNAME", "admin")
AUTH_PASSWORD = os.environ.get("LAZY_AMPR_PASSWORD", "")

state = State()
state_lock = threading.RLock()
jobs = JobManager()

app = FastAPI(title=APP_NAME, version=VERSION, docs_url="/api/docs", redoc_url=None)


# ---------------------------------------------------------------- auth
@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if not AUTH_PASSWORD or request.url.path == "/healthz":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            user, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        except (binascii.Error, UnicodeDecodeError):
            user, password = "", ""
        if secrets.compare_digest(user.encode(), AUTH_USER.encode()) and \
                secrets.compare_digest(password.encode(), AUTH_PASSWORD.encode()):
            return await call_next(request)
    return Response(status_code=401, headers={"WWW-Authenticate": f'Basic realm="{APP_NAME}"'})


# ---------------------------------------------------------------- paths
def allowed_path(raw: str | None, *, must_exist: bool = True, kind: str = "dir") -> Path:
    if not raw or not str(raw).strip():
        raise HTTPException(400, "Path is required")
    path = Path(str(raw).strip()).expanduser()
    if not path.is_absolute():
        raise HTTPException(400, f"Path must be absolute: {raw}")
    path = path.resolve()
    if not any(path == root or path.is_relative_to(root) for root in ROOTS):
        raise HTTPException(403, f"Path is outside the configured folders: {path}")
    if must_exist:
        if kind == "dir" and not path.is_dir():
            raise HTTPException(404, f"Folder not found: {path}")
        if kind == "file" and not path.is_file():
            raise HTTPException(404, f"File not found: {path}")
    return path


def toml_path(name: str) -> Path:
    safe = Path(name).name
    if safe != name or not safe.casefold().endswith(".toml") or safe.startswith("."):
        raise HTTPException(400, "Invalid TOML filename")
    return TOML_DIR / safe


def default_output_for(game_dir: Path) -> Path:
    base = state.settings.get("output_dir", "").strip() or DEFAULT_OUTPUT
    if base:
        return Path(base) / f"{game_dir.name}_AMPR"
    return game_dir.parent / f"{game_dir.name}_AMPR"


# ---------------------------------------------------------------- games / TOML linking
def auto_link(path: Path, info: dict) -> tuple[str | None, str | None]:
    """Mirror the desktop auto-linking: keep manual links, otherwise match by title/ID."""
    with state_lock:
        entry = state.upsert_game(path, title=info.get("title"), title_id=info.get("title_id"),
                                  content_id=info.get("content_id"))
        if entry.get("toml_src") == "manual":
            name = entry.get("toml")
            if name and (TOML_DIR / name).exists():
                return name, "manual"
            return None, None
        name = entry.get("toml")
        if not (name and (TOML_DIR / name).exists()):
            name = state.auto_toml_for(info.get("title_id", ""), info.get("title", ""),
                                       info.get("content_id", ""))
        if name:
            state.link_toml(path, name, "auto")
            return name, "auto"
        return None, None


def game_payload(path: Path) -> dict:
    info = parse_game_info(path)
    toml, source = auto_link(path, info)
    traces = state.get_game(path) or {}
    traces_dir = traces.get("traces") or (str(path / "traces") if (path / "traces").is_dir() else None)
    output = default_output_for(path)
    return {
        "path": str(path),
        "title": info["title"],
        "title_id": info["title_id"],
        "version": info["version"],
        "sdk_version": info["sdk_version"],
        "content_id": info["content_id"],
        "has_icon": bool(info.get("icon_path")),
        "is_packed": (path / "ampr_assets.index").is_file(),
        "toml": toml,
        "toml_source": source,
        "traces": traces_dir,
        "default_output": str(output),
        "output_exists": output.exists(),
    }


# ---------------------------------------------------------------- API: general
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/info")
def info():
    return {
        "app": APP_NAME,
        "version": VERSION,
        "roots": [{"path": str(r), "exists": r.is_dir()} for r in ROOTS],
        "default_output": DEFAULT_OUTPUT,
        "toml_dir": str(TOML_DIR),
        "cpu_count": os.cpu_count(),
    }


@app.get("/api/browse")
def browse(path: str | None = None):
    if not path:
        return {"path": None, "parent": None, "is_game": False, "entries": [
            {"name": str(r), "path": str(r), "is_game": False}
            for r in ROOTS if r.is_dir()
        ]}
    folder = allowed_path(path)
    entries = []
    try:
        children = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
    except OSError as error:
        raise HTTPException(500, f"Cannot read folder: {error}") from error
    for child in children:
        if child.name.startswith(".") or not child.is_dir():
            continue
        is_game = (child / "sce_sys" / "param.json").exists() or \
            (child.name != "sce_sys" and (child / "param.json").exists())
        entries.append({"name": child.name, "path": str(child), "is_game": is_game,
                        "is_packed": (child / "ampr_assets.index").is_file()})
    parent = folder.parent if folder not in ROOTS else None
    try:
        usage = shutil.disk_usage(folder)
        disk = {"total": usage.total, "free": usage.free}
    except OSError:
        disk = None
    return {
        "path": str(folder),
        "parent": str(parent) if parent else "",
        "is_game": (folder / "param.json").exists() or (folder / "sce_sys" / "param.json").exists(),
        "is_packed": (folder / "ampr_assets.index").is_file(),
        "disk": disk,
        "entries": entries,
    }


@app.get("/api/games")
def games(path: str):
    folder = allowed_path(path)
    return {"games": [game_payload(game) for game in detect_games(folder)]}


@app.get("/api/game")
def game(path: str):
    return game_payload(allowed_path(path))


@app.get("/api/icon")
def icon(path: str):
    folder = allowed_path(path)
    icon_file = folder / "sce_sys" / "icon0.png"
    if not icon_file.is_file():
        raise HTTPException(404, "No icon")
    return FileResponse(icon_file, media_type="image/png",
                        headers={"Cache-Control": "max-age=3600"})


class LinkRequest(BaseModel):
    path: str
    toml: str | None = None


@app.post("/api/games/link")
def link_game(body: LinkRequest):
    folder = allowed_path(body.path)
    with state_lock:
        if body.toml:
            if not toml_path(body.toml).is_file():
                raise HTTPException(404, "TOML not found")
            state.link_toml(folder, body.toml, "manual")
        else:
            # Unlink: a manual "none" keeps auto-matching from re-linking it.
            state.upsert_game(folder, toml=None, toml_src="manual")
    return game_payload(folder)


@app.post("/api/games/auto-link")
def auto_link_game(body: LinkRequest):
    folder = allowed_path(body.path)
    with state_lock:
        state.upsert_game(folder, toml=None, toml_src=None)
    return game_payload(folder)


# ---------------------------------------------------------------- API: settings
@app.get("/api/settings")
def get_settings():
    return state.settings


@app.put("/api/settings")
def put_settings(body: dict):
    with state_lock:
        merged = _normalized_settings({**state.settings, **body})
        if merged.get("output_dir"):
            merged["output_dir"] = str(allowed_path(merged["output_dir"], must_exist=False))
        state.settings = merged
        state.save()
    return state.settings


# ---------------------------------------------------------------- API: TOML profiles
@app.get("/api/tomls")
def list_tomls():
    with state_lock:
        result = []
        for toml in state.tomls():
            stat = toml.stat()
            result.append({
                "name": toml.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "games": [g.get("title") or Path(g["path"]).name for g in state.games_using(toml.name)],
            })
    return {"tomls": result, "dir": str(TOML_DIR)}


@app.get("/api/tomls/{name}", response_class=PlainTextResponse)
def read_toml(name: str):
    path = toml_path(name)
    if not path.is_file():
        raise HTTPException(404, "TOML not found")
    return path.read_text("utf-8", errors="replace")


class TomlBody(BaseModel):
    content: str
    overwrite: bool = True


@app.put("/api/tomls/{name}")
def write_toml(name: str, body: TomlBody):
    path = toml_path(name)
    if path.exists() and not body.overwrite:
        raise HTTPException(409, f"{name} already exists")
    if len(body.content.encode("utf-8")) > net.MAX_DOWNLOAD_BYTES:
        raise HTTPException(413, "TOML is larger than 4 MiB")
    try:
        tomllib.loads(body.content)
    except tomllib.TOMLDecodeError as error:
        raise HTTPException(400, f"Invalid TOML: {error}") from error
    TOML_DIR.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(body.content, "utf-8")
    temporary.replace(path)
    return {"name": path.name}


@app.delete("/api/tomls/{name}")
def delete_toml(name: str):
    path = toml_path(name)
    if not path.is_file():
        raise HTTPException(404, "TOML not found")
    path.unlink()
    with state_lock:
        for entry in state.games_using(name):
            entry["toml"] = None
            entry["toml_src"] = None
        state.save()
    return {"deleted": name}


class RemoteListRequest(BaseModel):
    url: str


class RemoteDownloadRequest(BaseModel):
    name: str
    url: str


@app.post("/api/tomls/remote/list")
def remote_list(body: RemoteListRequest):
    try:
        found = net.list_tomls_at_url(body.url.strip())
    except Exception as error:
        raise HTTPException(400, str(error)) from error
    return {"tomls": [{"name": n, "url": u, "exists": (TOML_DIR / Path(n).name).exists()}
                      for n, u in found]}


@app.post("/api/tomls/remote/download")
def remote_download(body: RemoteDownloadRequest):
    toml_path(body.name)
    try:
        dest = net.download_toml(body.name, body.url, TOML_DIR)
    except Exception as error:
        raise HTTPException(400, str(error)) from error
    return {"name": dest.name}


# ---------------------------------------------------------------- API: jobs
class PackRequest(BaseModel):
    path: str
    output: str | None = None
    toml: str | None = None          # TOML name; None = use linked/auto profile
    use_linked_toml: bool = True
    traces: str | None = None
    lz4_level: int | None = None
    skip_verify: bool | None = None


class ExtractRequest(BaseModel):
    path: str
    output: str | None = None


class ProfileRequest(BaseModel):
    path: str                         # game folder (for naming + linking)
    traces: str | None = None


def _job_response(job: Job) -> dict:
    return job.to_dict()


@app.post("/api/jobs/pack")
def start_pack(body: PackRequest):
    game_dir = allowed_path(body.path)
    output = allowed_path(body.output, must_exist=False) if body.output else default_output_for(game_dir)
    output = allowed_path(str(output), must_exist=False)
    try:
        validate_separate_trees(game_dir, output)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if jobs.active_for("pack", str(game_dir)):
        raise HTTPException(409, "This game is already queued or running")

    info = parse_game_info(game_dir)
    if body.toml:
        config = toml_path(body.toml)
        if not config.is_file():
            raise HTTPException(404, "TOML not found")
    elif body.use_linked_toml:
        name, _ = auto_link(game_dir, info)
        config = TOML_DIR / name if name else None
    else:
        config = None
    traces = allowed_path(body.traces) if body.traces else None
    if traces is None and config is None and (game_dir / "traces").is_dir():
        traces = game_dir / "traces"

    settings = dict(state.settings)
    level = body.lz4_level if body.lz4_level is not None else int(settings.get("lz4_level", 9))
    level = max(1, min(12, int(level)))
    skip_verify = body.skip_verify if body.skip_verify is not None else \
        bool(settings.get("skip_lz4_verification", False))

    def run(job: Job) -> str:
        job.log(f"--- Processing {game_dir.name} ---")
        job.log(f"Title: {info['title']} | ID: {info['title_id']}")
        job.log(f"Output: {output}")
        job.log(f"Profile: {config.name if config else ('traces: ' + str(traces) if traces else 'auto (scan)')}")
        job.set_status("Reading game info…")
        job.set_progress(2)

        def stage(fraction, name):
            mapped = pack_stage_progress(fraction, name)
            if mapped:
                job.set_progress(mapped[0])
                job.set_status(mapped[1])

        job.set_progress(15)
        job.set_status("Packing LZ4 (AMPR) directly from source…")
        run_lz4_pack(
            source_dir=game_dir,
            output_dir=output,
            settings=settings,
            custom_config=config,
            traces_dir=traces,
            game_name=game_dir.name,
            lz4_level=level,
            skip_verify=skip_verify,
            workers=settings.get("workers"),
            source_read_only=not os.access(game_dir, os.W_OK),
            block_size_kib=int(settings.get("block_size_kib", 128)),
            progress_callback=job.log,
            progress_fraction=stage,
            eta_callback=job.set_eta,
            cancel_check=job.is_cancelled,
            process_callback=job.set_process,
        )
        return f"AMPR packing completed: {output}"

    job = Job(kind="pack", title=info["title"], run=run, params={
        "key": str(game_dir), "path": str(game_dir), "output": str(output),
        "toml": config.name if config else None, "traces": str(traces) if traces else None,
        "lz4_level": level, "skip_verify": skip_verify,
    })
    return _job_response(jobs.submit(job))


@app.post("/api/jobs/extract")
def start_extract(body: ExtractRequest):
    source = allowed_path(body.path)
    if not (source / "ampr_assets.index").is_file():
        raise HTTPException(400, "This folder has no ampr_assets.index (not an AMPR-packed game)")
    if body.output:
        output = allowed_path(body.output, must_exist=False)
    else:
        base = state.settings.get("output_dir", "").strip() or DEFAULT_OUTPUT
        output = Path(base) / f"{source.name}_EXTRACTED" if base else source.parent / f"{source.name}_EXTRACTED"
        output = allowed_path(str(output), must_exist=False)
    try:
        validate_separate_trees(source, output)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if jobs.active_for("extract", str(source)):
        raise HTTPException(409, "This folder is already queued or running")

    def run(job: Job) -> str:
        job.log(f"--- Extracting {source.name} -> {output} ---")
        run_extract(source, output, progress_callback=job.log, progress_percent=job.set_progress,
                    status_callback=job.set_status, cancel_check=job.is_cancelled,
                    process_callback=job.set_process)
        return f"Extraction completed: {output}"

    job = Job(kind="extract", title=source.name, run=run,
              params={"key": str(source), "path": str(source), "output": str(output)})
    return _job_response(jobs.submit(job))


@app.post("/api/jobs/profile")
def start_profile(body: ProfileRequest):
    game_dir = allowed_path(body.path)
    traces = allowed_path(body.traces) if body.traces else game_dir / "traces"
    if not traces.is_dir():
        raise HTTPException(404, f"Traces folder not found: {traces}")
    info = parse_game_info(game_dir)
    title_id = info["title_id"] if info["title_id"] != "Unknown" else ""
    name = f"{title_id or slug(info['title'])}.toml"

    def run(job: Job) -> str:
        job.set_status("Generating TOML from traces…")
        job.set_progress(10)
        generate_trace_profile(traces, TOML_DIR / name, info["title"], progress_callback=job.log)
        with state_lock:
            state.upsert_game(game_dir, traces=str(traces))
            state.link_toml(game_dir, name, "auto")
        return f"Generated {name} from traces and linked it to {info['title']}"

    job = Job(kind="profile", title=info["title"], run=run,
              params={"key": str(game_dir), "path": str(game_dir), "traces": str(traces), "toml": name})
    return _job_response(jobs.submit(job))


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": [_job_response(job) for job in jobs.list()]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, since: int = 0):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    lines, cursor = job.log_since(since)
    return {**_job_response(job), "log": [text for _, text in lines], "cursor": cursor}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not jobs.cancel(job_id):
        raise HTTPException(404, "Job not found or already finished")
    return {"cancelled": job_id}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    if not jobs.remove(job_id):
        raise HTTPException(409, "Job not found or still active")
    return {"deleted": job_id}


@app.delete("/api/jobs")
def clear_jobs():
    return {"deleted": jobs.clear_finished()}


@app.exception_handler(ValueError)
def value_error(_request: Request, error: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(error)})


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
