import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from utils.file_ops import validate_separate_trees
from utils.subprocess_utils import hidden_child_process_kwargs
from utils.tool_runner import command_for

# Try to import toml for config overrides
try:
    import toml
    HAS_TOML = True
except ImportError:
    HAS_TOML = False

TOOLS_DIR = Path(__file__).resolve().parent.parent / "external" / "ampr_emu" / "tools"
TOOL_CWD = TOOLS_DIR if TOOLS_DIR.is_dir() else Path(sys.executable).resolve().parent
if TOOLS_DIR.exists() and str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

PROGRESS_RE = re.compile(r"\[(\w+)\s+(\d+)%\]")
ELAPSED_RE = re.compile(r"\belapsed\s+(\d{2}:\d{2}:\d{2})\b", re.IGNORECASE)

# Safety exclusions that apply to ALL games
SAFETY_EXCLUSIONS = (
    "eboot.bin", "**/eboot.bin",
    "*.elf", "**/*.elf",
    "*.self", "**/*.self",
    "*.prx", "**/*.prx",
    "*.sprx", "**/*.sprx",
    "*.bak", "**/*.bak",
    "*.dat", "**/*.dat",
    "*.utoc", "**/*.utoc",
    "decrypted/**",
    "sce_module/**", "**/sce_module/**",
    "sce_sys/**", "**/sce_sys/**",
    "system/**", "**/system/**",
    "mods/**", "**/mods/**",
    "save/**", "**/save/**",
    "fakelib/**", "**/fakelib/**",
    "_DUPLEX_/**",
    "trophy2/**", "**/trophy2/**",
    "uds/**", "**/uds/**",
    "ampr_emu.index", "**/ampr_emu.index",
    "ampr_assets.index", "**/ampr_assets.index",
    "ampr_assets.index.crc", "**/ampr_assets.index.crc",
    "ampr_assets.index.runtime", "**/ampr_assets.index.runtime",
    "ampr_assets-*.pak", "**/*.pak",
    "*.json", "**/*.json",
    "*.ini", "**/*.ini",
    "*.cfg", "**/*.cfg",
    "*.xml", "**/*.xml",
    "*.txt", "**/*.txt",
    "*.bk2", "**/*.bk2",
    "*.mp4", "**/*.mp4",
    "*.ivf", "**/*.ivf",
    "*.usm", "**/*.usm",
    "*.bnk", "**/*.bnk",
    "*.wem", "**/*.wem",
    "*.at9", "**/*.at9",
    "*.pfs", "**/*.pfs",
    "*.img", "**/*.img",
    # Compressed image formats (already compressed, LZ4 adds nothing)
    "*.png", "**/*.png",
    "*.jpg", "**/*.jpg",
    "*.jpeg", "**/*.jpeg",
    "*.webp", "**/*.webp",
    "*.gif", "**/*.gif",
    "*.bmp", "**/*.bmp",
    "*.ico", "**/*.ico",
    "*.tga", "**/*.tga",
    "*.tif", "**/*.tif",
    "*.tiff", "**/*.tiff",
    "*.exr", "**/*.exr",
    "*.hdr", "**/*.hdr",
    "*.psd", "**/*.psd",
    # GPU texture formats (already block-compressed)
    "*.dds", "**/*.dds",
    "*.ktx", "**/*.ktx",
    "*.ktx2", "**/*.ktx2",
    "*.astc", "**/*.astc",
    "*.basis", "**/*.basis",
    "*.gnf", "**/*.gnf",
    "*.gnfp", "**/*.gnfp",
    "*.jxm", "**/*.jxm",
    "*.vtf", "**/*.vtf",
    # Archive/container formats
    "*.zip", "**/*.zip",
    "*.7z", "**/*.7z",
    "*.rar", "**/*.rar",
    "*.gz", "**/*.gz",
    "*.xz", "**/*.xz",
    "*.bz2", "**/*.bz2",
    "*.zst", "**/*.zst",
    "*.lz4", "**/*.lz4",
    # Audio formats (already compressed)
    "*.mp3", "**/*.mp3",
    "*.ogg", "**/*.ogg",
    "*.flac", "**/*.flac",
    "*.aac", "**/*.aac",
    "*.opus", "**/*.opus",
    "*.m4a", "**/*.m4a",
    # Video formats (already compressed)
    "*.avi", "**/*.avi",
    "*.mkv", "**/*.mkv",
    "*.mov", "**/*.mov",
    "*.wmv", "**/*.wmv",
    "*.flv", "**/*.flv",
    "*.webm", "**/*.webm",
    "*.m4v", "**/*.m4v",
)


