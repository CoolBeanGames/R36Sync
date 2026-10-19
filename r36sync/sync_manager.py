"""
Sync and Save Backup Manager for R36Sync.
Coordinates local Library games, handheld SD card state diffing, bidirectional sync/unsync,
and automatic save file backups.
"""
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import shutil
from typing import Callable, Dict, List, Optional, Tuple, Any

from .config import CONSOLES, SAVE_EXTENSIONS, settings
from .cover_art import cover_manager
from .database import db


@dataclass
class LibraryGame:
    file_path: Path
    file_name: str
    stem: str
    console_code: str
    console_name: str
    size_bytes: int
    has_cover_art: bool
    cover_art_path: Optional[Path]
    is_on_handheld: bool
    is_checked: bool             # UI selection checkbox state
    has_save_backup: bool = False
    handheld_save_file: Optional[Path] = None

    @property
    def size_str(self) -> str:
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        elif self.size_bytes < 1024 * 1024 * 1024:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{self.size_bytes / (1024 * 1024 * 1024):.2f} GB"


@dataclass
class SyncResult:
    synced_count: int
    unsynced_count: int
    saves_backed_up: int
    errors: List[str]


class SyncManager:
    """Manages library scanning, handheld synchronization, and save game backups."""

    def __init__(self):
        pass

    def scan_library(
        self,
        library_dir: Optional[str] = None,
        sd_roms_root: Optional[Path] = None
    ) -> List[LibraryGame]:
        """
        Scans local library for downloaded and present ROM files.
        Checks handheld SD card to determine sync status and pre-checks already synced files.
        """
        lib_path = Path(library_dir or settings.library_dir)
        if not lib_path.exists():
            return []

        # Find existing files on handheld SD card for quick lookup
        sd_games_map = {}  # (console_code, stem) -> file_path
        sd_saves_map = {}  # (console_code, stem) -> save_file_path

        if sd_roms_root and sd_roms_root.exists():
            for console_dir in sd_roms_root.iterdir():
                if console_dir.is_dir() and not console_dir.name.startswith("."):
                    c_code = console_dir.name.lower()
                    for f in console_dir.iterdir():
                        if f.is_file():
                            ext = f.suffix.lower()
                            if ext in SAVE_EXTENSIONS:
                                sd_saves_map[(c_code, f.stem)] = f
                            elif ext in [".zip", ".7z", ".gba", ".gb", ".gbc", ".nes", ".sfc", ".smc", ".md", ".z64", ".n64", ".chd", ".cue", ".iso", ".pbp", ".nds", ".pce"]:
                                sd_games_map[(c_code, f.stem)] = f

        games: List[LibraryGame] = []

        # Scan each known console directory inside the library
        for code, c_def in CONSOLES.items():
            console_folder = lib_path / code
            if not console_folder.exists():
                continue

            for file_path in console_folder.iterdir():
                if not file_path.is_file():
                    continue

                ext = file_path.suffix.lower()
                if ext in [".png", ".jpg", ".txt", ".json", ".xml", ".torrent"] + SAVE_EXTENSIONS:
                    continue
                if c_def.extensions and ext not in c_def.extensions and ext not in [".zip", ".7z"]:
                    continue

                stem = file_path.stem
                size_bytes = file_path.stat().st_size

                # Check cover art
                cover_path = cover_manager.get_cover_art_path(str(lib_path), code, file_path.name)
                has_art = cover_path.exists()

                # Check handheld status
                is_on_handheld = (code, stem) in sd_games_map
                # Checkbox is checked if already on handheld
                is_checked = is_on_handheld

                # Check if handheld has an active save file
                handheld_save = sd_saves_map.get((code, stem))

                games.append(LibraryGame(
                    file_path=file_path,
                    file_name=file_path.name,
                    stem=stem,
                    console_code=code,
                    console_name=c_def.display_name,
                    size_bytes=size_bytes,
                    has_cover_art=has_art,
                    cover_art_path=cover_path if has_art else None,
                    is_on_handheld=is_on_handheld,
                    is_checked=is_checked,
                    handheld_save_file=handheld_save
                ))

        # Sort alphabetically by console then title
        games.sort(key=lambda g: (g.console_name, g.stem.lower()))
        return games

    def backup_handheld_saves(
        self,
        sd_roms_root: Path,
        backup_dir: Optional[str] = None
    ) -> Tuple[int, int, List[str]]:
        """
        Scans handheld SD card for all save files (.srm, .sav, .state*, etc.)
        and backs them up to both a timestamped directory and a 'latest' directory.
        Records each backup in the SQLite database.
        Returns (backed_up_count, total_bytes, list_of_backed_up_filenames).
        """
        if not sd_roms_root or not sd_roms_root.exists():
            return 0, 0, []

        base_backup = Path(backup_dir or settings.backup_dir)
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        history_dir = base_backup / "history" / timestamp_str
        latest_dir = base_backup / "latest"

        backed_up_files = []
        total_bytes = 0
        count = 0

        # Scan console folders and dedicated saves directories
        search_dirs = [sd_roms_root]
        for extra in ["saves", "retroarch/saves", ".config/retroarch/saves"]:
            p = sd_roms_root / extra
            if p.exists() and p.is_dir():
                search_dirs.append(p)

        for s_dir in search_dirs:
            for root, _, files in os.walk(s_dir):
                root_path = Path(root)
                # Determine console code from folder name
                rel_parts = root_path.relative_to(s_dir).parts
                console_code = rel_parts[0].lower() if rel_parts else "unknown"

                for fname in files:
                    ext = Path(fname).suffix.lower()
                    if ext in SAVE_EXTENSIONS:
                        source_file = root_path / fname
                        try:
                            fsize = source_file.stat().st_size
                            # Target paths
                            hist_dest = history_dir / console_code / fname
                            latest_dest = latest_dir / console_code / fname

                            hist_dest.parent.mkdir(parents=True, exist_ok=True)
                            latest_dest.parent.mkdir(parents=True, exist_ok=True)

                            shutil.copy2(source_file, hist_dest)
                            shutil.copy2(source_file, latest_dest)

                            # Record in database
                            db.record_save_backup(
                                game_title=source_file.stem,
                                console_code=console_code,
                                save_type=ext.lstrip("."),
                                file_name=fname,
                                source_path=str(source_file),
                                backup_path=str(latest_dest),
                                file_size=fsize
                            )

                            count += 1
                            total_bytes += fsize
                            backed_up_files.append(f"{console_code}/{fname}")
                        except Exception as e:
                            print(f"Error backing up save {source_file}: {e}")

        return count, total_bytes, backed_up_files

    def sync_to_handheld(
        self,
        games: List[LibraryGame],
        sd_roms_root: Path,
        backup_dir: Optional[str] = None,
        on_progress: Optional[Callable[[str, float], None]] = None
    ) -> SyncResult:
        """
        Executes full bidirectional sync:
        1. Backs up all save files from handheld SD card.
        2. Copies checked games (+ cover art) to handheld SD card.
        3. Unsyncs (deletes) unchecked games that are on handheld SD card.
        """
        errors = []
        synced_count = 0
        unsynced_count = 0

        # Step 1: Automatic save backup
        if on_progress:
            on_progress("Backing up save files from handheld...", 0.05)
        saves_count, saves_bytes, _ = self.backup_handheld_saves(sd_roms_root, backup_dir)

        total_actions = len(games)
        for i, game in enumerate(games, 1):
            progress_frac = 0.1 + (0.9 * (i / max(total_actions, 1)))

            target_console_dir = sd_roms_root / game.console_code
            target_console_dir.mkdir(parents=True, exist_ok=True)
            target_rom_file = target_console_dir / game.file_name

            images_dir = target_console_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            target_art_file = images_dir / f"{game.stem}-image.png"

            # Case A: User checked file, but it's not yet on handheld -> SYNC
            if game.is_checked and not game.is_on_handheld:
                if on_progress:
                    on_progress(f"Copying {game.file_name} to handheld...", progress_frac)
                try:
                    shutil.copy2(game.file_path, target_rom_file)

                    # Copy cover art if available
                    if game.cover_art_path and game.cover_art_path.exists():
                        shutil.copy2(game.cover_art_path, target_art_file)

                    game.is_on_handheld = True
                    synced_count += 1
                except Exception as e:
                    errors.append(f"Failed to copy {game.file_name}: {e}")

            # Case B: User unchecked file, and it was on handheld -> UNSYNC
            elif not game.is_checked and game.is_on_handheld:
                if on_progress:
                    on_progress(f"Unsyncing {game.file_name} from handheld...", progress_frac)
                try:
                    # Remove ROM file
                    if target_rom_file.exists():
                        target_rom_file.unlink()
                    # Remove cover art
                    if target_art_file.exists():
                        target_art_file.unlink()

                    game.is_on_handheld = False
                    unsynced_count += 1
                except Exception as e:
                    errors.append(f"Failed to remove {game.file_name}: {e}")

        if on_progress:
            on_progress("Sync complete!", 1.0)

        return SyncResult(
            synced_count=synced_count,
            unsynced_count=unsynced_count,
            saves_backed_up=saves_count,
            errors=errors
        )


# Global sync manager
sync_manager = SyncManager()
