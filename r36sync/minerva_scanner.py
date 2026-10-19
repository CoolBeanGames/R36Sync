"""
Minerva Archive Scanner module for R36Sync.
Fetches directory listings from https://minerva-archive.org/ and indexes ROMs into the database.
"""
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Any
from .config import CONSOLES, ConsoleDef
from .database import db, clean_game_title


MINERVA_BASE_URL = "https://minerva-archive.org"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) R36Sync/1.0"


class MinervaScanner:
    """Scans Minerva Archive directory listings and builds the local database."""

    def __init__(self):
        self._stop_requested = False
        self._is_scanning = False
        self._thread: Optional[threading.Thread] = None

    @property
    def is_scanning(self) -> bool:
        return self._is_scanning

    def stop(self):
        """Requests scanner to stop."""
        self._stop_requested = True

    def scan_all_consoles_async(
        self,
        on_progress: Optional[Callable[[str, int, int, str], None]] = None,
        on_complete: Optional[Callable[[int], None]] = None,
        on_error: Optional[Callable[[str], None]] = None
    ):
        """Starts background scanning of all configured consoles."""
        if self._is_scanning:
            return

        def run():
            self._is_scanning = True
            self._stop_requested = False
            total_added = 0
            try:
                consoles_list = list(CONSOLES.values())
                total_consoles = len(consoles_list)

                for idx, console_def in enumerate(consoles_list, 1):
                    if self._stop_requested:
                        break

                    if on_progress:
                        on_progress(console_def.code, idx, total_consoles, f"Scanning {console_def.display_name}...")

                    count = self.scan_console(console_def)
                    total_added += count

                    if on_progress:
                        on_progress(
                            console_def.code, idx, total_consoles,
                            f"Indexed {count:,} games for {console_def.display_name}"
                        )
                    # Brief polite pause between console directories
                    time.sleep(0.3)

                if on_complete:
                    on_complete(total_added)
            except Exception as e:
                if on_error:
                    on_error(str(e))
            finally:
                self._is_scanning = False

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def scan_console(self, console_def: ConsoleDef) -> int:
        """Scans a single console directory and any extra paths from Minerva Archive."""
        total = self._scan_single_path(
            console_def,
            console_def.minerva_path,
            console_def.torrent_prefix,
            console_def.minerva_group
        )

        for extra_path in getattr(console_def, "extra_paths", []):
            extra_torrent = ""
            if "PS one Classics" in extra_path:
                extra_torrent = "Minerva_Myrient - No-Intro - Sony - PlayStation (PS one Classics) (PSN).torrent"
            extra_group = "No-Intro" if extra_path.startswith("No-Intro") else console_def.minerva_group
            total += self._scan_single_path(console_def, extra_path, extra_torrent, extra_group)

        return total

    def _scan_single_path(self, console_def: ConsoleDef, path: str, torrent_prefix: str, group_name: str) -> int:
        """Scans an individual directory path on Minerva Archive."""
        quoted_path = urllib.parse.quote(path)
        url = f"{MINERVA_BASE_URL}/browse/./{quoted_path}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                html = response.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return 0

        # Extract folder magnet link if present
        folder_magnet = ""
        magnet_match = re.search(r"downloadMagnet\(\s*['\"]([^'\"]+)['\"]\s*\)", html)
        if magnet_match:
            folder_magnet = magnet_match.group(1).replace("&amp;", "&")

        # Standard torrent URL on Minerva
        torrent_url = ""
        if torrent_prefix:
            quoted_torrent = urllib.parse.quote(torrent_prefix)
            torrent_url = f"{MINERVA_BASE_URL}/assets/Minerva_Myrient_v0.3/{quoted_torrent}"

        # Pattern matching directory entry rows
        entry_pattern = re.compile(
            r'<div class="entry" data-name="([^"]+)">\s*'
            r'<a href="(/rom\?id=(\d+))"[^>]*>([^<]+)</a>\s*'
            r'<span>([^<]+)</span>',
            re.MULTILINE
        )

        roms_to_insert = []
        import html as html_module

        found_count = 0
        for match in entry_pattern.finditer(html):
            raw_data_name, rom_path, rom_id, file_name, size_str = match.groups()
            found_count += 1

            file_name = html_module.unescape(file_name.strip())
            title = clean_game_title(file_name)

            roms_to_insert.append({
                "minerva_id": rom_id,
                "title": title,
                "clean_title": title,
                "file_name": file_name,
                "console_code": console_def.code,
                "console_name": console_def.display_name,
                "group_name": group_name,
                "size_str": size_str.strip(),
                "torrent_url": torrent_url,
                "magnet_url": folder_magnet,
                "rom_url": f"{MINERVA_BASE_URL}{rom_path}",
                "torrent_file_idx": 0
            })

            if len(roms_to_insert) >= 500:
                db.upsert_roms(roms_to_insert)
                roms_to_insert.clear()

        if roms_to_insert:
            db.upsert_roms(roms_to_insert)

        return found_count


# Global scanner instance
scanner = MinervaScanner()
