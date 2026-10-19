"""
M3U / M3A Multi-Disc Playlist Manager for R36Sync.
Discovers multi-disc game titles (PS1, Sega CD, Dreamcast, etc.), groups disc files in order,
and creates .m3u (or .m3a) playlists along with cover art linking.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
from typing import Dict, List, Optional, Tuple, Any

from .config import CONSOLES, settings
from .cover_art import cover_manager


DISC_EXTENSIONS = {
    ".chd", ".cue", ".iso", ".pbp", ".bin", ".img",
    ".cdi", ".gdi", ".zip", ".7z", ".toc"
}


@dataclass
class MultiDiscSet:
    base_name: str                     # e.g. "Final Fantasy VII (USA)"
    console_code: str                  # e.g. "psx"
    folder_path: Path                  # Folder containing the games
    disc_files: List[Path]             # Ordered list of disc files (Disc 1, Disc 2...)
    disc_labels: List[str]             # e.g. ["Disc 1", "Disc 2", "Disc 3"]
    has_playlist: bool                 # True if .m3u or .m3a already exists
    playlist_path: Optional[Path] = None
    playlist_extension: str = ".m3u"   # ".m3u" or ".m3a"

    @property
    def disc_count(self) -> int:
        return len(self.disc_files)

    @property
    def total_size_bytes(self) -> int:
        total = 0
        for f in self.disc_files:
            try:
                total += f.stat().st_size
            except Exception:
                pass
        return total

    @property
    def size_str(self) -> str:
        s = self.total_size_bytes
        if s < 1024 * 1024:
            return f"{s / 1024:.1f} KB"
        elif s < 1024 * 1024 * 1024:
            return f"{s / (1024 * 1024):.1f} MB"
        else:
            return f"{s / (1024 * 1024 * 1024):.2f} GB"


class M3UManager:
    """Detects multi-disc files and generates .m3u / .m3a playlists for retro handhelds."""

    @staticmethod
    def extract_disc_info(filename: str) -> Tuple[Optional[str], Optional[str], Any]:
        """
        Extracts (base_title, disc_label, sort_key) from a filename.
        Returns (None, None, None) if not a multi-disc file.
        """
        stem = Path(filename).stem

        # Match (Disc 1), [Disc 1 of 2], (CD 1), (Disk A), etc.
        m = re.search(r'[\(\[]\s*(?:Disc|CD|Disk|Part)\s*([0-9A-Za-z]+)(?:\s*of\s*[0-9]+)?[\)\]]', stem, re.IGNORECASE)
        if not m:
            m = re.search(r'\b(?:Disc|CD|Disk|Part)\s*([0-9A-Za-z]+)\b', stem, re.IGNORECASE)

        if not m:
            return None, None, None

        token = m.group(1)
        disc_label = f"Disc {token}"

        # Sorting key: integer if numeric, else ord of first letter
        try:
            sort_key = (0, int(token))
        except ValueError:
            sort_key = (1, ord(token[0].upper()) if token else 0)

        # Base title: substring before the disc tag
        base = re.split(r'[\(\[]\s*(?:Disc|CD|Disk|Part)\b', stem, flags=re.IGNORECASE)[0].strip()
        if not base:
            base = stem

        # Clean trailing dashes or spaces
        base = re.sub(r'[\s_\-]+$', '', base).strip()
        return base, disc_label, sort_key

    def scan_directory_for_multidisc(
        self,
        directory: Path,
        console_code: str = "psx"
    ) -> List[MultiDiscSet]:
        """Scans a directory for multi-disc games and checks playlist existence."""
        if not directory.exists() or not directory.is_dir():
            return []

        # Find existing playlists (.m3u, .m3a)
        existing_playlists: Dict[str, Path] = {}
        for f in directory.iterdir():
            if f.is_file() and f.suffix.lower() in [".m3u", ".m3a"]:
                existing_playlists[f.stem.lower()] = f

        # Group disc files
        # base_name -> list of (sort_key, disc_label, file_path)
        groups: Dict[str, List[Tuple[Any, str, Path]]] = {}

        # Scan files in directory and immediate subfolders (e.g. .discs/ or <Game>/)
        search_dirs = [directory]
        for sub in directory.iterdir():
            if sub.is_dir() and sub.name.lower() not in ["images", "backups", "saves"]:
                search_dirs.append(sub)

        for s_dir in search_dirs:
            for f in s_dir.iterdir():
                if not f.is_file():
                    continue
                ext = f.suffix.lower()
                if ext not in DISC_EXTENSIONS:
                    continue

                base, label, sort_key = self.extract_disc_info(f.name)
                if base:
                    groups.setdefault(base, []).append((sort_key, label, f))

        sets: List[MultiDiscSet] = []
        for base_name, items in groups.items():
            # A multi-disc set must have 2 or more discs
            if len(items) < 2:
                continue

            # Sort discs chronologically
            items.sort(key=lambda x: x[0])
            disc_files = [x[2] for x in items]
            disc_labels = [x[1] for x in items]

            # Check if playlist exists
            pl_path = existing_playlists.get(base_name.lower())
            has_pl = pl_path is not None and pl_path.exists()
            pl_ext = pl_path.suffix.lower() if pl_path else ".m3u"

            sets.append(MultiDiscSet(
                base_name=base_name,
                console_code=console_code,
                folder_path=directory,
                disc_files=disc_files,
                disc_labels=disc_labels,
                has_playlist=has_pl,
                playlist_path=pl_path,
                playlist_extension=pl_ext
            ))

        sets.sort(key=lambda s: s.base_name.lower())
        return sets

    def scan_library(self, library_dir: Optional[str] = None) -> List[MultiDiscSet]:
        """Scans all console directories in the library for multi-disc titles."""
        lib_root = Path(library_dir or settings.library_dir)
        all_sets = []

        # Disc-capable consoles prioritized
        disc_consoles = ["psx", "segacd", "dreamcast", "saturn", "pcengine", "supergrafx", "c64"]
        other_consoles = [c for c in CONSOLES.keys() if c not in disc_consoles]

        for code in disc_consoles + other_consoles:
            console_dir = lib_root / code
            if console_dir.exists():
                sets = self.scan_directory_for_multidisc(console_dir, code)
                all_sets.extend(sets)

        return all_sets

    def create_playlist(
        self,
        set_info: MultiDiscSet,
        extension: str = ".m3u",
        organize_subfolder: bool = False
    ) -> Path:
        """
        Creates the .m3u (or .m3a) playlist file.
        Also copies Disc 1 box art to <base_name>-image.png for ArkOS display.
        """
        ext = extension.strip()
        if not ext.startswith("."):
            ext = f".{ext}"

        target_dir = set_info.folder_path
        target_dir.mkdir(parents=True, exist_ok=True)

        playlist_file = target_dir / f"{set_info.base_name}{ext}"

        lines = []

        if organize_subfolder:
            # Move raw disc files into a subfolder to prevent EmulationStation duplicate entries
            subfolder_name = f".discs/{set_info.base_name}"
            subfolder_path = target_dir / subfolder_name
            subfolder_path.mkdir(parents=True, exist_ok=True)

            updated_disc_files = []
            for disc_file in set_info.disc_files:
                if disc_file.parent != subfolder_path:
                    dest = subfolder_path / disc_file.name
                    shutil.move(disc_file, dest)
                    updated_disc_files.append(dest)
                else:
                    updated_disc_files.append(disc_file)
            set_info.disc_files = updated_disc_files

            for disc_file in set_info.disc_files:
                # Relative path from target_dir
                rel_path = disc_file.relative_to(target_dir).as_posix()
                lines.append(rel_path)
        else:
            # Flat layout: relative filename on each line
            for disc_file in set_info.disc_files:
                lines.append(disc_file.name)

        # Write playlist text file
        with open(playlist_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        set_info.has_playlist = True
        set_info.playlist_path = playlist_file
        set_info.playlist_extension = ext

        # Cover art linking: ensure playlist has matching box art
        self._sync_cover_art_for_playlist(set_info)

        return playlist_file

    def _sync_cover_art_for_playlist(self, set_info: MultiDiscSet):
        """Ensures the .m3u / .m3a playlist has matching box art in images/ directory."""
        images_dir = set_info.folder_path / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        playlist_art = images_dir / f"{set_info.base_name}-image.png"
        if playlist_art.exists():
            return

        # Check if Disc 1 has cover art
        if set_info.disc_files:
            disc1_stem = set_info.disc_files[0].stem
            disc1_art = images_dir / f"{disc1_stem}-image.png"
            if not disc1_art.exists():
                disc1_art = images_dir / f"{disc1_stem}.png"

            if disc1_art.exists():
                shutil.copy2(disc1_art, playlist_art)
                return

        # Fallback: fetch or generate cover art for the base title
        cover_manager.download_cover_art(
            console_code=set_info.console_code,
            rom_name=f"{set_info.base_name}.zip",
            destination_path=playlist_art
        )

    def parse_playlist_discs(self, playlist_path: Path) -> List[Path]:
        """Reads an existing .m3u or .m3a file and returns paths of all referenced discs."""
        if not playlist_path.exists():
            return []

        base_dir = playlist_path.parent
        disc_paths = []
        try:
            with open(playlist_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line_str = line.strip()
                    if line_str and not line_str.startswith("#"):
                        # Handle forward/backward slashes
                        p = base_dir / Path(line_str)
                        if p.exists():
                            disc_paths.append(p)
                        else:
                            # Try matching just the filename if path shifted
                            loose = base_dir / Path(line_str).name
                            if loose.exists():
                                disc_paths.append(loose)
        except Exception as e:
            print(f"Error parsing playlist {playlist_path}: {e}")

        return disc_paths


# Global M3U manager instance
m3u_manager = M3UManager()
