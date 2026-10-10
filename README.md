# Lazy_AMPR

Lazy_AMPR is a desktop and web front end for building or extracting AMPR LZ4 asset packs. It integrates the [`ampr_emu`](https://github.com/drakmor/ampr_emu) packing tools and supports folder-based workflows on Windows, Linux and macOS. Source executables are not downgraded, rewritten, or signed by the application.

The main purpose of Lazy_AMPR is to help reduce game space. It is not a general-purpose game modification suite.

## Compatibility notes

Not all PS5 games have been tested. Some games may not work correctly, and results can vary by title or region.

For best results, use a TOML profile generated from traces for the game you are working with. Running without a trace-generated TOML is supported, but it is less reliable and may not produce correct output. If a game-specific TOML is available, prefer it over guessing or using a generic profile.

## Image mounting

On Windows, ShadowMountPlus exFAT images can be mounted read-only and processed directly with OSFMount 3, without a temporary full-image extraction. The Windows package requests administrator privileges because OSFMount requires them; its mount and unmount commands run without opening a Command Prompt window.

On Linux, mount the image with an appropriate system tool first, then select the mounted game folder in Lazy_AMPR. Direct OSFMount image mounting remains Windows-only. Linux exFAT mount support is planned; see the TODO list below.

On macOS, mount the image first with Disk Utility or `hdiutil attach -readonly <image>`, then select the mounted game folder. The "exFAT image" picker is only shown on Windows; native macOS mounting through `hdiutil` is planned.

## Docker / Unraid (web UI)

Lazy_AMPR also ships as a headless Docker container with a web interface, so it can run on a NAS such as Unraid and be used from any browser. It uses the same packing core as the desktop app (no Qt inside the container).

The image is published to `ghcr.io/tobim-dev/lazy_ampr:latest` (amd64 and arm64) by the `Docker image` workflow on every push to `main` and for `v*` tags.

### Unraid

1. Copy `unraid/lazy-ampr.xml` to `/boot/config/plugins/dockerMan/templates-user/my-lazy-ampr.xml` on your Unraid flash drive (for example via the terminal: `wget -O /boot/config/plugins/dockerMan/templates-user/my-lazy-ampr.xml https://raw.githubusercontent.com/tobim-dev/lazy_ampr/main/unraid/lazy-ampr.xml`).
2. In the Unraid web UI go to **Docker → Add Container**, pick **lazy-ampr** under *Template*.
3. Set the paths:
   - **Games** (`/games`): the share with your PS5 game folders. Read-only is fine.
   - **Output** (`/output`): where `<game>_AMPR` and extracted folders are written.
   - **AppData** (`/config`): settings, state and TOML profiles.
4. Optionally set **Web UI password** (HTTP basic auth, user `admin` by default).
5. Apply, then click the container icon → **WebUI** (port 8080).

The container runs as `PUID`/`PGID` (default `99:100`, Unraid's `nobody:users`) with `UMASK=000`, so output files are owned like other share files.

### Docker Compose / plain Docker

```bash
docker run -d --name lazy-ampr -p 8080:8080 \
  -v /path/to/appdata:/config \
  -v /path/to/games:/games:ro \
  -v /path/to/output:/output \
  -e LAZY_AMPR_PASSWORD=change-me \
  ghcr.io/tobim-dev/lazy_ampr:latest
```

or `docker compose up -d` with the included `docker-compose.yml`. To build the image yourself: `docker build -t lazy-ampr .`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LAZY_AMPR_ROOTS` | `/games,/output` | Container folders the web UI may browse and use. Everything else is rejected. |
| `LAZY_AMPR_DEFAULT_OUTPUT` | `/output` | Output base when no output folder is set in Settings. |
| `LAZY_AMPR_PASSWORD` | *(empty)* | Enables HTTP basic auth when set. |
| `LAZY_AMPR_USERNAME` | `admin` | User name for basic auth. |
| `LAZY_AMPR_PORT` | `8080` | Port inside the container. |
| `PUID` / `PGID` / `UMASK` | `99` / `100` / `000` | User, group and umask the app runs with. |

### Using the web UI

- **Games**: scan a folder (e.g. `/games`), pick a TOML profile per game (auto-matched by title ID/name like the desktop app), and click **Pack**, or select several games and use **Pack selected** (batch). **TOML from traces** appears when a game folder has a `traces` folder.
- **Extract**: rebuild the original tree from an `_AMPR` folder.
- **Jobs**: jobs run one at a time in the background with progress, elapsed time, cancel and the full log. They keep running if you close the browser.
- **TOML profiles**: upload, paste/edit, delete, or import profiles from a direct `.toml` URL or a GitHub repo/tree URL.
- **Settings**: the same packing settings as the desktop app.

Image mounting (exFAT/OSFMount) is not available in the container; extract or mount images on the host and point `/games` at the game folders. Don't expose the web UI to the internet; it can read and write the mapped folders. Use a VPN or a reverse proxy with authentication if you need remote access.

For local development of the web UI: `pip install -r requirements-web.txt` then `LAZY_AMPR_ROOTS=/some/games,/some/output python -m web`.

## Run from source

Use Python 3.12, install `requirements.txt`, then run:

```powershell
python main.py
```

Application settings and imported TOML profiles use the platform application data directory:

- Windows: `%APPDATA%\Lazy_AMPR`
- Linux: `$XDG_CONFIG_HOME/lazy_ampr` or `~/.config/lazy_ampr`
- macOS: `~/Library/Application Support/Lazy_AMPR`

## Test

```powershell
python -m unittest discover -s tests -v
```

The test suite includes exFAT detection and OSFMount command regression tests.

## Build for Windows

Create `.venv312`, install the requirements plus PyInstaller, then run:

```powershell
.\build_windows.ps1
```

The distributable archive is written under the parent `release` directory.

## Build for Linux

Run the clean PyInstaller build from a native Linux environment:

```bash
./build_linux.sh
```

The Linux build produces an AppImage. The AppImage and its SHA-256 manifest are written under the parent `release` directory. Folder-based packing and extraction are supported; direct OSFMount image mounting remains Windows-only.

## Build for macOS

Run the native PyInstaller build on a Mac with Python 3.12 available:

```bash
PYTHON=python3.12 ./build_macos.sh
```

The script creates `.venv-macos` on first use, builds `Lazy_AMPR.app` for the host architecture, and writes `Lazy_AMPR-<version>-macOS-<arm64|x86_64>.zip` plus `SHA256SUMS.txt` under the parent `release` directory (override the base with `LAZY_AMPR_RELEASE_BASE`). Apple Silicon and Intel builds are separate; the app requires macOS 13 or newer.

The bundle is ad-hoc signed and not notarized, so Gatekeeper blocks the first launch of a downloaded copy. Either remove the quarantine flag once:

```bash
xattr -dr com.apple.quarantine Lazy_AMPR.app
```

or right-click the app, choose Open, and confirm in System Settings > Privacy & Security.

## Continuous integration

Every push and pull request runs the unit tests on Ubuntu, Windows and macOS, then builds the macOS app for arm64 and x86_64 and uploads the zips as workflow artifacts. Pushing a tag `vX.Y.Z` that matches `version.py` publishes those zips and a merged checksum file as a GitHub Release.

## Notes

The PS5 PRX sources under `external/`[`ampr_emu`](https://github.com/drakmor/ampr_emu) require the separate `ps5-payload-sdk`; they are not compiled by either desktop build.

macOS builds for Apple Silicon and Intel are produced by CI. They are ad-hoc signed only; see "Build for macOS" for the first-launch step.

## Credits

- Nazky ([GitHub](https://github.com/Nazky) | [Twitter](https://x.com/NazkyYT))
- Deckerr97 ([GitHub](https://github.com/kerrdec97) | [Twitter](https://x.com/kerrdec97))
- Pippo ([Twitter](https://x.com/itz_pippo))
- Drakmor ([GitHub](https://github.com/drakmor))
- williamtcastro ([GitHub](https://github.com/williamtcastro)) | [Twitter](https://x.com/williamtcastro)) 

## TODO

- [ ] Add a logo
- [ ] Add better exFAT support
- [x] Add macOS support
- [ ] Add exFAT mount support on Linux
- [ ] Add better download manager for TOML files
- [ ] Add more games support
- [ ] Making a good tuto to use the software (too tired to do it right now lol)