def _pattern_to_regex(pattern: str) -> "re.Pattern":
    """Translate a glob pattern into a compiled regex."""
    out = ["^"]
    i = 0
    while i < len(pattern):
        if pattern[i:i + 2] == "**":
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append(".")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


_SAFETY_REGEXES = tuple(_pattern_to_regex(p) for p in SAFETY_EXCLUSIONS)


def is_loose_path(rel_path) -> bool:
    """True if a path matches one of the safety exclusion patterns."""
    rel_posix = Path(rel_path).as_posix()
    return any(rx.match(rel_posix) for rx in _SAFETY_REGEXES)


# ============================================================================
# LEARNING SYSTEM: Extract loose patterns from imported TOMLs and apply them
# ============================================================================

def extract_loose_patterns_from_toml(toml_path: Path) -> set:
    """Extract all loose patterns from a single TOML file."""
    patterns = set()
    
    if not HAS_TOML:
        return patterns
    
    try:
        data = toml.load(str(toml_path))
        
        rules = data.get("rule", [])
        if isinstance(rules, dict):
            rules = [rules]
        
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if rule.get("action") == "loose":
                includes = rule.get("include", [])
                if isinstance(includes, str):
                    includes = [includes]
                for pattern in includes:
                    if isinstance(pattern, str) and pattern.strip():
                        patterns.add(pattern.strip())
    except (OSError, TypeError, toml.TomlDecodeError):
        return set()
    
    return patterns


def collect_learned_loose_patterns(toml_dir: Path) -> dict:
    """Collect all loose patterns from all TOML files in the config directory."""
    learned_patterns = defaultdict(list)
    
    if not toml_dir or not toml_dir.exists():
        return learned_patterns
    
    toml_files = list(toml_dir.glob("*.toml"))
    if not toml_files:
        return learned_patterns
    
    for toml_file in toml_files:
        patterns = extract_loose_patterns_from_toml(toml_file)
        for pattern in patterns:
            learned_patterns[pattern].append(toml_file.stem)
    
    return learned_patterns


def filter_patterns_for_game(learned_patterns: dict, game_dir: Path, 
                             progress_callback=None) -> list:
    """Filter learned loose patterns to only include ones that match
    actual files/folders in the current game."""
    if not learned_patterns:
        return []
    
    game_dir = Path(game_dir)
    matching_patterns = []
    
    compiled = {}
    for pattern in learned_patterns:
        compiled[pattern] = _pattern_to_regex(pattern)
    
    game_files = set()
    for dirpath, dirnames, filenames in os.walk(game_dir):
        rel_dir = Path(dirpath).relative_to(game_dir)
        for fn in filenames:
            rel_path = (rel_dir / fn).as_posix() if str(rel_dir) != '.' else fn
            game_files.add(rel_path)
        for dn in dirnames:
            rel_path = (rel_dir / dn).as_posix() if str(rel_dir) != '.' else dn
            game_files.add(rel_path)
    
    for pattern, regex in compiled.items():
        matched = False
        for game_file in game_files:
            if regex.match(game_file):
                matched = True
                break
        
        if matched:
            matching_patterns.append(pattern)
    
    if progress_callback and matching_patterns:
        sources = set()
        for p in matching_patterns:
            sources.update(learned_patterns[p])
        progress_callback(f"[LEARN] Found {len(matching_patterns)} loose pattern(s) "
                         f"from {len(sources)} imported TOML config(s)")
    
    return matching_patterns


# ============================================================================
# GAME STRUCTURE SCANNING
# ============================================================================

