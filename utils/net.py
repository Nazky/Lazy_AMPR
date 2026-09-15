import json
import posixpath
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import tomllib

UA = {"User-Agent": "LazyAMPR/0.1"}
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024

def _get(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only HTTP and HTTPS URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not supported")
    # The scheme and authority are validated immediately above and redirects
    # are checked again below; urllib is used here deliberately.
    with urllib.request.urlopen(  # nosec B310
        urllib.request.Request(url, headers=UA), timeout=30
    ) as response:
        final = urlsplit(response.geturl())
        if final.scheme not in {"http", "https"}:
            raise ValueError("Download redirected to an unsupported URL scheme")
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_DOWNLOAD_BYTES:
            raise ValueError("TOML download is larger than 4 MiB")
        data = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise ValueError("TOML download is larger than 4 MiB")
        return data

def _github(url):
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+)(/.*)?)?/?$", url)
    if not m: return None
    o, r, b, p = m.groups()
    return o, r, b or "HEAD", (p or "/").strip("/")

def list_tomls_at_url(url):
    gh = _github(url)
    if gh:
        o, r, b, p = gh
        data = json.loads(_get(f"https://api.github.com/repos/{o}/{r}/contents/{p}?ref={b}"))
        if isinstance(data, dict): data = [data]
        return [(i["name"], i["download_url"])
                for i in data if i.get("type") == "file"
                and i.get("download_url")
                and i["name"].casefold().endswith(".toml")]
    if url.split("?")[0].endswith(".toml"):
        return [(posixpath.basename(url.split("?")[0]), url)]
    raise ValueError("Unsupported URL — use a direct .toml link or a GitHub repo/tree URL")

def download_toml(name, url, dest_dir: Path):
    safe_name = Path(name).name
    if safe_name != name or not safe_name.casefold().endswith(".toml"):
        raise ValueError("Invalid TOML filename")
    data = _get(url)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Downloaded TOML is not valid UTF-8 text") from exc
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("Downloaded TOML has invalid syntax") from exc
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe_name
    temporary = dest.with_suffix(dest.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(dest)
    return dest
