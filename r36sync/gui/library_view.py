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
from .multidisc_dialog import MultiDiscDialog


PAGE_SIZE = 50


class LibraryView(ctk.CTkFrame):
    """The Main Page: Displays local library games and manages R36S handheld sync."""

    def __init__(self, master, on_switch_to_download=None, on_switch_to_browse=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_switch_to_download = on_switch_to_download
        self.on_switch_to_browse = on_switch_to_browse
        self.games: List[LibraryGame] = []
        self.filtered_games: List[LibraryGame] = []
        self.current_page: int = 0
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

        if self.on_switch_to_browse:
            self.browse_systems_btn = ctk.CTkButton(
                action_row,
                text="Browse Systems",
                width=110,
                height=30,
                fg_color="#4f46e5",
                hover_color="#4338ca",
                command=self.on_switch_to_browse
            )
            self.browse_systems_btn.pack(side="left", padx=4)

        self.multidisc_btn = ctk.CTkButton(
            action_row,
            text="Multi-Disc (.m3u)",
            width=130,
            height=30,
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            command=self.open_multidisc_dialog
        )
        self.multidisc_btn.pack(side="left", padx=4)

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
        filter_row.pack(fill="x", padx=12, pady=(4, 4))

        self.search_entry = ctk.CTkEntry(
            filter_row,
            placeholder_text="Search games...",
            width=180,
            height=30
        )
        self.search_entry.pack(side="left", padx=(0, 6))
        self.search_entry.bind("<KeyRelease>", lambda e: self.apply_filter())

        self.console_dropdown = ctk.CTkOptionMenu(
            filter_row,
            values=["All Consoles"] + [c.display_name for c in CONSOLES.values()],
            command=self.on_filter_changed,
            width=165,
            height=30
        )
        self.console_dropdown.pack(side="left", padx=3)

        self.check_dropdown = ctk.CTkOptionMenu(
            filter_row,
            values=["All Checks", "Checked", "Unchecked"],
            command=self.on_filter_changed,
            width=110,
            height=30
        )
        self.check_dropdown.pack(side="left", padx=3)

        self.sync_dropdown = ctk.CTkOptionMenu(
            filter_row,
            values=["All Sync", "Synced", "Not Synced"],
            command=self.on_filter_changed,
            width=110,
            height=30
        )
        self.sync_dropdown.pack(side="left", padx=3)

        self.type_dropdown = ctk.CTkOptionMenu(
            filter_row,
            values=["All Types", "Library Only", "SD Card Only", "Multi-Disc Only", "Single Disc Only"],
            command=self.on_filter_changed,
            width=135,
            height=30
        )
        self.type_dropdown.pack(side="left", padx=3)

        self.sort_dropdown = ctk.CTkOptionMenu(
            filter_row,
            values=["Sort: Title (A-Z)", "Sort: Title (Z-A)", "Sort: Size (Largest)", "Sort: Size (Smallest)", "Sort: Platform (A-Z)"],
            command=self.on_filter_changed,
            width=150,
            height=30
        )
        self.sort_dropdown.pack(side="left", padx=3)

        self.reset_filter_btn = ctk.CTkButton(
            filter_row,
            text="Reset",
            width=55,
            height=30,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self.reset_filters
        )
        self.reset_filter_btn.pack(side="left", padx=3)

        # 3. Pagination & Navigation Bar
        nav_row = ctk.CTkFrame(self, fg_color="transparent")
        nav_row.pack(fill="x", padx=12, pady=(2, 6))

        self.stats_label = ctk.CTkLabel(
            nav_row,
            text="0 games in library",
            text_color="gray60",
            font=ctk.CTkFont(size=12)
        )
        self.stats_label.pack(side="left", padx=4)

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
            text="Page 1 of 1",
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

        # 4. Main Games Scrollable Container
        self.scroll_frame = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.scroll_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # Checkbox variable storage
        self.check_vars: Dict[str, ctk.BooleanVar] = {}

    def next_page(self):
        total_pages = max(1, (len(self.filtered_games) + PAGE_SIZE - 1) // PAGE_SIZE)
        if self.current_page + 1 < total_pages:
            self.current_page += 1
            self._render_games()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._render_games()

    def on_tab_activated(self):
        """Called when user switches to Library tab."""
        self.refresh_library()

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

        # Preserve user checked states across refreshes
        checked_states = {}
        for key, var in self.check_vars.items():
            checked_states[key] = var.get()

        self.games = sync_manager.scan_library(settings.library_dir, sd_root)

        # Restore checked states
        for game in self.games:
            key = f"{game.console_code}:{game.file_name}"
            if key in checked_states:
                game.is_checked = checked_states[key]

        self.apply_filter()

    def on_filter_changed(self, _=None):
        self.apply_filter()

    def reset_filters(self):
        self.search_entry.delete(0, "end")
        self.console_dropdown.set("All Consoles")
        self.check_dropdown.set("All Checks")
        self.sync_dropdown.set("All Sync")
        self.type_dropdown.set("All Types")
        self.sort_dropdown.set("Sort: Title (A-Z)")
        self.apply_filter()

    def apply_filter(self):
        query = self.search_entry.get().strip().lower()
        console_sel = self.console_dropdown.get() if hasattr(self, "console_dropdown") else "All Consoles"
        check_sel = self.check_dropdown.get() if hasattr(self, "check_dropdown") else "All Checks"
        sync_sel = self.sync_dropdown.get() if hasattr(self, "sync_dropdown") else "All Sync"
        type_sel = self.type_dropdown.get() if hasattr(self, "type_dropdown") else "All Types"
        sort_sel = self.sort_dropdown.get() if hasattr(self, "sort_dropdown") else "Sort: Title (A-Z)"

        # Resolve console filter
        selected_code = "all"
        if console_sel != "All Consoles":
            for code, c_def in CONSOLES.items():
                if c_def.display_name == console_sel:
                    selected_code = code
                    break

        self.filtered_games = []

        for game in self.games:
            # 1. Console filter
            if selected_code != "all" and game.console_code != selected_code:
                continue

            # 2. Search query filter
            if query and query not in game.file_name.lower() and query not in game.stem.lower():
                continue

            # 3. Check status filter (checked / unchecked)
            if check_sel == "Checked" and not game.is_checked:
                continue
            elif check_sel == "Unchecked" and game.is_checked:
                continue

            # 4. Handheld Sync status filter (synced / not synced)
            if sync_sel == "Synced" and not (game.is_on_handheld and game.is_on_pc):
                continue
            elif sync_sel == "Not Synced" and (game.is_on_handheld and game.is_on_pc):
                continue

            # 5. Type / Location filter (SD card only, library only, multi-disc only, single disc only)
            if type_sel == "Library Only" and (not game.is_on_pc or game.is_on_handheld):
                continue
            elif type_sel == "SD Card Only" and (not game.is_on_handheld or game.is_on_pc):
                continue
            elif type_sel == "Multi-Disc Only" and not (game.is_playlist or game.disc_count > 1):
                continue
            elif type_sel == "Single Disc Only" and (game.is_playlist or game.disc_count > 1):
                continue

            self.filtered_games.append(game)

        # 5. Sorting (Title, Size, Platform)
        if sort_sel == "Sort: Title (A-Z)":
            self.filtered_games.sort(key=lambda g: g.stem.lower())
        elif sort_sel == "Sort: Title (Z-A)":
            self.filtered_games.sort(key=lambda g: g.stem.lower(), reverse=True)
        elif sort_sel == "Sort: Size (Largest)":
            self.filtered_games.sort(key=lambda g: g.size_bytes, reverse=True)
        elif sort_sel == "Sort: Size (Smallest)":
            self.filtered_games.sort(key=lambda g: g.size_bytes)
        elif sort_sel == "Sort: Platform (A-Z)":
            self.filtered_games.sort(key=lambda g: (g.console_name, g.stem.lower()))

        self.current_page = 0
        self._render_games()

    def _render_games(self):
        total_games = len(self.filtered_games)
        total_pages = max(1, (total_games + PAGE_SIZE - 1) // PAGE_SIZE)
        cur_p = min(self.current_page + 1, total_pages)
        self.page_lbl.configure(text=f"Page {cur_p} of {total_pages}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_btn.configure(state="normal" if cur_p < total_pages else "disabled")

        total_synced = sum(1 for g in self.games if g.is_on_handheld)
        start_idx = self.current_page * PAGE_SIZE
        end_idx = min(start_idx + PAGE_SIZE, total_games)
        if total_games > 0:
            self.stats_label.configure(
                text=f"{len(self.games)} in library ({total_synced} on handheld) • Showing {start_idx + 1}-{end_idx} of {total_games}"
            )
        else:
            self.stats_label.configure(
                text=f"{len(self.games)} in library ({total_synced} on handheld)"
            )

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
                    text="Go to the Browse tab to search and download games from Minerva Archive,\nor drop your ROM files into your Library folder.",
                    font=ctk.CTkFont(size=13),
                    text_color="gray50"
                ).pack(pady=4)

                btn_row = ctk.CTkFrame(empty_box, fg_color="transparent")
                btn_row.pack(pady=12)

                if self.on_switch_to_browse:
                    ctk.CTkButton(
                        btn_row,
                        text="Browse & Search Archive",
                        font=ctk.CTkFont(size=13, weight="bold"),
                        fg_color="#4f46e5",
                        hover_color="#4338ca",
                        command=self.on_switch_to_browse
                    ).pack(side="left", padx=6)
            return

        page_games = self.filtered_games[start_idx:end_idx]
        for game in page_games:
            self._render_game_row(game)

        try:
            self.scroll_frame._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _render_game_row(self, game: LibraryGame):
        row = ctk.CTkFrame(self.scroll_frame, corner_radius=8, height=54, fg_color=("gray90", "gray18"))
        row.pack(fill="x", padx=4, pady=3)
        row.pack_propagate(False)

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

        # Handheld Sync Badge
        if game.is_on_handheld and not game.is_on_pc:
            badge_text = "SD Card Only"
            badge_color = ("#e0e7ff", "#312e81")
            badge_text_color = ("#3730a3", "#a5b4fc")
        elif game.is_on_handheld:
            badge_text = "On Handheld"
            badge_color = ("#d1fae5", "#064e3b")
            badge_text_color = ("#065f46", "#6ee7b7")
        else:
            badge_text = "PC Library Only"
            badge_color = ("gray80", "gray25")
            badge_text_color = ("gray30", "gray70")

        # Pack right-hand action controls FIRST so they are never shoved outside window
        del_btn = ctk.CTkButton(
            row,
            text="🗑️",
            width=32,
            height=26,
            fg_color=("gray75", "gray28"),
            hover_color=("#b91c1c", "#991b1b"),
            command=lambda g=game: self.delete_game_from_library(g)
        )
        del_btn.pack(side="right", padx=(2, 6))

        art_btn = ctk.CTkButton(
            row,
            text="Art",
            width=36,
            height=26,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=lambda g=game: self.fetch_art_for_game(g)
        )
        art_btn.pack(side="right", padx=2)

        if not game.is_on_pc:
            import_btn = ctk.CTkButton(
                row,
                text="⬇ PC",
                width=42,
                height=26,
                fg_color="#6366f1",
                hover_color="#4f46e5",
                command=lambda g=game: self.import_game_to_pc(g)
            )
            import_btn.pack(side="right", padx=2)

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
        badge.pack(side="right", padx=(4, 6))

        # Game title and info packed AFTER right buttons to occupy remaining space cleanly
        info_frame = ctk.CTkFrame(row, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=8, pady=6)

        display_title = game.stem
        if len(display_title) > 65:
            display_title = display_title[:62] + "..."
        if game.is_playlist:
            display_title = f"{display_title}  💿 [{game.disc_count} Discs]"

        title_lbl = ctk.CTkLabel(
            info_frame,
            text=display_title,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        )
        title_lbl.pack(fill="x")

        sub_text = f"{game.console_name} • {game.size_str}"
        if game.is_playlist:
            sub_text += f" • Playlist ({game.file_path.suffix.lower()})"
        if not game.is_on_pc:
            sub_text += " • (On SD Card)"

        sub_lbl = ctk.CTkLabel(
            info_frame,
            text=sub_text,
            font=ctk.CTkFont(size=11),
            text_color="#818cf8" if game.is_playlist else "gray60",
            anchor="w"
        )
        sub_lbl.pack(fill="x")

        # Double-click anywhere on row to toggle check/uncheck
        def on_double_click(event=None):
            var.set(not var.get())
            on_toggle()

        for w in (row, thumb_label, info_frame, title_lbl, sub_lbl, badge):
            w.bind("<Double-Button-1>", on_double_click)

    def import_game_to_pc(self, game: LibraryGame):
        import tkinter.messagebox as mb
        try:
            sync_manager.import_sd_game_to_pc(game, settings.library_dir)
            self.refresh_library()
            mb.showinfo("Imported", f"Successfully imported '{game.stem}' to your PC library!", parent=self.winfo_toplevel())
        except Exception as e:
            mb.showerror("Import Failed", f"Could not import game: {e}", parent=self.winfo_toplevel())

    def delete_game_from_library(self, game: LibraryGame):
        import tkinter.messagebox as mb
        msg = f"Delete '{game.stem}' from your local library?"
        if game.is_playlist:
            msg = f"Delete playlist '{game.stem}' and all its {game.disc_count} disc files from your library?"

        if not mb.askyesno("Confirm Delete", msg, parent=self.winfo_toplevel()):
            return

        try:
            from ..m3u_manager import m3u_manager
            if game.is_playlist:
                discs = m3u_manager.parse_playlist_discs(game.file_path)
                for d in discs:
                    if d.exists():
                        d.unlink()
                if game.file_path.exists():
                    game.file_path.unlink()
                if game.cover_art_path and game.cover_art_path.exists():
                    game.cover_art_path.unlink()
            else:
                if game.file_path.exists():
                    game.file_path.unlink()
                m3u_manager.handle_disc_file_removed(game.file_path)
                if game.cover_art_path and game.cover_art_path.exists():
                    game.cover_art_path.unlink()

            self.refresh_library()
        except Exception as e:
            mb.showerror("Delete Failed", f"Could not delete game: {e}", parent=self.winfo_toplevel())

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

    def open_multidisc_dialog(self):
        MultiDiscDialog(self, on_playlists_updated=self.refresh_library)

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
