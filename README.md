# R36Sync 🎮

A modern graphical desktop application for managing, downloading, and synchronizing retro games for the **R36S emulation handheld** (ArkOS / AmberELEC / UnofficialOS) with **[MiNERVA Archive](https://minerva-archive.org/)** integration and automatic cover art scraping.

---

## Key Features

1. **Minerva Archive Database Scanner & Offline Search**
   - Scans and indexes directories from [https://minerva-archive.org/](https://minerva-archive.org/) on launch or on-demand.
   - Builds an offline, lightning-fast local SQLite database (`r36sync.db`) containing filenames, consoles, sizes, torrent URLs, and magnet links.
   - Searches execute against the stored database in under 15ms—no repetitive network queries or archive server load.

2. **Library View (Main Page)**
   - Displays all downloaded games and ROMs present on disk in your library.
   - Displays game title, console badge, file size, cover art thumbnail, and handheld sync status.
   - Interactive checkboxes: Games already present on your R36S handheld appear checked automatically.
   - Quick filtering by search term and console.

3. **Browse View (Browse by System -> Expand by Game)**
   - Visual catalog of all 22+ retro systems with badges, game counts, and library indicators.
   - Click into any system to expand and browse all its games.
   - Quick A-Z alphabetical jumper bar (`#`, `A`, `B`, `C` ... `Z`) to jump directly to any letter.
   - One-click downloads with real-time Libretro cover art fetching.

4. **Download Manager & Search**
   - Instant search across 40,000+ indexed ROMs with console filtering.
   - One-click **"Download to Library"**: Downloads the ROM and automatically fetches high-resolution box art from the official Libretro thumbnail database.
   - Built-in high-speed `aria2c` downloader supporting BitTorrent file extraction.
   - Options to save `.torrent` files or launch magnet links in default torrent clients (e.g., qBittorrent).

4. **R36S Handheld SD Card Detection & Folder Structure Check**
   - Automatically detects connected SD cards with ArkOS / EASYROMS formatting.
   - Evaluates signature console folders (`gb`, `gba`, `snes`, `nes`, `megadrive`, `psx`, `n64`, `bios`, etc.) and volume labels.
   - Includes a **"Setup Standard R36S Folders"** tool to prepare fresh SD cards with the complete ArkOS directory and `images/` hierarchy.

5. **Bidirectional Sync & Unsync Engine**
   - **Syncing**: Any checked games not yet on the SD card are copied over with their box art (`images/<rom_name>-image.png`).
   - **Unsyncing**: If you uncheck a game that is currently on the handheld and click **Sync**, the game and its cover art are removed from the SD card.
   - Real-time progress modal with file transfer details.

6. **Automatic Save Game Backups**
   - Automatically discovers and backs up in-game battery saves (`.srm`, `.sav`) and save states (`.state*`) from the handheld before every sync.
   - Organizes saves in both a `latest/` directory and timestamped version archives in `history/`.
   - Built-in Save Backup manager allowing one-click restores back to the SD card.

---

## Supported Consoles & ArkOS Folder Mapping

| Console | R36S SD Folder | Minerva Source | Extensions |
| :--- | :--- | :--- | :--- |
| **Game Boy Advance** | `gba` | No-Intro Nintendo GBA | `.gba`, `.zip`, `.7z` |
| **Game Boy Color** | `gbc` | No-Intro Nintendo GBC | `.gbc`, `.zip`, `.7z` |
| **Game Boy** | `gb` | No-Intro Nintendo GB | `.gb`, `.zip`, `.7z` |
| **Super Nintendo (SNES)** | `snes` | No-Intro Super Nintendo | `.sfc`, `.smc`, `.zip` |
| **Nintendo Entertainment System** | `nes` | No-Intro NES Headered | `.nes`, `.zip`, `.7z` |
| **Sega Genesis / Mega Drive** | `megadrive` | No-Intro Sega Mega Drive | `.md`, `.gen`, `.bin`, `.zip` |
| **Nintendo 64** | `n64` | No-Intro Nintendo 64 | `.z64`, `.n64`, `.zip` |
| **Sony PlayStation 1** | `psx` | No-Intro / Redump PSX | `.chd`, `.pbp`, `.cue`, `.iso` |
| **Nintendo DS** | `nds` | No-Intro Nintendo DS | `.nds`, `.zip` |
| **Sega Game Gear** | `gamegear` | No-Intro Game Gear | `.gg`, `.zip` |
| **Sega Master System** | `mastersystem`| No-Intro Master System | `.sms`, `.zip` |
| **Sega 32X** | `sega32x` | No-Intro Sega 32X | `.32x`, `.zip` |
| **PC Engine / TurboGrafx-16** | `pcengine` | No-Intro NEC PC Engine | `.pce`, `.zip` |
| **SNK Neo Geo Pocket / Color** | `ngp` / `ngpc`| No-Intro NeoGeo Pocket | `.ngp`, `.ngc`, `.zip` |
| **Bandai WonderSwan / Color** | `wonderswan` | No-Intro WonderSwan | `.ws`, `.wsc`, `.zip` |
| **Atari 2600 / 7800 / Lynx** | `atari2600` / etc.| No-Intro Atari | `.a26`, `.a78`, `.lnx` |
| **ColecoVision** | `coleco` | No-Intro ColecoVision | `.col`, `.rom`, `.zip` |
| **Commodore 64** | `c64` | No-Intro Commodore 64 | `.d64`, `.prg`, `.zip` |

---

## Installation & Running

### Requirements
- Windows 10/11
- Python 3.12+ (or Python 3.14)

### Quick Start
1. Install Python dependencies:
   ```powershell
   py -3.12 -m pip install -r requirements.txt
   ```
2. Launch R36Sync:
   - Double-click `run_r36sync.bat`, or
   - Run via terminal:
     ```powershell
     py -3.12 main.py
     ```

### Testing
Run the automated test suite:
```powershell
py -3.12 -m unittest tests/test_r36sync.py
```

---

## Project Architecture

```
R36Sync/
├── bin/
│   └── aria2c.exe              # High-speed BitTorrent & HTTP download engine
├── r36sync/
│   ├── config.py               # Console definitions, paths, settings
│   ├── database.py             # SQLite database and fast offline search
│   ├── minerva_scanner.py      # Minerva Archive crawler and cataloger
│   ├── cover_art.py            # Libretro box art fetcher and thumbnail cache
│   ├── sd_detector.py          # Windows drive & ArkOS folder structure detection
│   ├── sync_manager.py         # Handheld sync/unsync and save backup engine
│   ├── downloader.py           # Download queue with aria2c integration
│   └── gui/
│       ├── app.py              # Main CustomTkinter application window
│       ├── library_view.py     # Main Page: Library listing & sync checkboxes
│       ├── browse_view.py      # Browse Tab: Browse by System -> Expand by Game
│       ├── download_view.py    # Download Tab: Searchable Minerva catalog
│       ├── handheld_view.py    # SD Card & Sync Tab: Hardware & saves manager
│       ├── scanner_view.py     # Minerva Database Tab: Indexing coverage
│       └── settings_view.py    # Preferences, paths, and theme configuration
├── tests/
│   └── test_r36sync.py         # Full unit test suite
├── main.py                     # Application entry point
├── run_r36sync.bat             # Windows launcher script
└── requirements.txt            # Python dependencies
```

---

## License
MIT License. Created for the retro gaming and R36S community.
