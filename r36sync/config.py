"""
Configuration and settings management for R36Sync.
Defines console mappings for ArkOS/R36S, Minerva Archive endpoints, and paths.
"""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Dict, List, Optional


@dataclass
class ConsoleDef:
    code: str                      # R36S folder name (e.g. 'gba', 'gb', 'snes')
    display_name: str              # User-friendly name (e.g. 'Nintendo - Game Boy Advance')
    minerva_path: str              # Path on Minerva Archive browse
    minerva_group: str             # Group (e.g. 'No-Intro', 'Redump')
    libretro_name: str             # Libretro thumbnail repository name
    extensions: List[str]          # Accepted ROM extensions
    torrent_prefix: str = ""       # Torrent filename on Minerva if standard
    extra_paths: List[str] = field(default_factory=list)  # Additional Minerva directory paths to index


# R36S / ArkOS standard console directory definitions and Minerva mappings
CONSOLES: Dict[str, ConsoleDef] = {
    "gba": ConsoleDef(
        code="gba",
        display_name="Game Boy Advance",
        minerva_path="No-Intro/Nintendo - Game Boy Advance/",
        minerva_group="No-Intro",
        libretro_name="Nintendo - Game Boy Advance",
        extensions=[".gba", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Nintendo - Game Boy Advance.torrent"
    ),
    "gbc": ConsoleDef(
        code="gbc",
        display_name="Game Boy Color",
        minerva_path="No-Intro/Nintendo - Game Boy Color/",
        minerva_group="No-Intro",
        libretro_name="Nintendo - Game Boy Color",
        extensions=[".gbc", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Nintendo - Game Boy Color.torrent"
    ),
    "gb": ConsoleDef(
        code="gb",
        display_name="Game Boy",
        minerva_path="No-Intro/Nintendo - Game Boy/",
        minerva_group="No-Intro",
        libretro_name="Nintendo - Game Boy",
        extensions=[".gb", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Nintendo - Game Boy.torrent"
    ),
    "snes": ConsoleDef(
        code="snes",
        display_name="Super Nintendo (SNES)",
        minerva_path="No-Intro/Nintendo - Super Nintendo Entertainment System/",
        minerva_group="No-Intro",
        libretro_name="Nintendo - Super Nintendo Entertainment System",
        extensions=[".sfc", ".smc", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Nintendo - Super Nintendo Entertainment System.torrent"
    ),
    "nes": ConsoleDef(
        code="nes",
        display_name="Nintendo Entertainment System (NES)",
        minerva_path="No-Intro/Nintendo - Nintendo Entertainment System (Headered)/",
        minerva_group="No-Intro",
        libretro_name="Nintendo - Nintendo Entertainment System",
        extensions=[".nes", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Nintendo - Nintendo Entertainment System (Headered).torrent"
    ),
    "megadrive": ConsoleDef(
        code="megadrive",
        display_name="Sega Genesis / Mega Drive",
        minerva_path="No-Intro/Sega - Mega Drive - Genesis/",
        minerva_group="No-Intro",
        libretro_name="Sega - Mega Drive - Genesis",
        extensions=[".md", ".gen", ".bin", ".smd", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Sega - Mega Drive - Genesis.torrent"
    ),
    "n64": ConsoleDef(
        code="n64",
        display_name="Nintendo 64",
        minerva_path="No-Intro/Nintendo - Nintendo 64 (BigEndian)/",
        minerva_group="No-Intro",
        libretro_name="Nintendo - Nintendo 64",
        extensions=[".z64", ".n64", ".v64", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Nintendo - Nintendo 64 (BigEndian).torrent"
    ),
    "psx": ConsoleDef(
        code="psx",
        display_name="Sony PlayStation",
        minerva_path="Redump/Sony - PlayStation/",
        minerva_group="Redump",
        libretro_name="Sony - PlayStation",
        extensions=[".chd", ".pbp", ".cue", ".iso", ".bin", ".zip", ".7z", ".m3u", ".m3a"],
        torrent_prefix="Minerva_Myrient - Redump - Sony - PlayStation.torrent",
        extra_paths=["No-Intro/Sony - PlayStation (PS one Classics) (PSN)/"]
    ),
    "nds": ConsoleDef(
        code="nds",
        display_name="Nintendo DS",
        minerva_path="No-Intro/Nintendo - Nintendo DS (Decrypted)/",
        minerva_group="No-Intro",
        libretro_name="Nintendo - Nintendo DS",
        extensions=[".nds", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Nintendo - Nintendo DS (Decrypted).torrent"
    ),
    "gamegear": ConsoleDef(
        code="gamegear",
        display_name="Sega Game Gear",
        minerva_path="No-Intro/Sega - Game Gear/",
        minerva_group="No-Intro",
        libretro_name="Sega - Game Gear",
        extensions=[".gg", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Sega - Game Gear.torrent"
    ),
    "mastersystem": ConsoleDef(
        code="mastersystem",
        display_name="Sega Master System",
        minerva_path="No-Intro/Sega - Master System - Mark III/",
        minerva_group="No-Intro",
        libretro_name="Sega - Master System - Mark III",
        extensions=[".sms", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Sega - Master System - Mark III.torrent"
    ),
    "sega32x": ConsoleDef(
        code="sega32x",
        display_name="Sega 32X",
        minerva_path="No-Intro/Sega - 32X/",
        minerva_group="No-Intro",
        libretro_name="Sega - 32X",
        extensions=[".32x", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Sega - 32X.torrent"
    ),
    "sg1000": ConsoleDef(
        code="sg1000",
        display_name="Sega SG-1000",
        minerva_path="No-Intro/Sega - SG-1000/",
        minerva_group="No-Intro",
        libretro_name="Sega - SG-1000",
        extensions=[".sg", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Sega - SG-1000.torrent"
    ),
    "pcengine": ConsoleDef(
        code="pcengine",
        display_name="PC Engine / TurboGrafx-16",
        minerva_path="No-Intro/NEC - PC Engine - TurboGrafx-16/",
        minerva_group="No-Intro",
        libretro_name="NEC - PC Engine - TurboGrafx 16",
        extensions=[".pce", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - NEC - PC Engine - TurboGrafx-16.torrent"
    ),
    "supergrafx": ConsoleDef(
        code="supergrafx",
        display_name="PC Engine SuperGrafx",
        minerva_path="No-Intro/NEC - PC Engine SuperGrafx/",
        minerva_group="No-Intro",
        libretro_name="NEC - PC Engine SuperGrafx",
        extensions=[".sgx", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - NEC - PC Engine SuperGrafx.torrent"
    ),
    "ngp": ConsoleDef(
        code="ngp",
        display_name="SNK Neo Geo Pocket",
        minerva_path="No-Intro/SNK - NeoGeo Pocket/",
        minerva_group="No-Intro",
        libretro_name="SNK - Neo Geo Pocket",
        extensions=[".ngp", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - SNK - NeoGeo Pocket.torrent"
    ),
    "ngpc": ConsoleDef(
        code="ngpc",
        display_name="SNK Neo Geo Pocket Color",
        minerva_path="No-Intro/SNK - NeoGeo Pocket Color/",
        minerva_group="No-Intro",
        libretro_name="SNK - Neo Geo Pocket Color",
        extensions=[".ngc", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - SNK - NeoGeo Pocket Color.torrent"
    ),
    "wonderswan": ConsoleDef(
        code="wonderswan",
        display_name="Bandai WonderSwan",
        minerva_path="No-Intro/Bandai - WonderSwan/",
        minerva_group="No-Intro",
        libretro_name="Bandai - WonderSwan",
        extensions=[".ws", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Bandai - WonderSwan.torrent"
    ),
    "wonderswancolor": ConsoleDef(
        code="wonderswancolor",
        display_name="Bandai WonderSwan Color",
        minerva_path="No-Intro/Bandai - WonderSwan Color/",
        minerva_group="No-Intro",
        libretro_name="Bandai - WonderSwan Color",
        extensions=[".wsc", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Bandai - WonderSwan Color.torrent"
    ),
    "atari2600": ConsoleDef(
        code="atari2600",
        display_name="Atari 2600",
        minerva_path="No-Intro/Atari - Atari 2600/",
        minerva_group="No-Intro",
        libretro_name="Atari - 2600",
        extensions=[".a26", ".bin", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Atari - Atari 2600.torrent"
    ),
    "atari7800": ConsoleDef(
        code="atari7800",
        display_name="Atari 7800",
        minerva_path="No-Intro/Atari - Atari 7800 (BIN)/",
        minerva_group="No-Intro",
        libretro_name="Atari - 7800",
        extensions=[".a78", ".bin", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Atari - Atari 7800 (BIN).torrent"
    ),
    "atarilynx": ConsoleDef(
        code="atarilynx",
        display_name="Atari Lynx",
        minerva_path="No-Intro/Atari - Atari Lynx/",
        minerva_group="No-Intro",
        libretro_name="Atari - Lynx",
        extensions=[".lnx", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Atari - Atari Lynx.torrent"
    ),
    "coleco": ConsoleDef(
        code="coleco",
        display_name="ColecoVision",
        minerva_path="No-Intro/Coleco - ColecoVision/",
        minerva_group="No-Intro",
        libretro_name="Coleco - ColecoVision",
        extensions=[".col", ".rom", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Coleco - ColecoVision.torrent"
    ),
    "c64": ConsoleDef(
        code="c64",
        display_name="Commodore 64",
        minerva_path="No-Intro/Commodore - 64/",
        minerva_group="No-Intro",
        libretro_name="Commodore - 64",
        extensions=[".d64", ".t64", ".prg", ".crt", ".zip", ".7z"],
        torrent_prefix="Minerva_Myrient - No-Intro - Commodore - 64.torrent"
    ),
}

# Recognized save file extensions
SAVE_EXTENSIONS = [
    ".srm", ".sav", ".state", ".state1", ".state2", ".state3", ".state4",
    ".state5", ".state6", ".state7", ".state8", ".state9", ".eep", ".fla",
    ".dsv", ".rtc", ".fs", ".nv"
]

if getattr(sys, 'frozen', False):
    BUNDLE_DIR = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    APP_DIR = Path(sys.executable).parent
else:
    BUNDLE_DIR = Path(__file__).resolve().parent.parent
    APP_DIR = BUNDLE_DIR

BASE_DIR = APP_DIR
DEFAULT_LIBRARY_DIR = Path.home() / "Documents" / "R36Sync_Library"
DEFAULT_BACKUP_DIR = DEFAULT_LIBRARY_DIR / "backups"
SETTINGS_FILE = APP_DIR / "settings.json"

if (APP_DIR / "r36sync.db").exists():
    DB_FILE = APP_DIR / "r36sync.db"
elif (BUNDLE_DIR / "r36sync.db").exists():
    DB_FILE = BUNDLE_DIR / "r36sync.db"
else:
    DB_FILE = APP_DIR / "r36sync.db"


def _find_aria2_path() -> Path:
    bin_name = "aria2c.exe" if os.name == 'nt' else "aria2c"
    candidates = [
        APP_DIR / "bin" / bin_name,
        APP_DIR / bin_name,
        BUNDLE_DIR / "bin" / bin_name,
        BUNDLE_DIR / bin_name
    ]
    for c in candidates:
        if c.exists():
            return c
    system_aria = shutil.which("aria2c")
    if system_aria:
        return Path(system_aria)
    return APP_DIR / "bin" / bin_name


ARIA2_PATH = _find_aria2_path()


class Settings:
    """Manages application settings persisted as JSON."""

    def __init__(self):
        self.library_dir: str = str(DEFAULT_LIBRARY_DIR)
        self.backup_dir: str = str(DEFAULT_BACKUP_DIR)
        self.sd_card_dir: Optional[str] = None
        self.auto_scan_on_launch: bool = False
        self.auto_backup_saves: bool = True
        self.download_cover_art: bool = True
        self.playlist_format: str = "m3a"
        self.auto_create_playlists: bool = True
        self.theme: str = "Dark"
        self.load()

    def load(self):
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.library_dir = data.get("library_dir", str(DEFAULT_LIBRARY_DIR))
                    self.backup_dir = data.get("backup_dir", str(DEFAULT_BACKUP_DIR))
                    self.sd_card_dir = data.get("sd_card_dir")
                    self.auto_scan_on_launch = data.get("auto_scan_on_launch", False)
                    self.auto_backup_saves = data.get("auto_backup_saves", True)
                    self.download_cover_art = data.get("download_cover_art", True)
                    self.playlist_format = data.get("playlist_format", "m3a")
                    self.auto_create_playlists = data.get("auto_create_playlists", True)
                    self.theme = data.get("theme", "Dark")
            except Exception as e:
                print(f"Warning: Failed to load settings: {e}")

        # Ensure directories exist
        Path(self.library_dir).mkdir(parents=True, exist_ok=True)
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)

    def save(self):
        try:
            data = {
                "library_dir": self.library_dir,
                "backup_dir": self.backup_dir,
                "sd_card_dir": self.sd_card_dir,
                "auto_scan_on_launch": self.auto_scan_on_launch,
                "auto_backup_saves": self.auto_backup_saves,
                "download_cover_art": self.download_cover_art,
                "playlist_format": self.playlist_format,
                "auto_create_playlists": self.auto_create_playlists,
                "theme": self.theme
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")


# Global settings singleton
settings = Settings()
