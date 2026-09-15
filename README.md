# Lazy_AMPR

Lazy_AMPR is a desktop front end for building or extracting AMPR LZ4 asset packs. It integrates the [`ampr_emu`](https://github.com/drakmor/ampr_emu) packing tools and supports folder-based workflows on Windows and Linux. Source executables are not downgraded, rewritten, or signed by the application.

The main purpose of Lazy_AMPR is to help reduce game space. It is not a general-purpose game modification suite.

## Compatibility notes

Not all PS5 games have been tested. Some games may not work correctly, and results can vary by title or region.

For best results, use a TOML profile generated from traces for the game you are working with. Running without a trace-generated TOML is supported, but it is less reliable and may not produce correct output. If a game-specific TOML is available, prefer it over guessing or using a generic profile.

## Image mounting

On Windows, ShadowMountPlus exFAT images can be mounted read-only and processed directly with OSFMount 3, without a temporary full-image extraction. The Windows package requests administrator privileges because OSFMount requires them; its mount and unmount commands run without opening a Command Prompt window.

On Linux, mount the image with an appropriate system tool first, then select the mounted game folder in Lazy_AMPR. Direct OSFMount image mounting remains Windows-only. Linux exFAT mount support is planned; see the TODO list below.

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

## Notes

The PS5 PRX sources under `external/`[`ampr_emu`](https://github.com/drakmor/ampr_emu) require the separate `ps5-payload-sdk`; they are not compiled by either desktop build.

The shared Python/UI code contains macOS-aware paths and browser/file-manager integration, but no macOS release has been validated yet.

## Credits

- Nazky ([GitHub](https://github.com/Nazky) | [Twitter](https://x.com/NazkyYT))
- Deckerr97 ([GitHub](https://github.com/kerrdec97) | [Twitter](https://x.com/kerrdec97))
- Pippo ([Twitter](https://x.com/itz_pippo))
- Drakmor ([GitHub](https://github.com/drakmor))

## TODO

- [ ] Add a logo
- [ ] Add better exFAT support
- [ ] Add macOS support
- [ ] Add exFAT mount support on Linux
- [ ] Add better download manager for TOML files
- [ ] Add more games support