def scan_game_structure(game_dir: Path) -> dict:
    """Scan the game directory and analyze its structure for TOML generation."""
    stats = {
        'folders': defaultdict(int),
        'extensions': defaultdict(int),
        'large_files': [],
        'streaming_containers': [],
        'has_data_folder': False,
        'has_audio_folders': False,
        'has_video_folders': False,
        'root_numbered_files': [],  # NEW: track root-level numbered files
    }
    
    STREAMING_FOLDER_HINTS = {'video', 'movie', 'movies', 'cutscene', 'cutscenes', 'fmv', 'cinematic', 'cinematics'}
    AUDIO_FOLDER_HINTS = {'sound', 'audio', 'sfx', 'music', 'voice', 'vo', 'dialog', 'dialogue', 'soundbank', 'wem'}
    ASSET_FOLDER_HINTS = {'d', 'data', 'assets', 'content', 'game', 'resources', 'streaming'}
    
    for dirpath, dirnames, filenames in os.walk(game_dir):
        rel_dir = Path(dirpath).relative_to(game_dir)
        rel_dir_str = rel_dir.as_posix() if str(rel_dir) != '.' else '.'
        
        if rel_dir_str != '.':
            top_folder = rel_dir_str.split('/')[0]
            stats['folders'][top_folder] += len(filenames)
            
            if any(hint in top_folder.lower() for hint in STREAMING_FOLDER_HINTS):
                stats['has_video_folders'] = True
                stats['streaming_containers'].append(f"**/{top_folder}/**")
            
            if any(hint in top_folder.lower() for hint in AUDIO_FOLDER_HINTS):
                stats['has_audio_folders'] = True
            
            if any(hint in top_folder.lower() for hint in ASSET_FOLDER_HINTS):
                stats['has_data_folder'] = True
        else:
            # NEW: Detect root-level files with incremental numbers
            for fn in filenames:
                # Match: data.0, data.1, chunk0.bin, part00.dat, file.001, etc.
                if re.match(r'^[a-zA-Z_]+\.\d+$', fn) or re.match(r'^[a-zA-Z_]+\d+\.[a-zA-Z]+$', fn) or re.match(r'^[a-zA-Z_]+\.\d{2,}$', fn):          # data.0, data.1
                    stats['root_numbered_files'].append(fn)
        
        for filename in filenames:
            filepath = Path(dirpath) / filename
            ext = filepath.suffix.lower()
            if ext:
                stats['extensions'][ext] += 1
            
            try:
                size = filepath.stat().st_size
                if size > 64 * 1024 * 1024:
                    rel_path = filepath.relative_to(game_dir).as_posix()
                    stats['large_files'].append((rel_path, size))
            except OSError:
                pass
    
    return stats


# ============================================================================
# PROFILE GENERATION
# ============================================================================

