"""
Library Watcher module for R36Sync.
Monitors the local library directory in real time for added, modified, or deleted ROM/disc files.
Triggers live .m3a/.m3u playlist updates and notifies GUI views to refresh automatically.
"""
import os
from pathlib import Path
import threading
import time
from typing import Callable, List, Optional, Set

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent, FileMovedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object

from .config import settings
from .m3u_manager import m3u_manager, DISC_EXTENSIONS


IGNORED_DIR_NAMES = {
    "images", "backups", "saves", ".cache", ".git", ".aria2", "__pycache__"
}

IGNORED_EXTENSIONS = {
    ".aria2", ".tmp", ".crdownload", ".part", ".swp", ".lock"
}


class _LibraryEventHandler(FileSystemEventHandler):
    """Internal Watchdog event handler that feeds raw events to LibraryWatcher."""

    def __init__(self, watcher: "LibraryWatcher"):
        super().__init__()
        self.watcher = watcher

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            self.watcher._queue_change("created", event.src_path)

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory:
            self.watcher._queue_change("deleted", event.src_path)

    def on_moved(self, event: FileMovedEvent):
        if not event.is_directory:
            self.watcher._queue_change("deleted", event.src_path)
            self.watcher._queue_change("created", event.dest_path)


class LibraryWatcher:
    """
    Watches the user's Library directory for file additions, moves, and deletions.
    Automatically keeps multi-disc .m3a/.m3u playlists up to date and notifies GUI views.
    """

    def __init__(self, debounce_delay: float = 0.35):
        self.debounce_delay = debounce_delay
        self._observer: Optional[Observer] = None
        self._current_path: Optional[str] = None
        self._subscribers: List[Callable[[], None]] = []

        self._pending_lock = threading.Lock()
        self._pending_created: Set[str] = set()
        self._pending_deleted: Set[str] = set()
        self._timer: Optional[threading.Timer] = None
        self._is_running = False

    def subscribe(self, callback: Callable[[], None]):
        """Subscribes a callback to be called whenever library files change."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[], None]):
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify_subscribers(self):
        for sub in list(self._subscribers):
            try:
                sub()
            except Exception as e:
                print(f"Error in LibraryWatcher subscriber: {e}")

    def start(self, watch_dir: Optional[str] = None):
        """Starts monitoring the specified directory (or settings.library_dir)."""
        if not WATCHDOG_AVAILABLE:
            print("Note: watchdog not installed, live filesystem watching disabled.")
            return

        target_dir = str(watch_dir or settings.library_dir)
        p = Path(target_dir)
        if not p.exists():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"LibraryWatcher: could not create directory {target_dir}: {e}")
                return

        self.stop()

        try:
            handler = _LibraryEventHandler(self)
            self._observer = Observer()
            self._observer.schedule(handler, target_dir, recursive=True)
            self._observer.daemon = True
            self._observer.start()
            self._current_path = target_dir
            self._is_running = True
        except Exception as e:
            print(f"LibraryWatcher: failed to start watching {target_dir}: {e}")
            self._observer = None

    def stop(self):
        """Stops the active watcher observer."""
        if self._timer:
            self._timer.cancel()
            self._timer = None

        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=1.0)
            except Exception:
                pass
            self._observer = None

        self._is_running = False
        self._current_path = None

    def update_watch_directory(self, new_dir: str):
        """Restarts watcher if the target library directory changed."""
        if str(new_dir) != str(self._current_path):
            self.start(new_dir)

    def _queue_change(self, change_type: str, file_path_str: str):
        """Queues a file change event with debouncing to avoid disk write spikes."""
        p = Path(file_path_str)

        # Ignore non-ROM or system directories
        parts_lower = [part.lower() for part in p.parts]
        for ignored in IGNORED_DIR_NAMES:
            if ignored in parts_lower:
                return

        ext = p.suffix.lower()
        if ext in IGNORED_EXTENSIONS:
            return

        # Playlists themselves should not trigger disc addition handlers
        # but should trigger UI refresh
        with self._pending_lock:
            if change_type == "created":
                self._pending_created.add(str(p.resolve()))
                self._pending_deleted.discard(str(p.resolve()))
            elif change_type == "deleted":
                self._pending_deleted.add(str(p.resolve()))
                self._pending_created.discard(str(p.resolve()))

            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_delay, self._process_pending_changes)
            self._timer.daemon = True
            self._timer.start()

    def _process_pending_changes(self):
        """Processes collected created and deleted files in batch."""
        with self._pending_lock:
            created_list = list(self._pending_created)
            deleted_list = list(self._pending_deleted)
            self._pending_created.clear()
            self._pending_deleted.clear()
            self._timer = None

        changed = False

        # Process deleted files first
        for path_str in deleted_list:
            p = Path(path_str)
            ext = p.suffix.lower()
            if ext in DISC_EXTENSIONS:
                try:
                    mods = m3u_manager.handle_disc_file_removed(p)
                    if mods:
                        changed = True
                except Exception as e:
                    print(f"Error handling disc removal for {p.name}: {e}")
            elif ext in [".m3u", ".m3a"]:
                changed = True
            else:
                changed = True

        # Process created files
        for path_str in created_list:
            p = Path(path_str)
            if not p.exists():
                continue
            ext = p.suffix.lower()
            if ext in DISC_EXTENSIONS:
                try:
                    res = m3u_manager.handle_disc_file_added(p)
                    if res:
                        changed = True
                except Exception as e:
                    print(f"Error handling disc addition for {p.name}: {e}")
            elif ext in [".m3u", ".m3a"]:
                changed = True
            else:
                changed = True

        # Notify UI if anything changed
        if changed or created_list or deleted_list:
            self._notify_subscribers()


# Global library watcher instance
library_watcher = LibraryWatcher()
