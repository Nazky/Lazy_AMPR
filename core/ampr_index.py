import os
import struct
from pathlib import Path

RECORD_STRUCT = struct.Struct("<IIQq")
HASH_SLOT_STRUCT = struct.Struct("<QII")
HEADER_STRUCT = struct.Struct("<8sIIQQQII")

# IMPORTANT — do not "upgrade" these two constants.
# ampr_emu.index is a PATH INDEX: its magic is AMPRIDX3 / version 3, and that is
# the only thing ampr_pack.py's "reading-index" stage accepts.
# AMPRPAK3 / AMPRPAK4 are the magic of the PACK MANIFEST (ampr_assets.index),
# a completely different binary layout produced by ampr_pack.py itself.
# Writing AMPRPAK4 here makes ampr_pack fail with "unsupported AMPR index".
INDEX_MAGIC = b"AMPRIDX3"
INDEX_VERSION = 3

def key_for(path: str) -> bytes:
    """Match the runtime: UTF-8 encode, then fold ASCII A-Z only."""
    raw = path.replace("\\", "/").encode("utf-8")
    return bytes((byte + 0x20) if 0x41 <= byte <= 0x5A else byte for byte in raw)

def fnv1a64_path_hash(path: str) -> int:
    h = 1469598103934665603
    for byte in key_for(path):
        h ^= byte
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h or 1

def hash_slot_count(entry_count: int) -> int:
    if entry_count <= 0: return 0
    slots = 2
    target = entry_count * 2
    while slots < target: slots <<= 1
    return slots

def build_hash_slots(rows: list[tuple[int, int, str]]) -> list[tuple[int, int, int]]:
    duplicate_flag = 1
    slots = [(0, 0, 0) for _ in range(hash_slot_count(len(rows)))]
    mask = len(slots) - 1
    for index, (_, _, path) in enumerate(rows):
        h = fnv1a64_path_hash(path)
        pos = h & mask
        duplicate = False
        while slots[pos][1] != 0:
            if slots[pos][0] == h:
                old_hash, old_index_plus_one, old_flags = slots[pos]
                slots[pos] = (old_hash, old_index_plus_one, old_flags | duplicate_flag)
                duplicate = True
            pos = (pos + 1) & mask
        slots[pos] = (h, index + 1, duplicate_flag if duplicate else 0)
    return slots

def ensure_ampr_index(source_root: Path) -> Path | None:
    """Regenerate the source path index when the AMPR fakelib is present."""
    index_path = source_root / "ampr_emu.index"
    fakelib_sprx = source_root / "fakelib" / "libSceAmpr.sprx"
    if not fakelib_sprx.is_file():
        return None
    _build_index_local(source_root, index_path)
    return index_path

def _build_index_local(root: Path, output_path: Path, metadata_overrides=None) -> None:
    overrides = {name.casefold(): replacement for name, replacement in (metadata_overrides or {}).items()}
    root = root.resolve()
    output_path = output_path.resolve()
    output_tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    seen: dict[bytes, str] = {}
    rows: list[tuple[int, int, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort(key=str.lower)
        filenames.sort(key=str.lower)
        for filename in filenames:
            path = Path(dirpath) / filename
            try: resolved = path.resolve()
            except OSError: continue
            if resolved == output_path or resolved == output_tmp: continue
            rel = path.relative_to(root).as_posix()
            indexed_path = "/app0/" + rel
            if indexed_path.lower() in {
                "/app0/ampr_emu.index",
                "/app0/ampr_emu.index.tmp",
                "/app0/ampr_commands.bin",
                "/app0/apr_emu.log",
            }:
                continue
            try: st = overrides.get(rel.casefold(), path).stat()
            except OSError: continue
            if not path.is_file(): continue
            key = key_for(indexed_path)
            if key in seen:
                raise ValueError(
                    f"case-insensitive path collision: {seen[key]} <-> {indexed_path}"
                )
            seen[key] = indexed_path
            rows.append((st.st_size, int(st.st_mtime), indexed_path))
    if not rows: return
    rows = sorted(rows, key=lambda row: key_for(row[2]))
    path_blob = bytearray()
    records = bytearray()
    for size, mtime, path in rows:
        encoded = path.encode("utf-8") + b"\0"
        offset = len(path_blob)
        path_len = len(encoded) - 1
        if offset > 0xFFFFFFFF or path_len > 0xFFFFFFFF:
            raise ValueError("index path blob is too large")
        records += RECORD_STRUCT.pack(offset, path_len, size, mtime)
        path_blob += encoded
    hash_slots = build_hash_slots(rows)
    path_end = HEADER_STRUCT.size + len(records) + len(path_blob)
    hash_offset = (path_end + (HASH_SLOT_STRUCT.size - 1)) & ~(HASH_SLOT_STRUCT.size - 1)
    padding = b"\0" * (hash_offset - path_end)
    with output_tmp.open("wb") as f:
        f.write(HEADER_STRUCT.pack(INDEX_MAGIC, INDEX_VERSION, RECORD_STRUCT.size,
                                   len(rows), len(path_blob), hash_offset,
                                   HASH_SLOT_STRUCT.size, len(hash_slots)))
        f.write(records)
        f.write(path_blob)
        f.write(padding)
        for h, index_plus_one, flags in hash_slots:
            f.write(HASH_SLOT_STRUCT.pack(h, index_plus_one, flags))
    output_tmp.replace(output_path)
