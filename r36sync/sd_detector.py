"""
SD Card Detector module for R36Sync.
Discovers and validates SD cards formatted for the R36S emulation handheld (ArkOS EASYROMS).
"""
import ctypes
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from .config import CONSOLES


# Characteristic console directories on ArkOS for R36S
SIGNATURE_FOLDERS = {
    "gb", "gbc", "gba", "nes", "snes", "megadrive", "n64",
    "psx", "arcade", "bios", "nds", "gamegear", "mastersystem",
    "pcengine", "dreamcast", "neogeo", "mame", "sega32x"
}

KNOWN_VOLUME_LABELS = {"EASYROMS", "ARKOS", "ROMS", "R36S", "RETRO"}


@dataclass
class SDCardInfo:
    drive_letter: str                 # e.g. "E:\\"
    volume_label: str                 # e.g. "EASYROMS"
    filesystem: str                   # e.g. "exFAT" or "FAT32"
    is_removable: bool
    free_bytes: int
    total_bytes: int
    roms_root: Path                   # Directory where console folders live
    detected_folders: List[str]       # Matching console folders found
    match_score: int                  # 0 to 100 confidence
    is_valid_r36s: bool

    @property
    def free_gb(self) -> float:
        return self.free_bytes / (1024 ** 3)

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024 ** 3)


class SDDetector:
    """Detects and validates connected R36S SD cards."""

    @staticmethod
    def get_logical_drives() -> List[str]:
        """Returns list of active drive paths (e.g. ['C:\\', 'E:\\'])."""
        drives = []
        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                if bitmask & 1:
                    drives.append(f"{letter}:\\")
                bitmask >>= 1
        except Exception:
            # Fallback for non-ctypes environments
            for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
                path = f"{letter}:\\"
                if os.path.exists(path):
                    drives.append(path)
        return drives

    @staticmethod
    def get_volume_info(drive_path: str) -> Tuple[str, str, bool]:
        """Returns (volume_name, filesystem, is_removable)."""
        label = ""
        fs = ""
        is_removable = False
        try:
            buf = ctypes.create_unicode_buffer(261)
            fs_buf = ctypes.create_unicode_buffer(261)
            ctypes.windll.kernel32.GetVolumeInformationW(
                drive_path, buf, 260, None, None, None, fs_buf, 260
            )
            label = buf.value
            fs = fs_buf.value
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
            is_removable = (drive_type == 2)  # DRIVE_REMOVABLE = 2
        except Exception:
            pass
        return label, fs, is_removable

    @classmethod
    def check_folder_structure(cls, root_path: Path) -> Tuple[Path, List[str], int]:
        """
        Examines directory structure for R36S console folders.
        Returns (roms_root, matched_folders, score).
        """
        candidates = [
            root_path,
            root_path / "roms",
            root_path / "EASYROMS",
        ]

        best_root = root_path
        best_matches = []
        best_score = 0

        for cand in candidates:
            if not cand.exists() or not cand.is_dir():
                continue

            try:
                subdirs = {d.name.lower() for d in cand.iterdir() if d.is_dir()}
            except Exception:
                continue

            matches = list(subdirs.intersection(SIGNATURE_FOLDERS))
            score = len(matches) * 10
            if score > best_score:
                best_score = score
                best_matches = matches
                best_root = cand

        return best_root, sorted(best_matches), min(best_score, 100)

    @classmethod
    def inspect_drive(cls, drive_path: str) -> Optional[SDCardInfo]:
        """Inspects a single drive to evaluate if it's an R36S SD card."""
        root = Path(drive_path)
        if not root.exists():
            return None

        label, fs, is_removable = cls.get_volume_info(drive_path)

        try:
            usage = shutil.disk_usage(drive_path)
            free_bytes = usage.free
            total_bytes = usage.total
        except Exception:
            free_bytes = 0
            total_bytes = 0

        roms_root, matches, score = cls.check_folder_structure(root)

        # Bonus score if label matches EASYROMS/ARKOS
        if label.upper() in KNOWN_VOLUME_LABELS:
            score = min(score + 40, 100)

        # Valid R36S requires either matching label OR at least 3 signature folders
        is_valid = (score >= 30) or (label.upper() in KNOWN_VOLUME_LABELS and len(matches) >= 1)

        return SDCardInfo(
            drive_letter=drive_path,
            volume_label=label,
            filesystem=fs,
            is_removable=is_removable,
            free_bytes=free_bytes,
            total_bytes=total_bytes,
            roms_root=roms_root,
            detected_folders=matches,
            match_score=score,
            is_valid_r36s=is_valid
        )

    @classmethod
    def find_r36s_sd_cards(cls) -> List[SDCardInfo]:
        """Scans all drives and returns detected R36S SD cards sorted by match score."""
        detected = []
        for drive in cls.get_logical_drives():
            info = cls.inspect_drive(drive)
            if info and info.is_valid_r36s:
                detected.append(info)

        detected.sort(key=lambda x: x.match_score, reverse=True)
        return detected

    @classmethod
    def create_r36s_folder_structure(cls, target_root: Path) -> List[str]:
        """Creates the full standard R36S / ArkOS folder hierarchy on a given drive/folder."""
        created = []
        target_root.mkdir(parents=True, exist_ok=True)
        for folder_name in sorted(SIGNATURE_FOLDERS):
            folder_path = target_root / folder_name
            folder_path.mkdir(exist_ok=True)
            # Create nested images directory for box art
            (folder_path / "images").mkdir(exist_ok=True)
            created.append(folder_name)
        return created


# Global detector instance
sd_detector = SDDetector()
