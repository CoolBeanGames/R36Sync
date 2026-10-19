"""
Main Application Window for R36Sync.
Integrates Library, Download, Handheld/SD Card, Minerva Database, and Settings tabs.
"""
import threading
from typing import Optional
import customtkinter as ctk

from ..config import settings
from ..database import db
from ..library_watcher import library_watcher
from ..minerva_scanner import scanner
from .library_view import LibraryView
from .browse_view import BrowseView
from .download_view import DownloadView
from .handheld_view import HandheldView
from .scanner_view import ScannerView
from .settings_view import SettingsView


class R36SyncApp(ctk.CTk):
    """Main window for R36Sync."""

    def __init__(self):
        super().__init__()

        # Appearance mode
        ctk.set_appearance_mode(settings.theme.lower())
        ctk.set_default_color_theme("blue")

        self.title("R36Sync - Handheld Game Manager & Minerva Archive Sync")
        self.geometry("1100x740")
        self.minsize(920, 600)

        self._create_layout()

        # Handle clean exit
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Startup triggers
        self.after(300, self._on_startup)

    def _create_layout(self):
        # 1. Top Global Notification Banner
        self.banner_frame = ctk.CTkFrame(self, fg_color="#1e3a8a", height=32, corner_radius=0)
        self.banner_frame.pack(fill="x")
        self.banner_frame.pack_propagate(False)

        self.banner_lbl = ctk.CTkLabel(
            self.banner_frame,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#93c5fd"
        )
        self.banner_lbl.pack(side="left", padx=16)

        self.banner_progress = ctk.CTkProgressBar(self.banner_frame, width=160, height=8)
        self.banner_progress.pack(side="right", padx=16)
        self.banner_progress.set(0)

        # Initially hidden if not scanning
        self.banner_frame.pack_forget()

        # 2. Main Tab View
        self.tabview = ctk.CTkTabview(
            self,
            corner_radius=10,
            fg_color=("gray95", "gray14")
        )
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(4, 10))

        # Create Tabs
        self.tab_library = self.tabview.add("Library")
        self.tab_browse = self.tabview.add("Browse")
        self.tab_download = self.tabview.add("Download")
        self.tab_handheld = self.tabview.add("SD Card & Sync")
        self.tab_scanner = self.tabview.add("Minerva Database")
        self.tab_settings = self.tabview.add("Settings")

        # Style tab buttons
        self.tabview._segmented_button.configure(
            font=ctk.CTkFont(size=14, weight="bold"),
            height=36
        )

        # Instantiate View Frames inside Tabs
        self.library_view = LibraryView(
            self.tab_library,
            on_switch_to_download=self.switch_to_download_tab,
            on_switch_to_browse=self.switch_to_browse_tab
        )
        self.library_view.pack(fill="both", expand=True)

        self.browse_view = BrowseView(
            self.tab_browse,
            on_download_completed=self.on_download_completed
        )
        self.browse_view.pack(fill="both", expand=True)

        self.download_view = DownloadView(
            self.tab_download,
            on_download_completed=self.on_download_completed,
            on_switch_to_browse=self.switch_to_browse_tab
        )
        self.download_view.pack(fill="both", expand=True)

        self.handheld_view = HandheldView(
            self.tab_handheld,
            on_sync_triggered=self.library_view.execute_sync
        )
        self.handheld_view.pack(fill="both", expand=True)

        self.scanner_view = ScannerView(
            self.tab_scanner,
            on_db_updated=self.on_minerva_db_updated
        )
        self.scanner_view.pack(fill="both", expand=True)

        self.settings_view = SettingsView(
            self.tab_settings,
            on_settings_changed=self.on_settings_updated
        )
        self.settings_view.pack(fill="both", expand=True)

    def switch_to_download_tab(self):
        """Switches UI to the Download tab."""
        self.tabview.set("Download")

    def switch_to_browse_tab(self):
        """Switches UI to the Browse tab."""
        self.tabview.set("Browse")

    def on_download_completed(self):
        """Called when a game download finishes; refreshes library and browse."""
        self.library_view.refresh_library()
        self.browse_view.render_systems()

    def on_minerva_db_updated(self):
        """Called when Minerva database scan adds games."""
        self.browse_view.render_systems()
        self.download_view._run_search()
        self.download_view.update_db_stat()
        self.scanner_view.refresh_stats()

    def on_settings_updated(self):
        """Called when user changes settings."""
        library_watcher.update_watch_directory(settings.library_dir)
        self.library_view.refresh_library()
        self.handheld_view.refresh()

    def on_library_fs_changed(self):
        """Triggered by background LibraryWatcher when any library file or playlist changes."""
        def schedule_update():
            if hasattr(self, "_pending_fs_timer") and self._pending_fs_timer:
                try:
                    self.after_cancel(self._pending_fs_timer)
                except Exception:
                    pass
            self._pending_fs_timer = self.after(400, self._handle_library_fs_update)

        self.after(0, schedule_update)

    def _handle_library_fs_update(self):
        self._pending_fs_timer = None
        try:
            curr_tab = self.tabview.get()
            if curr_tab == "Library":
                self.library_view.refresh_library()
            elif curr_tab == "Browse":
                self.browse_view.render_systems()
            elif curr_tab == "SD Card & Sync":
                self.handheld_view.refresh()
            else:
                self.library_view.refresh_library()
        except Exception as e:
            print(f"Error updating views after fs change: {e}")

    def show_banner(self, text: str, progress: float = 0.0):
        self.banner_frame.pack(fill="x", before=self.tabview)
        self.banner_lbl.configure(text=text)
        self.banner_progress.set(progress)

    def hide_banner(self):
        self.banner_frame.pack_forget()

    def _on_startup(self):
        """Runs startup checks, scans library, and triggers Minerva Archive initial scan."""
        # 1. Populate Library immediately from disk
        self.library_view.refresh_library()
        self.handheld_view.refresh()

        # 2. Start live filesystem monitoring
        library_watcher.subscribe(self.on_library_fs_changed)
        library_watcher.start(settings.library_dir)

        # 3. Check if Minerva Archive should be scanned
        total_cached = db.get_total_rom_count()

        if total_cached == 0:
            # First launch: database is empty, scan to populate initial catalog
            self.show_banner("Scanning https://minerva-archive.org/ to build initial database...", 0.05)

            def on_progress(code, cur, total, msg):
                frac = cur / max(total, 1)
                self.after(0, lambda: [
                    self.show_banner(f"Scanning Minerva Archive: {msg} ({int(frac * 100)}%)", frac),
                    self.scanner_view.refresh_stats(),
                    self.download_view.update_db_stat()
                ])

            def on_complete(total_added):
                self.after(0, lambda: [
                    self.show_banner(f"Minerva Archive database ready! {db.get_total_rom_count():,} games stored.", 1.0),
                    self.on_minerva_db_updated(),
                    self.after(4000, self.hide_banner)
                ])

            def on_error(err):
                self.after(0, lambda: [
                    self.show_banner(f"Minerva Archive scan note: {err}", 1.0),
                    self.after(5000, self.hide_banner)
                ])

            scanner.scan_all_consoles_async(
                on_progress=on_progress,
                on_complete=on_complete,
                on_error=on_error
            )
        elif settings.auto_scan_on_launch:
            # User opted into checking for updates on launch
            self.show_banner("Checking Minerva Archive for updates...", 0.05)

            def on_progress(code, cur, total, msg):
                frac = cur / max(total, 1)
                self.after(0, lambda: [
                    self.show_banner(f"Updating Minerva Archive: {msg} ({int(frac * 100)}%)", frac),
                    self.scanner_view.refresh_stats(),
                    self.download_view.update_db_stat()
                ])

            def on_complete(total_added):
                self.after(0, lambda: [
                    self.show_banner(f"Minerva Archive catalog updated! {db.get_total_rom_count():,} games stored.", 1.0),
                    self.on_minerva_db_updated(),
                    self.after(4000, self.hide_banner)
                ])

            def on_error(err):
                self.after(0, lambda: [
                    self.show_banner(f"Minerva Archive note: {err}", 1.0),
                    self.after(5000, self.hide_banner)
                ])

            scanner.scan_all_consoles_async(
                on_progress=on_progress,
                on_complete=on_complete,
                on_error=on_error
            )
        else:
            # Instant startup using existing stored database
            self.download_view._run_search()
            self.download_view.update_db_stat()

    def _on_close(self):
        """Clean shutdown handler."""
        try:
            library_watcher.stop()
        except Exception:
            pass
        self.destroy()