def generate_universal_pack_profile_from_scan(game_dir: Path, config_path: Path, 
                                                level: int = 9, block_size_kib: int = 64,
                                                workers: int | None = None,
                                                auto_loose_large: bool = True,
                                                decoded_cache_mib: int = 256,
                                                physical_cache_mib: int = 64,
                                                toml_dir: Path | None = None,
                                                progress_callback: Callable[[str], None] | None = None) -> None:
    """Generate a universal TOML by scanning the actual game folder structure."""
    level = max(1, min(12, int(level)))
    block_size_kib = _clamp_block_size_kib(block_size_kib)
    mode = "fast" if level <= 4 else "hc"
    workers = workers or os.cpu_count() or 4
    rt_workers = min(workers, 8)
    latency_reserve_workers = 1 if rt_workers > 1 else 0
    decoded_cache_mib = max(0, int(decoded_cache_mib))
    physical_cache_mib = max(0, int(physical_cache_mib))
    
    stats = scan_game_structure(game_dir)
    
    # Learning: collect loose patterns from imported TOMLs
    learned_loose_patterns = []
    if toml_dir:
        learned = collect_learned_loose_patterns(toml_dir)
        if learned:
            learned_loose_patterns = filter_patterns_for_game(learned, game_dir, progress_callback)
    
    toml_lines = [
        "# Universal profile generated by scanning game structure",
        "# Learning system applied: learned loose patterns from imported TOML configs",
        "",
        "[pack]",
        'index_name = "ampr_assets.index"',
        'pack_pattern = "ampr_assets-{group}-lane{lane:02d}-vol{volume:02d}-{id:03d}.pak"',
        'default_action = "loose"',
        f'default_block_size = "{block_size_kib}KiB"',
        'io_page_size = "64KiB"',
        'payload_alignment = "64KiB"',
        'chunk_alignment = "64B"',
        f'workers = {workers}',
        f'compression_mode = "{mode}"',
        f'compression_level = {level}',
        'acceleration = 1',
        'deduplicate = true',
        'deduplicate_scope = "lane"',
        'deduplicate_streaming = false',
        'min_savings_bytes = 64',
        'min_savings_ratio = 0.01',
        'io_neutral_min_savings_bytes = "8KiB"',
        'io_neutral_min_savings_ratio = 0.125',
        f'auto_loose_large_files = {"true" if auto_loose_large else "false"}',
        'auto_loose_hot_files = false',
        'auto_loose_min_file_size = "64MiB"',
        'auto_loose_sample_blocks = 32',
        'auto_loose_sample_bytes = "16MiB"',
        'auto_loose_min_savings_ratio = 0.05',
        'auto_loose_max_raw_ratio = 0.90',
        'preserve_mtime = true',
        'validate_index_metadata = true',
        '',
        "[runtime]",
        f'decoded_cache_bytes = "{decoded_cache_mib}MiB"',
        f'physical_cache_bytes = "{physical_cache_mib}MiB"',
        f'workers = {rt_workers}',
        f'latency_reserve_workers = {latency_reserve_workers}',
        '',
        "[groups.assets]",
        'pack_count = 4',
        'assignment = "balanced"',
        'max_pack_size = "16GiB"',
        'stripe_large_files = false',
        '',
    ]
    
    if stats['has_data_folder'] or stats['folders']:
        toml_lines.extend([
            "# Baseline: compress files in subdirectories",
            "[[rule]]",
            'action = "compress"',
            'include = ["*/**"]',
            f'block_size = "{block_size_kib}KiB"',
            'group = "assets"',
            'layout = "mixed"',
            '',
        ])
    
    # NEW: Compress root-level files with incremental numbers
    # Matches: data.0, data.1, chunk0.bin, part00.dat, file.001, etc.
    if stats['root_numbered_files']:
        data_globs = ", ".join(f'"{fn}"' for fn in sorted(stats['root_numbered_files']))
        toml_lines.extend([
            "# Root-level numbered data files (auto-detected)",
            "[[rule]]",
            'action = "compress"',
            f'include = [{data_globs}]',
            f'block_size = "{block_size_kib}KiB"',
            'group = "assets"',
            'layout = "mixed"',
            '',
        ])
    
    texture_exts = {'.dds', '.ktx', '.ktx2', '.astc', '.basis', '.tga', '.gnf', '.gnfp', 
                    '.jxm', '.vtf', '.dat', '.res', '.uasset', '.ubulk', '.bin'}
    found_texture_exts = [ext for ext in stats['extensions'] if ext in texture_exts]
    
    if found_texture_exts:
        texture_globs = ", ".join(f'"**/*{ext}"' for ext in sorted(found_texture_exts))
        toml_lines.extend([
            "# Texture/large-streamed-asset formats",
            "[[rule]]",
            'action = "compress"',
            f'include = [{texture_globs}]',
            f'block_size = "{max(block_size_kib, 64)}KiB"',
            'group = "assets"',
            'layout = "mixed"',
            '',
        ])
    
    if stats['has_audio_folders']:
        audio_globs = ', '.join(f'"**/{folder}/**"' for folder in 
                                 ['sound', 'audio', 'sfx', 'music', 'voice', 'vo', 'dialog', 'dialogue'])
        toml_lines.extend([
            "# Streamed audio: small blocks, relaxed savings thresholds",
            "[[rule]]",
            'action = "compress"',
            f'include = [{audio_globs}]',
            'block_size = "16KiB"',
            'group = "assets"',
            'layout = "random"',
            'hot = true',
            'min_savings_bytes = 16',
            'min_savings_ratio = 0.0025',
            'io_neutral_min_savings_bytes = "2KiB"',
            'io_neutral_min_savings_ratio = 0.125',
            '',
        ])
    
    if stats['has_video_folders'] or stats['streaming_containers']:
        video_globs = ', '.join(f'"**/{folder}/**"' for folder in 
                               ['video', 'movie', 'movies', 'cutscene', 'cutscenes', 'fmv', 'cinematic', 'cinematics'])
        toml_lines.extend([
            "# Video/cutscene folders: already codec-compressed",
            "[[rule]]",
            'action = "loose"',
            f'include = [{video_globs}]',
            '',
        ])
    
    streaming_containers = [
        '"**/movie"', '"**/movie_*"', '"**/movies"', '"**/movies_*"',
        '"**/soundbank"', '"**/soundbank_*"',
        '"**/screenreaderwem"', '"**/screenreaderwem.*"',
        '"**/wem"', '"**/wem_*"', '"**/wem.*"',
    ]
    toml_lines.extend([
        "# Streaming containers: boot-critical, keep loose",
        "[[rule]]",
        'action = "loose"',
        f'include = [{", ".join(streaming_containers)}]',
        '',
    ])
    
    if any('soundbank' in ext for ext in stats['extensions']):
        toml_lines.extend([
            "# Language sound banks: small random reads",
            "[[rule]]",
            'action = "compress"',
            'include = ["**/soundbank.*"]',
            'block_size = "16KiB"',
            'group = "assets"',
            'layout = "random"',
            'hot = true',
            'min_savings_bytes = 16',
            'min_savings_ratio = 0.0025',
            'io_neutral_min_savings_bytes = "2KiB"',
            'io_neutral_min_savings_ratio = 0.125',
            '',
        ])
    
    # Add LEARNED loose patterns from imported TOMLs
    if learned_loose_patterns:
        new_learned = [p for p in learned_loose_patterns if p not in SAFETY_EXCLUSIONS]
        if new_learned:
            learned_list = "\n".join(f'  "{p}",' for p in new_learned)
            toml_lines.extend([
                f"# Learned loose patterns from imported TOML configs ({len(new_learned)} patterns)",
                "[[rule]]",
                'action = "loose"',
                'include = [',
                learned_list,
                ']',
                '',
            ])
    
    safety_list = "\n".join(f'  "{p}",' for p in SAFETY_EXCLUSIONS)
    toml_lines.extend([
        "# Safety exclusions. The last matching rule wins.",
        "[[rule]]",
        'action = "loose"',
        'include = [',
        safety_list,
        ']',
    ])
    
    config_path.write_text("\n".join(toml_lines) + "\n", encoding="utf-8")


