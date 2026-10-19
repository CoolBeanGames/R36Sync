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

    ROMAN_NUMERALS = {
        "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
        "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10
    }
    TOKEN_RE = r'(\d{1,3}|[a-zA-Z]\b|IV|IX|V?I{1,3})'

    @classmethod
    def extract_disc_info(cls, filename: str) -> Tuple[Optional[str], Optional[str], Any]:
        """
        Extracts (base_title, disc_label, sort_key) from a filename.
        Handles:
          - game_1-disc_1.chd, game_1-disc_2.chd
          - Final Fantasy VII (USA) (Disc 1).chd
          - Resident Evil 2 (USA) (Disc 1) (Leon).chd
          - Metal Gear Solid - Disc 2.iso
          - Shenmue_Disc1.cdi
          - Chrono Cross [Disc 1 of 2].chd
        Returns (None, None, None) if not a multi-disc file.
        """
        stem = Path(filename).stem

        # 1. Bracketed/Parenthesized: (Disc 1), [Disc 1 of 2], (CD 1), etc.
        m = re.search(r'[\(\[]\s*(?:Disc|CD|Disk|Part)[\s_\-]*' + cls.TOKEN_RE + r'(?:\s*of\s*[0-9]+)?[\)\]]', stem, re.IGNORECASE)
        if m:
            token = m.group(1)
            base = re.split(r'[\(\[]\s*(?:Disc|CD|Disk|Part)\b', stem, flags=re.IGNORECASE)[0].strip()
            base = re.sub(r'[\s_\-]+$', '', base).strip()
            if not base:
                base = stem
            sort_key = cls._compute_sort_key(token)
            return base, f"Disc {token}", sort_key

        # 2. Separated by delimiter: -disc_1, _disc2, .disc 1, Disc 1, etc.
        m = re.search(r'(?:[\s_\-\.\(\[])(?:Disc|CD|Disk|Part)[\s_\-]*' + cls.TOKEN_RE + r'(?:\s*of\s*[0-9]+)?(?:[\s_\-\.\)\]]|$)', stem, re.IGNORECASE)
        if m:
            token = m.group(1)
            base = stem[:m.start()].strip()
            base = re.sub(r'[\s_\-]+$', '', base).strip()
            if not base:
                base = stem
            sort_key = cls._compute_sort_key(token)
            return base, f"Disc {token}", sort_key

        return None, None, None

    @classmethod
    def _compute_sort_key(cls, token: str) -> Tuple[int, Any]:
        """Computes a tuple sort key for chronological ordering of discs."""
        token_upper = token.upper()
        if token.isdigit():
            return (0, int(token))
        if token_upper in cls.ROMAN_NUMERALS:
            return (0, cls.ROMAN_NUMERALS[token_upper])
        if len(token) == 1 and token.isalpha():
            return (1, ord(token_upper))
        return (2, token_upper)

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

    def find_existing_playlist(self, directory: Path, base_name: str) -> Optional[Path]:
        """Finds an existing .m3a or .m3u playlist file for the given base name in directory."""
        if not directory.exists() or not directory.is_dir():
            return None
        base_lower = base_name.lower()
        for ext in [".m3a", ".m3u"]:
            p = directory / f"{base_name}{ext}"
            if p.exists():
                return p
        for f in directory.iterdir():
            if f.is_file() and f.suffix.lower() in [".m3a", ".m3u"] and f.stem.lower() == base_lower:
                return f
        return None

    def find_playlists_referencing_disc(self, disc_filename: str, directory: Path) -> List[Path]:
        """Finds all .m3a and .m3u files in directory (or parents) that contain disc_filename."""
        matching = []
        disc_name_lower = Path(disc_filename).name.lower()

        search_dirs = [directory]
        if directory.parent.exists() and (directory.name.lower() in [".discs", "discs"] or (directory.parent != directory and directory.parent.name not in ["", "."])):
            search_dirs.append(directory.parent)

        seen = set()
        for s_dir in search_dirs:
            if not s_dir.exists() or not s_dir.is_dir():
                continue
            for f in s_dir.iterdir():
                if f.is_file() and f.suffix.lower() in [".m3a", ".m3u"]:
                    if f in seen:
                        continue
                    seen.add(f)
                    try:
                        with open(f, "r", encoding="utf-8", errors="replace") as pf:
                            for line in pf:
                                line_s = line.strip()
                                if line_s and not line_s.startswith("#"):
                                    if Path(line_s).name.lower() == disc_name_lower:
                                        matching.append(f)
                                        break
                    except Exception:
                        pass
        return matching

    def add_disc_to_playlist(self, playlist_path: Path, new_disc: Path) -> Path:
        """Adds a new disc file to an existing .m3a or .m3u playlist in sorted order."""
        if not playlist_path.exists():
            raise FileNotFoundError(f"Playlist not found: {playlist_path}")

        existing_lines = []
        with open(playlist_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_str = line.strip()
                if line_str and not line_str.startswith("#"):
                    existing_lines.append(line_str)

        new_disc_name = new_disc.name
        for line in existing_lines:
            if Path(line).name.lower() == new_disc_name.lower():
                return playlist_path

        try:
            rel_posix = new_disc.relative_to(playlist_path.parent).as_posix()
        except ValueError:
            rel_posix = new_disc.name

        uses_subfolders = any("/" in l or "\\" in l for l in existing_lines)
        if uses_subfolders:
            entry_to_add = rel_posix
        else:
            entry_to_add = new_disc.name

        existing_lines.append(entry_to_add)

        def disc_line_sort_key(line_text: str):
            fn = Path(line_text).name
            _, _, s_key = self.extract_disc_info(fn)
            if s_key is not None:
                return s_key
            return (99, fn.lower())

        existing_lines.sort(key=disc_line_sort_key)

        with open(playlist_path, "w", encoding="utf-8") as f:
            f.write("\n".join(existing_lines) + "\n")

        return playlist_path

    def remove_disc_from_playlist(self, playlist_path: Path, removed_disc_name: str) -> Optional[Path]:
        """
        Removes a disc from an existing .m3a or .m3u playlist.
        If 0 discs remain, the playlist is deleted.
        Returns the playlist_path if still active, or None if deleted.
        """
        if not playlist_path.exists():
            return None

        target_name_lower = Path(removed_disc_name).name.lower()

        kept_lines = []
        with open(playlist_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    continue
                if Path(line_str).name.lower() != target_name_lower:
                    kept_lines.append(line_str)

        if len(kept_lines) == 0:
            try:
                playlist_path.unlink()
            except Exception as e:
                print(f"Warning: could not delete empty playlist {playlist_path}: {e}")
            return None
        else:
            with open(playlist_path, "w", encoding="utf-8") as f:
                f.write("\n".join(kept_lines) + "\n")
            return playlist_path

    def handle_disc_file_added(
        self,
        file_path: Path,
        preferred_ext: Optional[str] = None,
        console_code: Optional[str] = None
    ) -> Optional[Path]:
        """
        Live update handler for when a game disc file is added (downloaded or created).
        1.) If game_1-disc_1 is added, check if other discs exist.
        2.) If game_1-disc_2 is added and no playlist exists, creates game_1.m3a.
        3.) If game_1-disc_3 is added and game_1.m3a already exists, adds disc 3 in sorted order.
        """
        if not file_path.exists() or not file_path.is_file():
            return None
        if file_path.suffix.lower() not in DISC_EXTENSIONS:
            return None

        base_name, label, sort_key = self.extract_disc_info(file_path.name)
        if not base_name:
            return None

        target_dir = file_path.parent
        if target_dir.name.lower() in [".discs", "discs"] and target_dir.parent.exists():
            target_dir = target_dir.parent

        ext = preferred_ext or f".{getattr(settings, 'playlist_format', 'm3a')}"
        if not ext.startswith("."):
            ext = f".{ext}"

        # Check if a playlist already exists
        existing_pl = self.find_existing_playlist(target_dir, base_name)
        if existing_pl and existing_pl.exists():
            # Step 3: Playlist already exists! Add new disc to existing playlist
            return self.add_disc_to_playlist(existing_pl, file_path)

        # Step 1 & 2: No playlist exists yet. Scan directory for all discs of this game
        matched_discs = []
        search_dirs = [target_dir]
        for sub in target_dir.iterdir():
            if sub.is_dir() and sub.name.lower() not in ["images", "backups", "saves"]:
                search_dirs.append(sub)

        for s_dir in search_dirs:
            for f in s_dir.iterdir():
                if f.is_file() and f.suffix.lower() in DISC_EXTENSIONS:
                    f_base, f_label, f_sort = self.extract_disc_info(f.name)
                    if f_base and f_base.lower() == base_name.lower():
                        matched_discs.append((f_sort, f_label, f))

        if len(matched_discs) >= 2:
            # Step 2: 2 or more discs found! Create .m3a
            matched_discs.sort(key=lambda x: x[0])
            disc_files = [x[2] for x in matched_discs]
            disc_labels = [x[1] for x in matched_discs]

            if not console_code:
                console_code = target_dir.name

            set_info = MultiDiscSet(
                base_name=base_name,
                console_code=console_code,
                folder_path=target_dir,
                disc_files=disc_files,
                disc_labels=disc_labels,
                has_playlist=False,
                playlist_extension=ext
            )
            return self.create_playlist(set_info, extension=ext)

        # Step 1: Only 1 disc exists so far, do not create playlist yet
        return None

    def handle_disc_file_removed(self, file_path: Path) -> List[Path]:
        """
        Live update handler for when a disc file is deleted.
        4.) If game_1-disc_2 is deleted, deletes the disc 2 entry from the same .m3a/.m3u.
        """
        target_dir = file_path.parent
        matching_playlists = self.find_playlists_referencing_disc(file_path.name, target_dir)

        modified_playlists = []
        for pl in matching_playlists:
            res = self.remove_disc_from_playlist(pl, file_path.name)
            if res:
                modified_playlists.append(res)
        return modified_playlists


# Global M3U manager instance
m3u_manager = M3UManager()
