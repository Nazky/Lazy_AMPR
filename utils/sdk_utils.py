"""Decode PS4/PS5 SDK / SYSTEM_VER values into human-readable form.

Handles every layout seen in the wild:
  - 64-bit:  0x0900000000000000   (version in the top two bytes)
  - 32-bit:  0x09000000           (param.sfo SYSTEM_VER)
  - 16-bit:  0x0900
  - plain:   9  /  "9"  /  "9.00" / "0x09000000"
Version bytes are BCD-encoded decimal digits (0x11 == 11, 0x72 == 72).
"""


def _bcd(b: int) -> int:
    """Decode one BCD byte; also tolerates plain-hex bytes (0x0B -> 11)."""
    return (b >> 4) * 10 + (b & 0x0F)


def _parse_pair(raw):
    """Return (major, minor) as plain ints."""
    if raw is None:
        return (0, 0)

    if isinstance(raw, str):
        s = raw.strip().lower()
        if not s or s in ("unknown", "—", "-"):
            return (0, 0)
        # Already a human dotted string like "9.00" / "6.72"
        if "." in s and not s.startswith("0x"):
            try:
                maj, minor = s.split(".", 1)
                return (int(maj), int(minor))
            except ValueError:
                return (0, 0)
        try:
            v = int(s, 16) if s.startswith("0x") else int(s, 0)
        except ValueError:
            return (0, 0)
    elif isinstance(raw, int):
        v = raw
    else:
        return (0, 0)

    if v == 0:
        return (0, 0)

    if v > 0xFFFFFFFF:          # 64-bit layout
        maj_b = (v >> 56) & 0xFF
        min_b = (v >> 48) & 0xFF
    elif v > 0xFFFF:            # 32-bit layout
        maj_b = (v >> 24) & 0xFF
        min_b = (v >> 16) & 0xFF
    elif v > 0xFF:              # 16-bit layout
        maj_b = (v >> 8) & 0xFF
        min_b = v & 0xFF
    else:                       # plain major only
        return (v, 0)

    return (_bcd(maj_b), _bcd(min_b))


def parse_sdk(raw) -> int:
    """Normalize any SDK representation to the canonical 32-bit int (0xMMmm0000)."""
    maj, minor = _parse_pair(raw)
    return (maj << 24) | (minor << 16)


def sdk_to_human(raw) -> str:
    """Convert any SDK representation to a human string like '9.00' or '6.72'."""
    maj, minor = _parse_pair(raw)
    if maj == 0 and minor == 0:
        return "—"
    return f"{maj}.{minor:02d}"