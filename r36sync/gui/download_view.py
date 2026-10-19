"""
Download View for R36Sync.
Searches the stored SQLite database of Minerva Archive ROMs and provides 1-click downloading
directly to the local library with automatic cover art fetching.
"""
import os
from pathlib import Path
import threading
from typing import Dict, List, Optional, Any
import customtkinter as ctk

from ..config import CONSOLES, settings
from ..database import db
from ..downloader import downloader, DownloadTask


PAGE_SIZE = 50


class DownloadView(ctk.CTkFrame):
    """Download Tab: Instant search of stored Minerva database and library download manager."""

    def __init__(self, master, on_download_completed=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_download_completed = on_download_completed
        self.current_page = 0
        self.total_results = 0
        self.current_results: List[Dict[str, Any]] = []
        self.selected_console_code: Optional[str] = None
        self._search_timer: Optional[threading.Timer] = None

        self._create_ui()
        # Listen to download queue updates
        downloader.subscribe(self._on_download_task_update)

    def _create_ui(self):
        # 1. Header Frame
        header = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
        header.pack(fill="x", padx=12, pady=(10, 6))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x", padx=12, pady=(8, 4))

        ctk.CTkLabel(
            title_row,
            text="Minerva Archive Catalog",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")

        self.db_stat_badge = ctk.CTkLabel(
            title_row,
            text="Database: 0 games cached",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("gray75", "gray25"),
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.db_stat_badge.pack(side="right")

        # Search Controls Row
        search_row = ctk.CTkFrame(header, fg_color="transparent")
        search_row.pack(fill="x", padx=12, pady=(4, 10))

        self.search_entry = ctk.CTkEntry(
            search_row,
            placeholder_text="Search stored archive (e.g. Mario, Pokemon, Zelda)...",
            width=360,
            height=34
        )
        self.search_entry.pack(side="left", padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", self._on_search_key)

        self.console_dropdown = ctk.CTkOptionMenu(
            search_row,
            values=["All Consoles"] + [c.display_name for c in CONSOLES.values()],
            command=self._on_console_changed,
            width=230,
            height=34
        )
        self.console_dropdown.pack(side="left", padx=4)

        self.clear_btn = ctk.CTkButton(
            search_row,
            text="Clear",
            width=65,
            height=34,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self.clear_search
        )
        self.clear_btn.pack(side="left", padx=4)

        # 2. Results Info & Pagination Bar
        nav_row = ctk.CTkFrame(self, fg_color="transparent")
        nav_row.pack(fill="x", padx=12, pady=(4, 4))

        self.results_info_lbl = ctk.CTkLabel(
            nav_row,
            text="0 results found in stored database",
            font=ctk.CTkFont(size=12),
            text_color="gray60"
        )
        self.results_info_lbl.pack(side="left", padx=4)

        # Pagination
        self.next_btn = ctk.CTkButton(
            nav_row,
            text="Next >",
            width=70,
            height=26,
            command=self.next_page
        )
        self.next_btn.pack(side="right", padx=4)

        self.page_lbl = ctk.CTkLabel(
            nav_row,
            text="Page 1",
            font=ctk.CTkFont(size=12)
        )
        self.page_lbl.pack(side="right", padx=8)

        self.prev_btn = ctk.CTkButton(
            nav_row,
            text="< Prev",
            width=70,
            height=26,
            command=self.prev_page
        )
        self.prev_btn.pack(side="right", padx=4)

        # 3. Active Download Banner
        self.download_banner = ctk.CTkFrame(self, corner_radius=8, fg_color=("gray80", "gray20"))
        self.download_banner.pack(fill="x", padx=12, pady=(0, 6))
        self.download_banner.pack_forget()  # Hidden by default

        self.dl_title_lbl = ctk.CTkLabel(
            self.download_banner,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        )
        self.dl_title_lbl.pack(side="left", padx=10, pady=6)

        self.dl_progress = ctk.CTkProgressBar(self.download_banner, width=200)
        self.dl_progress.pack(side="left", padx=10, pady=6)
        self.dl_progress.set(0)

        self.dl_speed_lbl = ctk.CTkLabel(
            self.download_banner,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray60"
        )
        self.dl_speed_lbl.pack(side="left", padx=6, pady=6)

        # 4. Results Scrollable Frame
        self.scroll_frame = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.scroll_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    def update_db_stat(self):
        """Updates the total cached games badge."""
        total = db.get_total_rom_count()
        self.db_stat_badge.configure(
            text=f"Database: {total:,} games stored"
        )

    def _on_search_key(self, event):
        """Debounces search input to query local database efficiently."""
        if self._search_timer:
            self._search_timer.cancel()
        self._search_timer = threading.Timer(0.15, self._run_search)
        self._search_timer.start()

    def _on_console_changed(self, selection: str):
        if selection == "All Consoles":
            self.selected_console_code = None
        else:
            for code, c_def in CONSOLES.items():
                if c_def.display_name == selection:
                    self.selected_console_code = code
                    break
        self.current_page = 0
        self._run_search()

    def clear_search(self):
        self.search_entry.delete(0, "end")
        self.current_page = 0
        self._run_search()

    def next_page(self):
        if (self.current_page + 1) * PAGE_SIZE < self.total_results:
            self.current_page += 1
            self._run_search()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._run_search()

    def _run_search(self):
        """Executes search directly against local SQLite DB."""
        query = self.search_entry.get().strip()
        offset = self.current_page * PAGE_SIZE

        self.total_results = db.count_search_results(query, self.selected_console_code)
        self.current_results = db.search_roms(query, self.selected_console_code, limit=PAGE_SIZE, offset=offset)

        self.after(0, self._render_results)

    def _render_results(self):
        self.update_db_stat()

        total_pages = max(1, (self.total_results + PAGE_SIZE - 1) // PAGE_SIZE)
        cur_p = self.current_page + 1
        self.page_lbl.configure(text=f"Page {cur_p} of {total_pages}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_btn.configure(state="normal" if cur_p < total_pages else "disabled")

        self.results_info_lbl.configure(
            text=f"Found {self.total_results:,} game(s) in stored database"
        )

        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        if not self.current_results:
            empty_box = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            empty_box.pack(pady=50)

            total_db = db.get_total_rom_count()
            if total_db == 0:
                msg = "The stored Minerva Archive database is currently empty."
                sub_msg = "Minerva Archive will automatically scan and index ROMs on launch,\nor you can visit the Minerva Database tab to scan now."
            else:
                msg = "No games matched your search criteria."
                sub_msg = "Try searching for a different title or select 'All Consoles'."

            ctk.CTkLabel(
                empty_box,
                text=msg,
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="gray60"
            ).pack(pady=4)

            ctk.CTkLabel(
                empty_box,
                text=sub_msg,
                font=ctk.CTkFont(size=13),
                text_color="gray50"
            ).pack(pady=4)
            return

        for rom in self.current_results:
            self._render_rom_row(rom)

    def _render_rom_row(self, rom: Dict[str, Any]):
        row = ctk.CTkFrame(self.scroll_frame, corner_radius=8, fg_color=("gray90", "gray18"))
        row.pack(fill="x", padx=4, pady=3)

        info_box = ctk.CTkFrame(row, fg_color="transparent")
        info_box.pack(side="left", fill="both", expand=True, padx=12, pady=6)

        title = rom.get("title", rom.get("file_name", ""))
        ctk.CTkLabel(
            info_box,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        ).pack(fill="x")

        console_name = rom.get("console_name", "")
        size_str = rom.get("size_str", "")
        ctk.CTkLabel(
            info_box,
            text=f"{console_name} • {size_str}",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            anchor="w"
        ).pack(fill="x")

        # Check if already in local library
        lib_file = Path(settings.library_dir) / rom.get("console_code", "") / rom.get("file_name", "")
        is_downloaded = lib_file.exists() and lib_file.stat().st_size > 0

        # Action Buttons
        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=10, pady=6)

        if is_downloaded:
            badge = ctk.CTkLabel(
                btn_frame,
                text="In Library",
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color=("#d1fae5", "#064e3b"),
                text_color=("#065f46", "#6ee7b7"),
                corner_radius=6,
                padx=10,
                pady=4
            )
            badge.pack(side="left", padx=4)
        else:
            dl_btn = ctk.CTkButton(
                btn_frame,
                text="Download to Library",
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#3b82f6",
                hover_color="#2563eb",
                height=30,
                command=lambda r=rom: self.download_game(r)
            )
            dl_btn.pack(side="left", padx=4)

        # Options dropdown or secondary button
        opt_btn = ctk.CTkButton(
            btn_frame,
            text="•••",
            width=32,
            height=30,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=lambda r=rom: self._show_rom_options(r)
        )
        opt_btn.pack(side="left", padx=2)

    def download_game(self, rom: Dict[str, Any]):
        """Queues game for download and updates UI."""
        downloader.enqueue_download(rom)

    def _show_rom_options(self, rom: Dict[str, Any]):
        """Displays modal with additional options (Magnet link, Torrent file, Minerva page)."""
        top = ctk.CTkToplevel(self)
        top.title(rom.get("title", "Game Options"))
        top.geometry("450x260")
        top.transient(self.winfo_toplevel())
        top.grab_set()

        ctk.CTkLabel(
            top,
            text=rom.get("title", ""),
            font=ctk.CTkFont(size=14, weight="bold"),
            wraplength=400
        ).pack(pady=(16, 6))

        ctk.CTkLabel(
            top,
            text=f"Filename: {rom.get('file_name')}\nConsole: {rom.get('console_name')} • Size: {rom.get('size_str')}",
            font=ctk.CTkFont(size=12),
            text_color="gray60"
        ).pack(pady=4)

        btn_box = ctk.CTkFrame(top, fg_color="transparent")
        btn_box.pack(pady=12)

        # 1. Download Torrent File
        def save_torrent():
            cache_dir = Path(settings.library_dir) / ".cache"
            fname = Path(rom.get("file_name", "game")).stem + ".torrent"
            save_path = cache_dir / fname
            success = downloader.download_torrent_file_only(rom, save_path)
            if success:
                try:
                    os.startfile(str(cache_dir))
                except Exception:
                    pass
            top.destroy()

        ctk.CTkButton(
            btn_box,
            text="Save .torrent File",
            width=160,
            command=save_torrent
        ).pack(pady=4)

        # 2. Open Magnet Link
        def open_magnet():
            downloader.open_magnet_link(rom.get("magnet_url", ""))
            top.destroy()

        ctk.CTkButton(
            btn_box,
            text="Open Magnet Link",
            width=160,
            command=open_magnet
        ).pack(pady=4)

        # 3. View on Minerva Archive
        def open_url():
            import webbrowser
            url = rom.get("rom_url") or "https://minerva-archive.org"
            webbrowser.open(url)
            top.destroy()

        ctk.CTkButton(
            btn_box,
            text="Open Minerva Page",
            width=160,
            fg_color=("gray75", "gray28"),
            command=open_url
        ).pack(pady=4)

    def _on_download_task_update(self, task: DownloadTask):
        """Callback from background downloader."""
        def update():
            if task.status == "Downloading":
                self.download_banner.pack(fill="x", padx=12, pady=(0, 6))
                f_name = task.rom_data.get("file_name", "")
                self.dl_title_lbl.configure(text=f"Downloading: {f_name[:30]}...")
                self.dl_progress.set(task.progress)
                self.dl_speed_lbl.configure(text=f"{task.speed} ({int(task.progress * 100)}%)")
            elif task.status == "Completed":
                self.dl_title_lbl.configure(text="Download Complete! Cover art saved.")
                self.dl_progress.set(1.0)
                self.dl_speed_lbl.configure(text="Done")
                self.after(3000, lambda: self.download_banner.pack_forget())
                # Re-render to show "In Library" badge
                self._render_results()
                if self.on_download_completed:
                    self.on_download_completed()
            elif task.status == "Failed":
                self.dl_title_lbl.configure(text=f"Download Error: {task.error_msg}")
                self.after(4000, lambda: self.download_banner.pack_forget())

        self.after(0, update)
