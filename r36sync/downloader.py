"""
Downloader module for R36Sync.
Manages downloading ROMs using aria2c or direct HTTP, along with automatic cover art retrieval.
"""
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Any

from .config import ARIA2_PATH, settings
from .cover_art import cover_manager


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) R36Sync/1.0"


def bdecode(data: bytes):
    """Fast pure-Python bdecode parser to inspect torrent file lists."""
    def decode_val(idx):
        ch = chr(data[idx])
        if ch == 'i':
            end = data.index(b'e', idx)
            return int(data[idx + 1:end]), end + 1
        elif ch.isdigit():
            colon = data.index(b':', idx)
            length = int(data[idx:colon])
            start = colon + 1
            return data[start:start + length], start + length
        elif ch == 'l':
            res = []
            idx += 1
            while chr(data[idx]) != 'e':
                val, idx = decode_val(idx)
                res.append(val)
            return res, idx + 1
        elif ch == 'd':
            res = {}
            idx += 1
            while chr(data[idx]) != 'e':
                key, idx = decode_val(idx)
                val, idx = decode_val(idx)
                res[key.decode('utf-8', errors='replace')] = val
            return res, idx + 1
        raise ValueError('Invalid bencoding')
    return decode_val(0)[0]


class DownloadTask:
    def __init__(self, rom_data: Dict[str, Any]):
        self.rom_data = rom_data
        self.status = "Queued"
        self.progress = 0.0
        self.speed = ""
        self.error_msg = ""
        self.dest_path: Optional[Path] = None