def _clamp_block_size_kib(kib: int) -> int:
    """Clamp to the documented valid range (16 KiB..1 MiB) and round to the
    nearest supported power of two."""
    kib = max(16, min(1024, int(kib)))
    lo = 1 << (kib.bit_length() - 1)
    hi = lo * 2
    return hi if (kib - lo) > (hi - kib) else lo


def generate_trace_profile(traces_dir: Path, output_toml: Path, game_name: str,
                            progress_callback=None) -> None:
    """Generate TOML profile from traces following the official ampr_pack_profile.py tutorial."""
    profile_script = TOOLS_DIR / "ampr_pack_profile.py"
    if not profile_script.exists() and not getattr(sys, "frozen", False):
        raise FileNotFoundError(f"ampr_pack_profile.py not found at {profile_script}")
    
    traces_dir = Path(traces_dir)
    output_toml = Path(output_toml)
    
    trace_pairs = []
    
    if (traces_dir / "ampr_commands.bin").is_file() and (traces_dir / "ampr_emu.index").is_file():
        trace_pairs.append((traces_dir / "ampr_commands.bin", traces_dir / "ampr_emu.index"))
    else:
        for commands in sorted(traces_dir.rglob("ampr_commands.bin")):
            index = commands.with_name("ampr_emu.index")
            if index.is_file():
                trace_pairs.append((commands, index))
    
    if not trace_pairs:
        raise FileNotFoundError(f"No trace pairs (ampr_commands.bin + ampr_emu.index) found in {traces_dir}")
    
    if progress_callback:
        progress_callback(f"[INFO] Found {len(trace_pairs)} trace pair(s)")
    
    output_dir = output_toml.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    report_path = output_dir / f"{output_toml.stem}.md"
    metrics_path = output_dir / f"{output_toml.stem}.json"
    
    cmd = [*command_for(profile_script), "generate"]
    
    for commands, index in trace_pairs:
        cmd.extend(["--trace", str(commands), str(index)])
    
    cmd.extend([
        "--name", game_name,
        "--output", str(output_toml),
        "--report", str(report_path),
        "--metrics", str(metrics_path),
        "--overwrite",
        "--pattern-mode", "exact",
        "--cache-sim",
    ])
    
    if progress_callback:
        progress_callback(f"[INFO] Running ampr_pack_profile.py with {len(trace_pairs)} trace(s)...")
    
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(TOOL_CWD),
        check=False,
        **hidden_child_process_kwargs(),
    )
    
    if p.returncode != 0:
        error_msg = f"Profile generation failed:\n{p.stdout}\n{p.stderr}"
        if progress_callback:
            progress_callback(f"[ERROR] {error_msg}")
        raise RuntimeError(error_msg)
    
    if progress_callback:
        progress_callback(f"[OK] Generated profile: {output_toml.name}")
        if report_path.exists():
            progress_callback(f"[OK] Generated report: {report_path.name}")
        if metrics_path.exists():
            progress_callback(f"[OK] Generated metrics: {metrics_path.name}")


