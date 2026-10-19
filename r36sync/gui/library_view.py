"""
Library View for R36Sync (Main Page).
Displays all downloaded games present on disk, sync checkboxes, cover arts, and sync actions.
"""
import os
from pathlib import Path
import subprocess
import threading
from typing import Dict, List, Optional
import customtkinter as ctk
from PIL import Image

from ..config import CONSOLES, settings
from ..cover_art import cover_manager
from ..sd_detector import sd_detector, SDCardInfo
from ..sync_manager import sync_manager, LibraryGame, SyncResult


class LibraryView(ctk.CTkFrame):
    """The Main Page: Displays local library games and manages R36S handheld sync."""

    def __init__(self, master, on_switch_to_download=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_switch_to_download = on_switch_to_download
        self.games: List[LibraryGame] = []
        self.filtered_games: List[LibraryGame] = []
        self.active_sd_info: Optional[SDCardInfo] = None
        self.selected_console_filter: str = "all"
        self._thumb_cache: Dict[str, ctk.CTkImage] = {}

        self._create_ui()

    def _create_ui(self):
        # 1. Top Control Header
        header_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
        header_frame.pack(fill="x", padx=12, pady=(10, 6))

        # Top Row: Title & Handheld SD card status
        top_row = ctk.CTkFrame(header_frame, fg_color="transparent")
        top_row.pack(fill="x", padx=12, pady=(8, 4))

        self.title_label = ctk.CTkLabel(
            top_row,
            text="Game Library",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.title_label.pack(side="left")

        self.sd_status_badge = ctk.CTkLabel(
            top_row,
            text="Scanning SD Card...",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("gray75", "gray25"),
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.sd_status_badge.pack(side="right", padx=6)

        self.refresh_sd_btn = ctk.CTkButton(
            top_row,
            text="Detect SD",
            width=80,
            height=28,
            command=self.refresh_sd_card
        )
        self.refresh_sd_btn.pack(side="right", padx=4)

        # Second Row: Sync action button & selection controls
        action_row = ctk.CTkFrame(header_frame, fg_color="transparent")
        action_row.pack(fill="x", padx=12, pady=(4, 8))

        self.sync_btn = ctk.CTkButton(
            action_row,
            text="Sync with R36S Handheld",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=34,
            command=self.execute_sync
        )
        self.sync_btn.pack(side="left", padx=(0, 10))

        self.check_all_btn = ctk.CTkButton(
            action_row,
            text="Check All",
            width=80,
            height=30,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=lambda: self.set_all_checked(True)
        )
        self.check_all_btn.pack(side="left", padx=4)

        self.uncheck_all_btn = ctk.CTkButton(
            action_row,
            text="Uncheck All",
            width=85,
            height=30,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=lambda: self.set_all_checked(False)
        )
        self.uncheck_all_btn.pack(side="left", padx=4)

        self.refresh_lib_btn = ctk.CTkButton(
            action_row,
            text="Refresh Library",
            width=100,
            height=30,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self.refresh_library
        )
        self.refresh_lib_btn.pack(side="left", padx=4)

        self.open_folder_btn = ctk.CTkButton(
            action_row,
            text="Open Folder",
            width=90,
            height=30,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self.open_library_folder
        )
        self.open_folder_btn.pack(side="right")

        # 2. Filter & Search Row
        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.pack(fill="x", padx=12, pady=(4, 6))

        self.search_entry = ctk.CTkEntry(
            filter_row,
            placeholder_text="Filter library games...",
            width=280,
            height=32
        )
        self.search_entry.pack(side="left", padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self.apply_filter())

        self.console_dropdown = ctk.CTkOptionMenu(
            filter_row,
            values=["All Consoles"] + [c.display_name for c in CONSOLES.values()],
            command=self.on_console_filter_changed,
            width=220,
            height=32
        )
        self.console_dropdown.pack(side="left", padx=4)

        self.stats_label = ctk.CTkLabel(
            filter_row,
            text="0 games in library",
            text_color="gray60",
            font=ctk.CTkFont(size=12)
        )
        self.stats_label.pack(side="right", padx=6)

        # 3. Main Games Scrollable Container
        self.scroll_frame = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.scroll_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # Checkbox variable storage
        self.check_vars: Dict[str, ctk.BooleanVar] = {}

    def refresh_sd_card(self):
        """Scans for R36S SD card and updates status badge."""
        cards = sd_detector.find_r36s_sd_cards()
        if cards:
            self.active_sd_info = cards[0]
            label = self.active_sd_info.volume_label or "SD Card"
            self.sd_status_badge.configure(
                text=f"R36S Found: {self.active_sd_info.drive_letter} [{label}] ({self.active_sd_info.free_gb:.1f} GB Free)",
                fg_color="#065f46",
                text_color="#6ee7b7"
            )
        else:
            # Check if settings has a manual path
            if settings.sd_card_dir and Path(settings.sd_card_dir).exists():
                info = sd_detector.inspect_drive(settings.sd_card_dir)
                if info:
                    self.active_sd_info = info
                    self.sd_status_badge.configure(
                        text=f"Custom SD: {info.drive_letter} ({info.free_gb:.1f} GB Free)",
                        fg_color="#065f46",
                        text_color="#6ee7b7"
                    )
                    return

            self.active_sd_info = None
            self.sd_status_badge.configure(
                text="No R36S SD Card Detected",
                fg_color="#7f1d1d",
                text_color="#fca5a5"
            )

    def refresh_library(self):
        """Scans the local library directory and populates the list."""
        self.refresh_sd_card()
        sd_root = self.active_sd_info.roms_root if self.active_sd_info else None
        self.games = sync_manager.scan_library(settings.library_dir, sd_root)
        self.apply_filter()

    def on_console_filter_changed(self, selection: str):
        if selection == "All Consoles":
            self.selected_console_filter = "all"
        else:
            for code, c_def in CONSOLES.items():
                if c_def.display_name == selection:
                    self.selected_console_filter = code
                    break
        self.apply_filter()

    def apply_filter(self):
        query = self.search_entry.get().strip().lower()
        self.filtered_games = []

        for game in self.games:
            # Console filter
            if self.selected_console_filter != "all" and game.console_code != self.selected_console_filter:
                continue
            # Search query
            if query and query not in game.file_name.lower() and query not in game.stem.lower():
                continue
            self.filtered_games.append(game)

        total_synced = sum(1 for g in self.games if g.is_on_handheld)
        self.stats_label.configure(
            text=f"{len(self.games)} in library ({total_synced} on handheld) • Showing {len(self.filtered_games)}"
        )

        self._render_games()

    def _render_games(self):
        # Clear existing rows
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        self.check_vars.clear()

        if not self.filtered_games:
            empty_box = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            empty_box.pack(pady=60)

            msg = "No games found in your Library." if not self.games else "No games match your search query."
            ctk.CTkLabel(
                empty_box,
                text=msg,
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="gray60"
            ).pack(pady=4)

            if not self.games:
                ctk.CTkLabel(
                    empty_box,
                    text="Go to the Download tab to search and download games from Minerva Archive,\nor drop your ROM files into your Library folder.",
                    font=ctk.CTkFont(size=13),
                    text_color="gray50"
                ).pack(pady=4)

                if self.on_switch_to_download:
                    ctk.CTkButton(
                        empty_box,
                        text="Go to Download Tab",
                        font=ctk.CTkFont(size=13, weight="bold"),
                        fg_color="#3b82f6",
                        command=self.on_switch_to_download
                    ).pack(pady=12)
            return

        for game in self.filtered_games:
            self._render_game_row(game)

    def _render_game_row(self, game: LibraryGame):
        row = ctk.CTkFrame(self.scroll_frame, corner_radius=8, fg_color=("gray90", "gray18"))
        row.pack(fill="x", padx=4, pady=3)

        key = f"{game.console_code}:{game.file_name}"
        var = ctk.BooleanVar(value=game.is_checked)
        self.check_vars[key] = var

        def on_toggle():
            game.is_checked = var.get()

        # Checkbox
        cb = ctk.CTkCheckBox(
            row,
            text="",
            variable=var,
            width=24,
            command=on_toggle
        )
        cb.pack(side="left", padx=(10, 6))

        # Thumbnail
        thumb_label = ctk.CTkLabel(row, text="", width=40, height=40)
        thumb_label.pack(side="left", padx=4)

        if game.has_cover_art and game.cover_art_path:
            ctk_img = self._get_ctk_thumb(str(game.cover_art_path))
            if ctk_img:
                thumb_label.configure(image=ctk_img)
            else:
                thumb_label.configure(text="🎮")
        else:
            thumb_label.configure(text="🎮", font=ctk.CTkFont(size=16))

        # Game title and info
        info_frame = ctk.CTkFrame(row, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=8, pady=6)

        title_lbl = ctk.CTkLabel(
            info_frame,
            text=game.stem,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        )
        title_lbl.pack(fill="x")

        sub_text = f"{game.console_name} • {game.size_str}"
        sub_lbl = ctk.CTkLabel(
            info_frame,
            text=sub_text,
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            anchor="w"
        )
        sub_lbl.pack(fill="x")

        # Handheld Sync Badge
        if game.is_on_handheld:
            badge_text = "On Handheld"
            badge_color = ("#d1fae5", "#064e3b")
            badge_text_color = ("#065f46", "#6ee7b7")
        else:
            badge_text = "PC Library Only"
            badge_color = ("gray80", "gray25")
            badge_text_color = ("gray30", "gray70")

        badge = ctk.CTkLabel(
            row,
            text=badge_text,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=badge_color,
            text_color=badge_text_color,
            corner_radius=6,
            padx=8,
            pady=2
        )
        badge.pack(side="right", padx=(4, 12))

        # Re-fetch art button
        art_btn = ctk.CTkButton(
            row,
            text="Art",
            width=40,
            height=26,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=lambda g=game: self.fetch_art_for_game(g)
        )
        art_btn.pack(side="right", padx=4)

    def _get_ctk_thumb(self, path_str: str) -> Optional[ctk.CTkImage]:
        if path_str in self._thumb_cache:
            return self._thumb_cache[path_str]
        pil_img = cover_manager.load_thumbnail_image(Path(path_str), (40, 40))
        if pil_img:
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(40, 40))
            self._thumb_cache[path_str] = ctk_img
            return ctk_img
        return None

    def set_all_checked(self, checked: bool):
        for game in self.filtered_games:
            game.is_checked = checked
            key = f"{game.console_code}:{game.file_name}"
            if key in self.check_vars:
                self.check_vars[key].set(checked)

    def fetch_art_for_game(self, game: LibraryGame):
        def task():
            cover_manager.download_cover_art(game.console_code, game.file_name)
            self.after(100, self.refresh_library)
        threading.Thread(target=task, daemon=True).start()

    def open_library_folder(self):
        lib_path = Path(settings.library_dir)
        lib_path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(lib_path))
        except Exception as e:
            print(f"Error opening library: {e}")

    def execute_sync(self):
        """Runs the sync/unsync process in a worker thread with a progress modal."""
        if not self.active_sd_info:
            # Alert user that no SD card was detected
            self._show_alert("No SD Card", "Please connect your R36S SD card or configure a custom path in Settings.")
            return

        # Prepare progress dialog
        dialog = ctk.CTkToplevel(self)
        dialog.title("Syncing with R36S")
        dialog.geometry("420x200")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        status_lbl = ctk.CTkLabel(
            dialog,
            text="Preparing sync...",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        status_lbl.pack(pady=(25, 10))

        prog_bar = ctk.CTkProgressBar(dialog, width=340)
        prog_bar.set(0)
        prog_bar.pack(pady=10)

        detail_lbl = ctk.CTkLabel(
            dialog,
            text="Backing up saves and copying files...",
            font=ctk.CTkFont(size=12),
            text_color="gray60"
        )
        detail_lbl.pack(pady=4)

        def sync_worker():
            def on_progress(msg, frac):
                dialog.after(0, lambda: [
                    status_lbl.configure(text=msg),
                    prog_bar.set(frac),
                    detail_lbl.configure(text=msg)
                ])

            sd_root = self.active_sd_info.roms_root
            result = sync_manager.sync_to_handheld(
                self.games,
                sd_root,
                settings.backup_dir,
                on_progress=on_progress
            )

            def on_done():
                dialog.destroy()
                summary = (
                    f"Sync Complete!\n\n"
                    f"• {result.synced_count} game(s) synced to R36S\n"
                    f"• {result.unsynced_count} game(s) unsynced from R36S\n"
                    f"• {result.saves_backed_up} save file(s) safely backed up"
                )
                if result.errors:
                    summary += f"\n\nWarnings:\n" + "\n".join(result.errors[:3])
                self._show_alert("Sync Finished", summary)
                self.refresh_library()

            dialog.after(500, on_done)

        threading.Thread(target=sync_worker, daemon=True).start()

    def _show_alert(self, title: str, message: str):
        top = ctk.CTkToplevel(self)
        top.title(title)
        top.geometry("400x220")
        top.transient(self.winfo_toplevel())
        top.grab_set()

        ctk.CTkLabel(
            top,
            text=title,
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(20, 10))

        ctk.CTkLabel(
            top,
            text=message,
            wraplength=340,
            font=ctk.CTkFont(size=13)
        ).pack(pady=10, padx=20)

        ctk.CTkButton(
            top,
            text="OK",
            width=100,
            command=top.destroy
        ).pack(pady=(10, 20))