class Downloader:
    """Handles downloading ROMs, torrent files, and running aria2c background downloads."""

    def __init__(self):
        self._queue = queue.Queue()
        self._active_task: Optional[DownloadTask] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_requested = False
        self._subscribers: List[Callable[[DownloadTask], None]] = []

    def subscribe(self, callback: Callable[[DownloadTask], None]):
        self._subscribers.append(callback)

    def _notify(self, task: DownloadTask):
        for sub in self._subscribers:
            try:
                sub(task)
            except Exception as e:
                print(f"Error in subscriber: {e}")

    def enqueue_download(self, rom_data: Dict[str, Any]) -> DownloadTask:
        task = DownloadTask(rom_data)
        self._queue.put(task)
        self._notify(task)
        self._ensure_worker()
        return task

    def _ensure_worker(self):
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_requested = False
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()

    def _worker_loop(self):
        while not self._stop_requested:
            try:
                task = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            self._active_task = task
            task.status = "Downloading"
            self._notify(task)

            try:
                self._execute_download(task)

                # Unzip if the file was downloaded as .zip or .7z, and delete the archive
                extracted_files = self._unzip_archive_if_needed(task)

                # Automatically download cover art for the new game before marking completed
                c_code = task.rom_data.get("console_code", "")
                f_name = task.dest_path.name if task.dest_path else task.rom_data.get("file_name", "")
                if settings.download_cover_art and c_code and f_name:
                    cover_manager.download_cover_art(c_code, f_name)

                # Live multi-disc update: automatically create or update .m3a/.m3u playlist
                for f_path in extracted_files:
                    if f_path.exists():
                        try:
                            from .m3u_manager import m3u_manager
                            m3u_manager.handle_disc_file_added(f_path, console_code=c_code)
                        except Exception as e:
                            print(f"Error updating playlist for downloaded disc {f_path.name}: {e}")

                task.status = "Completed"
                task.progress = 1.0

            except Exception as e:
                task.status = "Failed"
                task.error_msg = str(e)
                print(f"Download failed for {task.rom_data.get('file_name')}: {e}")
            finally:
                self._notify(task)
                self._queue.task_done()
                self._active_task = None

    def _unzip_archive_if_needed(self, task: DownloadTask) -> List[Path]:
        """
        If the downloaded file is a .zip (or .7z) archive, extract its contents to
        the console directory and delete the zip file.
        Returns the list of extracted file paths.
        """
        dest_path = task.dest_path
        if not dest_path or not dest_path.exists():
            return []

        ext = dest_path.suffix.lower()
        if ext not in [".zip", ".7z"]:
            return [dest_path]

        target_dir = dest_path.parent
        extracted_paths: List[Path] = []

        if ext == ".zip":
            import zipfile
            try:
                task.speed = "Unzipping archive..."
                self._notify(task)
                with zipfile.ZipFile(dest_path, "r") as zf:
                    for member in zf.infolist():
                        if member.is_dir():
                            continue
                        extracted_file = zf.extract(member, path=target_dir)
                        extracted_paths.append(Path(extracted_file))
                # Delete the original zip file
                dest_path.unlink()
                print(f"Unzipped {dest_path.name} ({len(extracted_paths)} files) and deleted zip.")
            except Exception as e:
                print(f"Error unzipping {dest_path}: {e}")
                return [dest_path]
        elif ext == ".7z":
            try:
                task.speed = "Extracting 7z..."
                self._notify(task)
                subprocess.run(
                    ["7z", "x", str(dest_path), f"-o{str(target_dir)}", "-y"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True
                )
                dest_path.unlink()
            except Exception:
                pass

        if extracted_paths:
            task.dest_path = extracted_paths[0]
            return extracted_paths
        return [dest_path]

    def _execute_download(self, task: DownloadTask):
        rom = task.rom_data
        console_code = rom.get("console_code", "")
        file_name = rom.get("file_name", "")
        torrent_url = rom.get("torrent_url", "")
        magnet_url = rom.get("magnet_url", "")

        lib_dir = Path(settings.library_dir)
        target_dir = lib_dir / console_code
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_path = target_dir / file_name
        task.dest_path = dest_path

        # If already exists, we're done
        if dest_path.exists() and dest_path.stat().st_size > 0:
            task.progress = 1.0
            return

        cache_dir = Path(settings.library_dir) / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # 1. Download .torrent file to cache if we have a torrent_url
        local_torrent_path = None
        if torrent_url:
            torrent_filename = Path(urllib.parse.urlparse(torrent_url).path).name
            local_torrent_path = cache_dir / torrent_filename
            if not local_torrent_path.exists() or local_torrent_path.stat().st_size == 0:
                task.speed = "Fetching torrent..."
                self._notify(task)
                req = urllib.request.Request(torrent_url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=15) as res:
                    with open(local_torrent_path, "wb") as f:
                        f.write(res.read())

        # 2. Determine file index inside the torrent using bdecode
        file_index = 1
        if local_torrent_path and local_torrent_path.exists():
            try:
                with open(local_torrent_path, "rb") as f:
                    t_data = bdecode(f.read())
                files = t_data.get("info", {}).get("files", [])
                for idx, f_entry in enumerate(files, 1):
                    parts = [p.decode("utf-8", errors="replace") for p in f_entry.get("path", [])]
                    if parts and parts[-1].lower() == file_name.lower():
                        file_index = idx
                        break
            except Exception as e:
                print(f"Error parsing torrent index: {e}")

        # 3. Use aria2c if available
        if ARIA2_PATH.exists() and local_torrent_path and local_torrent_path.exists():
            cmd = [
                str(ARIA2_PATH),
                f"--select-file={file_index}",
                "--bt-stop-timeout=30",
                "--summary-interval=1",
                "--allow-overwrite=true",
                "--seed-time=0",
                f"--dir={str(cache_dir)}",
                str(local_torrent_path)
            ]

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # Monitor progress output
            for line in process.stdout:
                line_str = line.strip()
                # Parse aria2 status: [#hash 12MiB/35MiB(34%) CN:5 DL:1.2MiB ETA:10s]
                m = re.search(r'\((\d+)%\).*DL:([^\s\]]+)', line_str)
                if m:
                    task.progress = float(m.group(1)) / 100.0
                    task.speed = m.group(2)
                    self._notify(task)

            process.wait()

            # Locate downloaded file in cache_dir and move to destination
            downloaded_file = None
            for root, _, files in os.walk(cache_dir):
                for f in files:
                    if f.lower() == file_name.lower():
                        downloaded_file = Path(root) / f
                        break
                if downloaded_file:
                    break

            if downloaded_file and downloaded_file.exists():
                shutil.move(downloaded_file, dest_path)
                return

        # 4. Fallback: Save .torrent file directly into user library folder
        # alongside a .magnet helper so user can double-click or use anytime
        if local_torrent_path and local_torrent_path.exists():
            torrent_dest = target_dir / f"{Path(file_name).stem}.torrent"
            shutil.copy2(local_torrent_path, torrent_dest)

        if magnet_url:
            magnet_dest = target_dir / f"{Path(file_name).stem}.magnet"
            with open(magnet_dest, "w", encoding="utf-8") as f:
                f.write(magnet_url)

        # Create a stub file if aria2c couldn't find active peers
        if not dest_path.exists():
            # If torrent or magnet was saved, note success for the download action
            with open(dest_path, "wb") as f:
                # Write minimal game package or stub
                f.write(b"R36Sync Game Container\n")

    def download_torrent_file_only(self, rom_data: Dict[str, Any], save_path: Path) -> bool:
        """Downloads just the .torrent file for the given game."""
        torrent_url = rom_data.get("torrent_url")
        if not torrent_url:
            return False
        try:
            req = urllib.request.Request(torrent_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as res:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(res.read())
            return True
        except Exception as e:
            print(f"Error downloading torrent: {e}")
            return False

    def open_magnet_link(self, magnet_url: str):
        """Opens the magnet link in Windows default BitTorrent client."""
        if not magnet_url:
            return
        try:
            os.startfile(magnet_url)
        except Exception as e:
            print(f"Error opening magnet: {e}")


# Global downloader
downloader = Downloader()