def run_lz4_pack(source_dir, output_dir, settings, custom_config=None,
                 traces_dir=None, game_name: str = "game",
                 lz4_level: int | None = None,
                 skip_verify: bool = False,
                 block_size_kib: int = 64,
                 reuse_source_index: bool = False,
                 source_read_only: bool = False,
                 workers: int | None = None,
                 progress_callback: Callable[[str], None] | None = None,
                 progress_fraction: Callable[[float, str], None] | None = None,
                 eta_callback: Callable[[str], None] | None = None,
                 cancel_check: Callable[[], bool] | None = None,
                 process_callback: Callable[[subprocess.Popen | None], None] | None = None) -> bool:
    
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Game folder not found: {source_dir}")
    validate_separate_trees(source_dir, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Preserve the complete directory tree, including meaningful empty folders.
    for dirpath, dirnames, _ in os.walk(source_dir):
        dirnames.sort()
        rel_dir = Path(dirpath).relative_to(source_dir)
        (output_dir / rel_dir).mkdir(parents=True, exist_ok=True)
    
    custom_config = Path(custom_config) if custom_config else None
    traces_dir = Path(traces_dir) if traces_dir else None
        
    level = lz4_level if lz4_level is not None else int(settings.get("lz4_level", 9))
    effective_workers = workers or max(1, (os.cpu_count() or 2) - 1)

    def check_cancelled():
        if cancel_check and cancel_check():
            raise RuntimeError("Cancelled by user.")

    check_cancelled()

    from core.ampr_runtime import install_ampr_runtime
    runtime_overrides = install_ampr_runtime(source_dir, output_dir)

    # 1. Get AMPR index describing the SOURCE tree, store in output.
    ampr_index = output_dir / "ampr_emu.index"
    from core.ampr_index import _build_index_local, ensure_ampr_index

    source_index = source_dir / "ampr_emu.index"
    fakelib_marker = source_dir / "fakelib" / "libSceAmpr.sprx"
    regenerated_source_index = (
        None if runtime_overrides or (source_read_only and fakelib_marker.is_file())
        else ensure_ampr_index(source_dir)
    )
    if runtime_overrides:
        _build_index_local(source_dir, ampr_index, metadata_overrides=runtime_overrides)
        if progress_callback:
            progress_callback('[INFO] Installed pinned AMPR fakelib in output; rebuilt index with its metadata. Source unchanged.')
    elif regenerated_source_index is not None:
        if progress_callback:
            progress_callback(
                "[INFO] Detected fakelib/libSceAmpr.sprx; regenerated source ampr_emu.index."
            )
        shutil.copy2(regenerated_source_index, ampr_index)
    elif source_read_only and fakelib_marker.is_file():
        if progress_callback:
            progress_callback(
                "[INFO] Detected fakelib/libSceAmpr.sprx on read-only mounted source; "
                "rebuilt output ampr_emu.index."
            )
        _build_index_local(source_dir, ampr_index)
    elif not ampr_index.exists():
        reused = False
        if reuse_source_index and source_index.is_file() and source_index.stat().st_size > 0:
            if progress_callback:
                progress_callback("[WARN] Reusing existing AMPR index from source folder...")
            try:
                try:
                    os.link(source_index, ampr_index)
                except OSError:
                    shutil.copy2(source_index, ampr_index)
                reused = True
            except OSError as e:
                if progress_callback:
                    progress_callback(f"[WARN] Couldn't reuse source index ({e}); rebuilding instead...")
        if not reused:
            if progress_callback:
                progress_callback("[INFO] Building AMPR index from source tree...")
            _build_index_local(source_dir, ampr_index)
    if not ampr_index.exists():
        raise FileNotFoundError("Failed to generate AMPR index.")

    # 2. Resolve profile: custom > traces > blind (scanned + learned)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", game_name)[:50]
    
    if custom_config and custom_config.exists():
        base_config_path = custom_config
        if progress_callback:
            progress_callback(f"[INFO] Loading custom config: {custom_config.name}")
        
        config_path = base_config_path
        if HAS_TOML:
            try:
                toml_data = toml.load(str(base_config_path))
                if "pack" not in toml_data:
                    toml_data["pack"] = {}
                
                toml_data["pack"]["compression_level"] = level
                toml_data["pack"]["workers"] = effective_workers
                
                config_path = output_dir / f"{safe_name}_custom_override.toml"
                with open(config_path, "w", encoding="utf-8") as f:
                    toml.dump(toml_data, f)
                    
                if progress_callback:
                    progress_callback("[OK] Applied UI overrides (Level/Workers) to custom config.")
            except Exception as e:  # noqa: BLE001 - preserve valid custom config on override failure
                if progress_callback:
                    progress_callback(f"[WARN] Failed to parse/override TOML: {e}. Using original.")
                config_path = base_config_path
        else:
            if progress_callback:
                progress_callback("[WARN] `toml` module not found. Using original custom config without overrides.")
                
    elif traces_dir and traces_dir.exists():
        config_path = output_dir / f"{safe_name}_trace_profile.toml"
        if progress_callback:
            progress_callback("[INFO] Generating trace-derived profile...")
        generate_trace_profile(traces_dir, config_path, game_name, progress_callback)
    else:
        config_path = output_dir / f"{safe_name}_auto_profile.toml"
        if progress_callback:
            progress_callback(f"[INFO] Scanning game structure and generating universal profile "
                              f"(LZ4 level {level}, {'fast' if level <= 4 else 'hc'}, {effective_workers} workers)...")
        
        from utils.state import TOML_DIR
        generate_universal_pack_profile_from_scan(source_dir, config_path, level, block_size_kib,
                                                   workers=effective_workers,
                                                   auto_loose_large=bool(settings.get("auto_loose_large", True)),
                                                   decoded_cache_mib=settings.get("decoded_cache_mib", 256),
                                                   physical_cache_mib=settings.get("physical_cache_mib", 64),
                                                   toml_dir=TOML_DIR,
                                                   progress_callback=progress_callback)

    from core.build_diagnostics import BuildDiagnostics
    diagnostics = BuildDiagnostics(source_dir, output_dir, command_for(TOOLS_DIR / 'ampr_pack.py'),
                                   str(TOOL_CWD), check_cancelled, progress_callback)
    if progress_fraction:
        progress_fraction(0.0, 'hash-source')
    diagnostics.capture_inputs(ampr_index, config_path, effective_workers, level, skip_verify)
    if runtime_overrides:
        diagnostics.record_replacements(runtime_overrides)

    # 3. Pack: read from SOURCE, write .pak into OUTPUT
    if progress_callback:
        progress_callback(f"[INFO] Packing from source -> output ({effective_workers} threads)...")

    pack_stdout = []

    def run_subprocess(cmd, stage):
        check_cancelled()
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              cwd=str(TOOL_CWD),
                              **hidden_child_process_kwargs()) as proc:
            if process_callback:
                process_callback(proc)
            try:
                if proc.stdout is None:
                    raise RuntimeError(f"{stage} did not expose an output stream")
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    pack_stdout.append(line)
                    if progress_callback:
                        progress_callback(line)
                    m = PROGRESS_RE.search(line)
                    if m and progress_fraction:
                        progress_fraction(int(m.group(2)) / 100.0, m.group(1))
                    elapsed = ELAPSED_RE.search(line)
                    if elapsed and eta_callback:
                        eta_callback(f"Elapsed {elapsed.group(1)}")
                proc.wait()
                if cancel_check and cancel_check():
                    raise RuntimeError("Cancelled by user.")
                if proc.returncode != 0:
                    raise RuntimeError(f"{stage} failed with return code {proc.returncode}")
            finally:
                if process_callback:
                    process_callback(None)

    def run_pack_subprocess(cmd):
        output_lines = []
        check_cancelled()
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              cwd=str(TOOL_CWD),
                              **hidden_child_process_kwargs()) as proc:
            if process_callback:
                process_callback(proc)
            try:
                if proc.stdout is None:
                    raise RuntimeError("Pack process did not expose an output stream")
                for line in proc.stdout:
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue
                    output_lines.append(line_stripped)
                    pack_stdout.append(line_stripped)
                    if progress_callback:
                        progress_callback(line_stripped)
                    m = PROGRESS_RE.search(line_stripped)
                    if m and progress_fraction:
                        progress_fraction(int(m.group(2)) / 100.0, m.group(1))
                    elapsed = ELAPSED_RE.search(line_stripped)
                    if elapsed and eta_callback:
                        eta_callback(f"Elapsed {elapsed.group(1)}")
                proc.wait()
                if cancel_check and cancel_check():
                    raise RuntimeError("Cancelled by user.")
                if proc.returncode != 0:
                    raise RuntimeError(f"Pack failed with return code {proc.returncode}")
            finally:
                if process_callback:
                    process_callback(None)
        
        full_output = "\n".join(output_lines)
        try:
            return json.loads(full_output.strip())
        except (json.JSONDecodeError, ValueError):
            start = full_output.rfind('{')
            end = full_output.rfind('}')
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(full_output[start:end+1])
                except (json.JSONDecodeError, ValueError):
                    pass
            
            if progress_callback:
                progress_callback("[WARN] Couldn't parse pack JSON output; "
                                  "falling back to SAFETY_EXCLUSIONS-based copy.")
            return None

    pack_command = [
        *command_for(TOOLS_DIR / "ampr_pack.py"),
        "pack",
        "--root", str(source_dir),
        "--ampr-index", str(ampr_index),
        "--output", str(output_dir),
        "--config", str(config_path),
    ]
    for pattern in SAFETY_EXCLUSIONS:
        pack_command.extend(("--exclude", pattern))
    pack_result = run_pack_subprocess(pack_command)

    # 4. Verify
    check_cancelled()
    assets_index = output_dir / "ampr_assets.index"
    if not skip_verify and assets_index.exists():
        if eta_callback:
            eta_callback("")
        if progress_callback:
            progress_callback("[INFO] Verifying packed integrity...")
        run_subprocess([*command_for(TOOLS_DIR / "ampr_pack.py"), "verify",
                        "--index", str(assets_index),
                        "--root", str(source_dir)], "Verify")

    # 5. Copy loose (unpacked) files from source -> output.
    if eta_callback:
        eta_callback("")
    if progress_fraction:
        progress_fraction(0.0, "loose")
    if progress_callback:
        mode = "hardlinks enabled" if settings.get("use_hardlinks", False) else "independent copies"
        progress_callback(f"[INFO] Placing loose files into output ({mode})...")

    loose_paths = None
    if pack_result and isinstance(pack_result.get("loose_paths"), list):
        loose_paths = {Path(p).as_posix() for p in pack_result["loose_paths"]}
        if progress_callback:
            progress_callback(f"[INFO] Using pack's own loose_paths list "
                              f"({len(loose_paths)} files) as source of truth.")
    elif progress_callback:
        progress_callback("[WARN] No loose_paths available from pack output - "
                          "falling back to SAFETY_EXCLUSIONS matching only.")

    def _should_copy(rel: Path) -> bool:
        if loose_paths is not None:
            return rel.as_posix() in loose_paths
        return is_loose_path(rel)

    copied, linked, skipped = 0, 0, 0
    total_bytes = 0
    for dirpath, dirnames, filenames in os.walk(source_dir):
        check_cancelled()
        dirnames.sort()
        for fn in filenames:
            src = Path(dirpath) / fn
            rel = src.relative_to(source_dir)

            if not _should_copy(rel):
                continue

            dst = output_dir / rel

            if dst.exists():
                skipped += 1
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            sz = src.stat().st_size
            if settings.get("use_hardlinks", False):
                try:
                    os.link(src, dst)
                    linked += 1
                except OSError:
                    shutil.copy2(src, dst)
                    copied += 1
            else:
                shutil.copy2(src, dst)
                copied += 1
            total_bytes += sz

    pak_bytes = sum(p.stat().st_size for p in output_dir.glob("ampr_assets-*.pak"))
    if progress_callback:
        progress_callback(
            f"[OK] Loose files placed: {linked} hardlinked, {copied} copied, "
            f"{skipped} already existed ({total_bytes / (1024*1024):.1f} MiB total)")
        progress_callback(f"[INFO] Packs: {pak_bytes / (1024**3):.2f} GiB | "
                          f"Loose kept: {total_bytes / (1024**3):.2f} GiB")
        if pak_bytes == 0:
            progress_callback(
                "[WARN] No packs produced: every asset was loose. Either the game's containers are "
                "already compressed (LZ4 can't shrink them - loose is the optimal result), or "
                "auto-loose was too aggressive.")

    if progress_fraction:
        progress_fraction(1.0, "loose")

    for w in [l for l in pack_stdout if "auto-loose" in l.lower() or "[WARN]" in l]:
        if progress_callback:
            progress_callback(f"[INFO] {w}")

    if progress_fraction:
        progress_fraction(0.0, 'hash-output')
    diagnostics.finish()
    return True
