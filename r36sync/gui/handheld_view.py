"""
Handheld & SD Card View for R36Sync.
Displays R36S SD card diagnostics, storage usage, and all games currently installed on the SD card.
Provides one-click import to PC, game deletion from SD card, and access to save game backup history.
"""
import os
from pathlib import Path
import shutil
import threading
from typing import Optional, List, Dict, Any
import customtkinter as ctk

from ..config import CONSOLES, SAVE_EXTENSIONS, settings
from ..cover_art import cover_manager
from ..database import db
from ..sd_detector import sd_detector, SDCardInfo
from ..sync_manager import sync_manager


PAGE_SIZE = 50


class SavesHistoryDialog(ctk.CTkToplevel):
    """Modal dialog displaying save game backup history and one-click restores."""

    def __init__(self, master, active_sd: Optional[SDCardInfo] = None, **kwargs):
        super().__init__(master, **kwargs)
        self.active_sd = active_sd
        self.title("Save Backups History & Restores")
        self.geometry("680x480")
        self.minsize(550, 380)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        self._create_ui()
        self._render_saves()

    def _create_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            header,
            text="Save Backups History",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        ctk.CTkButton(
            header,
            text="Open Backup Folder",
            width=140,
            command=self.open_backups_folder
        ).pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(self, corner_radius=8)
        self.scroll.pack(fill="both", expand=True, padx=16, pady=(4, 14))

    def open_backups_folder(self):
        b_path = Path(settings.backup_dir)
        b_path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(b_path))

    def _render_saves(self):
        for w in self.scroll.winfo_children():
            w.destroy()

        backups = db.get_save_backups(limit=80)
        if not backups:
            ctk.CTkLabel(
                self.scroll,
                text="No save backups recorded yet.\nSaves are automatically backed up during synchronization.",
                font=ctk.CTkFont(size=13),
                text_color="gray60"
            ).pack(pady=40)
            return

        for save in backups:
            row = ctk.CTkFrame(self.scroll, fg_color=("gray90", "gray18"), corner_radius=6)
            row.pack(fill="x", padx=4, pady=2)

            restore_btn = ctk.CTkButton(
                row,
                text="Restore to SD",
                width=100,
                height=26,
                fg_color=("gray75", "gray28"),
                hover_color=("gray65", "gray35"),
                command=lambda s=save: self.restore_save(s)
            )
            restore_btn.pack(side="right", padx=8)

            info_box = ctk.CTkFrame(row, fg_color="transparent")
            info_box.pack(side="left", fill="both", expand=True, padx=10, pady=4)

            ctk.CTkLabel(
                info_box,
                text=save.get("file_name", ""),
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w"
            ).pack(fill="x")

            time_str = save.get("backup_time", "")
            c_code = save.get("console_code", "").upper()
            size = save.get("file_size", 0)
            ctk.CTkLabel(
                info_box,
                text=f"{c_code} • {time_str} • {size:,} bytes",
                font=ctk.CTkFont(size=11),
                text_color="gray60",
                anchor="w"
            ).pack(fill="x")

    def restore_save(self, save_record):
        if not self.active_sd or not self.active_sd.roms_root.exists():
            import tkinter.messagebox as mb
            mb.showwarning("No SD Card", "Please connect your R36S SD card first.", parent=self)
            return

        backup_path = Path(save_record.get("backup_path", ""))
        if not backup_path.exists():
            import tkinter.messagebox as mb
            mb.showerror("Missing File", "The backup file was not found on disk.", parent=self)
            return

        console_code = save_record.get("console_code", "")
        dest_dir = self.active_sd.roms_root / console_code
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / save_record.get("file_name", "")

        try:
            shutil.copy2(backup_path, dest_file)
            import tkinter.messagebox as mb
            mb.showinfo("Save Restored", f"Restored {dest_file.name} to {console_code} on R36S!", parent=self)
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("Error", f"Failed to restore save: {e}", parent=self)


class HandheldView(ctk.CTkFrame):
    """SD Card & Handheld Tab: Hardware inspection, storage diagnostics, installed games manager."""

    def __init__(self, master, on_sync_triggered=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_sync_triggered = on_sync_triggered
        self.active_sd: Optional[SDCardInfo] = None
        self.sd_games: List[Dict[str, Any]] = []
        self.filtered_sd_games: List[Dict[str, Any]] = []
        self.current_page: int = 0
        self.selected_console_filter: str = "all"
        self._thumb_cache: Dict[str, ctk.CTkImage] = {}

        self._create_ui()

    def on_tab_activated(self):
        """Called when user switches to SD Card & Sync tab."""
        self.refresh()

    def _create_ui(self):
        # 1. SD Card Diagnostic Card
        self.card_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
        self.card_frame.pack(fill="x", padx=12, pady=(10, 6))

        header_row = ctk.CTkFrame(self.card_frame, fg_color="transparent")
        header_row.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            header_row,
            text="R36S Handheld SD Card Diagnostics",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        self.rescan_btn = ctk.CTkButton(
            header_row,
            text="Rescan Drives",
            width=110,
            command=self.refresh
        )
        self.rescan_btn.pack(side="right")

        # Drive details
        self.details_label = ctk.CTkLabel(
            self.card_frame,
            text="Scanning for R36S SD cards...",
            font=ctk.CTkFont(size=13),
            justify="left",
            anchor="w"
        )
        self.details_label.pack(fill="x", padx=14, pady=4)

        # Storage bar
        self.storage_progress = ctk.CTkProgressBar(self.card_frame, height=12)
        self.storage_progress.pack(fill="x", padx=14, pady=(4, 6))
        self.storage_progress.set(0)

        self.storage_text = ctk.CTkLabel(
            self.card_frame,
            text="Storage: 0 GB / 0 GB",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            anchor="w"
        )
        self.storage_text.pack(fill="x", padx=14, pady=(0, 6))

        # Folder structure status
        self.folders_summary_lbl = ctk.CTkLabel(
            self.card_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="gray70",
            wraplength=700,
            justify="left",
            anchor="w"
        )
        self.folders_summary_lbl.pack(fill="x", padx=14, pady=(0, 10))

        # Actions Row
        action_row = ctk.CTkFrame(self.card_frame, fg_color="transparent")
        action_row.pack(fill="x", padx=14, pady=(0, 12))

        self.prepare_btn = ctk.CTkButton(
            action_row,
            text="Setup Standard R36S Folders",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#6366f1",
            hover_color="#4f46e5",
            command=self.prepare_folders
        )
        self.prepare_btn.pack(side="left", padx=(0, 8))

        self.backup_saves_btn = ctk.CTkButton(
            action_row,
            text="Backup Saves Now",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            command=self.backup_saves_now
        )
        self.backup_saves_btn.pack(side="left", padx=4)

        self.saves_history_btn = ctk.CTkButton(
            action_row,
            text="Saves History...",
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self.open_saves_history
        )
        self.saves_history_btn.pack(side="left", padx=4)

        self.open_sd_btn = ctk.CTkButton(
            action_row,
            text="Open SD in Explorer",
            fg_color=("gray75", "gray28"),
            command=self.open_sd_in_explorer
        )
        self.open_sd_btn.pack(side="left", padx=4)

        # 2. Installed Games on SD Card Section
        games_section = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
        games_section.pack(fill="both", expand=True, padx=12, pady=(6, 10))

        g_header = ctk.CTkFrame(games_section, fg_color="transparent")
        g_header.pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkLabel(
            g_header,
            text="Games Installed on R36S Handheld",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(side="left")

        self.games_badge = ctk.CTkLabel(
            g_header,
            text="0 games on SD card",
            font=ctk.CTkFont(size=12),
            text_color="gray60"
        )
        self.games_badge.pack(side="left", padx=10)

        # Filter row
        filter_row = ctk.CTkFrame(games_section, fg_color="transparent")
        filter_row.pack(fill="x", padx=14, pady=(2, 6))

        self.search_entry = ctk.CTkEntry(
            filter_row,
            placeholder_text="Filter games on SD card...",
            width=260,
            height=30
        )
        self.search_entry.pack(side="left", padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self.apply_filter())

        self.console_dropdown = ctk.CTkOptionMenu(
            filter_row,
            values=["All Consoles"] + [c.display_name for c in CONSOLES.values()],
            command=self.on_console_filter_changed,
            width=210,
            height=30
        )
        self.console_dropdown.pack(side="left", padx=4)

        # Pagination controls
        self.next_btn = ctk.CTkButton(
            filter_row,
            text="Next >",
            width=65,
            height=28,
            command=self.next_page
        )
        self.next_btn.pack(side="right", padx=4)

        self.page_lbl = ctk.CTkLabel(
            filter_row,
            text="Page 1 of 1",
            font=ctk.CTkFont(size=12)
        )
        self.page_lbl.pack(side="right", padx=6)

        self.prev_btn = ctk.CTkButton(
            filter_row,
            text="< Prev",
            width=65,
            height=28,
            command=self.prev_page
        )
        self.prev_btn.pack(side="right", padx=4)

        # Scrollable games table
        self.games_scroll = ctk.CTkScrollableFrame(games_section, corner_radius=8)
        self.games_scroll.pack(fill="both", expand=True, padx=14, pady=(4, 10))

    def next_page(self):
        total_pages = max(1, (len(self.filtered_sd_games) + PAGE_SIZE - 1) // PAGE_SIZE)
        if self.current_page + 1 < total_pages:
            self.current_page += 1
            self._render_games_table()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._render_games_table()

    def open_saves_history(self):
        """Opens modal dialog for save backups and restores."""
        SavesHistoryDialog(self, active_sd=self.active_sd)

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
        self.filtered_sd_games = []

        for g in self.sd_games:
            if self.selected_console_filter != "all" and g.get("console_code") != self.selected_console_filter:
                continue
            if query and query not in g.get("stem", "").lower() and query not in g.get("file_name", "").lower():
                continue
            self.filtered_sd_games.append(g)

        self.current_page = 0
        self._render_games_table()

    def refresh(self):
        """Scans for SD cards, updates diagnostics, and loads installed games."""
        cards = sd_detector.find_r36s_sd_cards()
        if cards:
            self.active_sd = cards[0]
            info = self.active_sd
            used_gb = info.total_gb - info.free_gb
            ratio = (used_gb / info.total_gb) if info.total_gb > 0 else 0

            status_str = (
                f"Drive: {info.drive_letter}   |   Volume: {info.volume_label or 'Unnamed'}   |   "
                f"Filesystem: {info.filesystem}   |   Handheld Match: {info.match_score}% Confidence"
            )
            self.details_label.configure(text=status_str)
            self.storage_progress.set(ratio)
            self.storage_text.configure(
                text=f"Storage: {used_gb:.1f} GB used of {info.total_gb:.1f} GB total ({info.free_gb:.1f} GB free)"
            )

            folders_str = "Detected ArkOS Folders: " + ", ".join(info.detected_folders[:12])
            if len(info.detected_folders) > 12:
                folders_str += f" (+{len(info.detected_folders) - 12} more)"
            self.folders_summary_lbl.configure(text=folders_str)

            self.prepare_btn.configure(state="normal")
            self.backup_saves_btn.configure(state="normal")
            self.open_sd_btn.configure(state="normal")
        else:
            self.active_sd = None
            self.details_label.configure(
                text="No R36S SD Card detected.\nInsert your microSD card (EASYROMS partition) into your computer or set a custom path in Settings."
            )
            self.storage_progress.set(0)
            self.storage_text.configure(text="Storage: N/A")
            self.folders_summary_lbl.configure(text="")

            self.prepare_btn.configure(state="disabled")
            self.backup_saves_btn.configure(state="disabled")
            self.open_sd_btn.configure(state="disabled")

        self._load_sd_games()
        self.apply_filter()

    def _load_sd_games(self):
        """Scans the active SD card for all game ROMs and playlists."""
        self.sd_games = []
        if not self.active_sd or not self.active_sd.roms_root.exists():
            return

        sd_root = self.active_sd.roms_root
        pc_lib = Path(settings.library_dir)

        # Pre-index PC library files per console code for instant O(1) checks
        pc_library_stems: Dict[str, set] = {}
        for c_k in CONSOLES.keys():
            pc_c_dir = pc_lib / c_k
            if pc_c_dir.exists():
                try:
                    pc_library_stems[c_k] = {
                        pf.stem.lower() for pf in pc_c_dir.iterdir()
                        if pf.is_file() and pf.suffix.lower() not in [".torrent", ".magnet", ".png", ".jpg"]
                    }
                except Exception:
                    pc_library_stems[c_k] = set()
            else:
                pc_library_stems[c_k] = set()

        from ..m3u_manager import m3u_manager

        for console_dir in sd_root.iterdir():
            if not console_dir.is_dir() or console_dir.name.startswith("."):
                continue

            code = console_dir.name.lower()
            c_def = CONSOLES.get(code)
            c_name = c_def.display_name if c_def else code.upper()

            # Find all playlists on SD
            sd_hidden_discs = set()
            playlists = [f for f in console_dir.iterdir() if f.is_file() and f.suffix.lower() in [".m3u", ".m3a"]]
            pl_disc_map = {}
            for pl in playlists:
                discs = m3u_manager.parse_playlist_discs(pl)
                pl_disc_map[pl] = discs
                for d in discs:
                    sd_hidden_discs.add(d.name.lower())

            for f in console_dir.iterdir():
                if not f.is_file():
                    continue
                ext = f.suffix.lower()
                if ext in [".png", ".jpg", ".txt", ".json", ".xml", ".torrent", ".magnet"] + SAVE_EXTENSIONS:
                    continue
                if c_def and c_def.extensions and ext not in c_def.extensions and ext not in [".zip", ".7z"]:
                    continue

                if f.name.lower() in sd_hidden_discs:
                    continue

                stem = f.stem
                is_playlist = ext in [".m3u", ".m3a"]
                disc_count = 1
                if is_playlist:
                    discs = pl_disc_map.get(f, [])
                    disc_count = max(1, len(discs))
                    try:
                        size_bytes = sum(d.stat().st_size for d in discs if d.exists())
                    except Exception:
                        size_bytes = f.stat().st_size
                    if size_bytes == 0:
                        size_bytes = f.stat().st_size
                else:
                    size_bytes = f.stat().st_size

                # Fast O(1) in-memory check if in PC library
                is_on_pc = stem.lower() in pc_library_stems.get(code, set())

                # Cover art
                sd_art = console_dir / "images" / f"{stem}-image.png"
                if not sd_art.exists():
                    sd_art = console_dir / "images" / f"{stem}.png"
                pc_art = cover_manager.get_cover_art_path(str(pc_lib), code, f.name)
                art_path = sd_art if sd_art.exists() else (pc_art if pc_art.exists() else None)

                self.sd_games.append({
                    "file_path": f,
                    "file_name": f.name,
                    "stem": stem,
                    "console_code": code,
                    "console_name": c_name,
                    "size_bytes": size_bytes,
                    "size_str": self._format_size(size_bytes),
                    "is_playlist": is_playlist,
                    "disc_count": disc_count,
                    "is_on_pc": is_on_pc,
                    "cover_art_path": art_path
                })

        self.sd_games.sort(key=lambda g: (g["console_name"], g["stem"].lower()))

    def _render_games_table(self):
        for w in self.games_scroll.winfo_children():
            w.destroy()

        total_pages = max(1, (len(self.filtered_sd_games) + PAGE_SIZE - 1) // PAGE_SIZE)
        if self.current_page >= total_pages:
            self.current_page = max(0, total_pages - 1)

        cur_p = self.current_page + 1
        self.page_lbl.configure(text=f"Page {cur_p} of {total_pages}")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_btn.configure(state="normal" if cur_p < total_pages else "disabled")

        self.games_badge.configure(
            text=f"{len(self.sd_games)} games on SD card • Showing {len(self.filtered_sd_games)}"
        )

        if not self.active_sd:
            ctk.CTkLabel(
                self.games_scroll,
                text="No R36S SD Card detected.\nConnect your SD card to view and manage installed games.",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="gray60"
            ).pack(pady=40)
            return

        if not self.filtered_sd_games:
            msg = "No games installed on this SD card yet." if not self.sd_games else "No games match your search query."
            ctk.CTkLabel(
                self.games_scroll,
                text=msg,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="gray60"
            ).pack(pady=40)
            return

        start_idx = self.current_page * PAGE_SIZE
        end_idx = start_idx + PAGE_SIZE
        page_games = self.filtered_sd_games[start_idx:end_idx]

        for game in page_games:
            self._render_game_row(game)

        try:
            self.games_scroll._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _render_game_row(self, game: Dict[str, Any]):
        row = ctk.CTkFrame(self.games_scroll, fg_color=("gray90", "gray18"), corner_radius=8, height=54)
        row.pack(fill="x", padx=4, pady=3)
        row.pack_propagate(False)

        # Thumbnail
        thumb_label = ctk.CTkLabel(row, text="", width=40, height=40)
        thumb_label.pack(side="left", padx=8, pady=4)

        art_path = game.get("cover_art_path")
        if art_path and Path(art_path).exists():
            thumb = self._get_ctk_thumb(str(art_path))
            if thumb:
                thumb_label.configure(image=thumb)
            else:
                thumb_label.configure(text="🎮", font=ctk.CTkFont(size=16))
        else:
            thumb_label.configure(text="🎮", font=ctk.CTkFont(size=16))

        # Status badge (PC status)
        if game.get("is_on_pc"):
            badge_text = "✓ In PC Library"
            badge_color = ("#d1fae5", "#064e3b")
            badge_text_color = ("#065f46", "#6ee7b7")
        else:
            badge_text = "SD Card Only"
            badge_color = ("#e0e7ff", "#312e81")
            badge_text_color = ("#3730a3", "#a5b4fc")

        # Pack right-side buttons FIRST so they stay fixed on the right
        del_btn = ctk.CTkButton(
            row,
            text="🗑️",
            width=32,
            height=26,
            fg_color=("gray75", "gray28"),
            hover_color=("#b91c1c", "#991b1b"),
            command=lambda g=game: self.delete_game_from_sd(g)
        )
        del_btn.pack(side="right", padx=(2, 6))

        if not game.get("is_on_pc"):
            import_btn = ctk.CTkButton(
                row,
                text="⬇ Import to PC",
                width=90,
                height=26,
                fg_color="#6366f1",
                hover_color="#4f46e5",
                command=lambda g=game: self.import_to_pc(g)
            )
            import_btn.pack(side="right", padx=4)

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
        badge.pack(side="right", padx=(4, 8))

        # Title & Info packed SECOND to occupy remaining horizontal space
        info_box = ctk.CTkFrame(row, fg_color="transparent")
        info_box.pack(side="left", fill="both", expand=True, padx=6, pady=4)

        display_title = game["stem"]
        if len(display_title) > 65:
            display_title = display_title[:62] + "..."
        if game.get("is_playlist"):
            display_title += f"  💿 [{game.get('disc_count', 1)} Discs]"

        ctk.CTkLabel(
            info_box,
            text=display_title,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        ).pack(fill="x")

        sub_text = f"{game['console_name']} • {game['size_str']} • {game['file_name']}"
        ctk.CTkLabel(
            info_box,
            text=sub_text,
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            anchor="w"
        ).pack(fill="x")

    def import_to_pc(self, game: Dict[str, Any]):
        """Copies game file and box art from SD card into local PC library."""
        import tkinter.messagebox as mb
        try:
            pc_lib = Path(settings.library_dir)
            target_console = pc_lib / game["console_code"]
            target_console.mkdir(parents=True, exist_ok=True)
            dest_file = target_console / game["file_name"]
            shutil.copy2(game["file_path"], dest_file)

            if game.get("is_playlist"):
                from ..m3u_manager import m3u_manager
                discs = m3u_manager.parse_playlist_discs(game["file_path"])
                for d in discs:
                    try:
                        rel = d.relative_to(game["file_path"].parent)
                    except ValueError:
                        rel = Path(d.name)
                    dest_disc = target_console / rel
                    dest_disc.parent.mkdir(parents=True, exist_ok=True)
                    if d.exists():
                        shutil.copy2(d, dest_disc)

            art_path = game.get("cover_art_path")
            if art_path and Path(art_path).exists():
                art_dir = target_console / "images"
                art_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(art_path, art_dir / f"{game['stem']}-image.png")

            game["is_on_pc"] = True
            self._render_games_table()
            mb.showinfo("Imported", f"Successfully imported '{game['stem']}' to your PC library!", parent=self.winfo_toplevel())
        except Exception as e:
            mb.showerror("Import Failed", f"Could not import game: {e}", parent=self.winfo_toplevel())

    def delete_game_from_sd(self, game: Dict[str, Any]):
        """Deletes game and any associated discs/art from the SD card."""
        import tkinter.messagebox as mb
        title = game["stem"]
        if not mb.askyesno("Confirm Delete", f"Delete '{title}' from your R36S SD card?", parent=self.winfo_toplevel()):
            return

        try:
            f_path = game["file_path"]
            if game.get("is_playlist"):
                from ..m3u_manager import m3u_manager
                discs = m3u_manager.parse_playlist_discs(f_path)
                for d in discs:
                    if d.exists():
                        d.unlink()
                if f_path.exists():
                    f_path.unlink()
            else:
                if f_path.exists():
                    f_path.unlink()

            # Remove art from SD images/ folder
            art_dir = f_path.parent / "images"
            for art_name in [f"{title}-image.png", f"{title}.png"]:
                art_file = art_dir / art_name
                if art_file.exists():
                    art_file.unlink()

            self.refresh()
            mb.showinfo("Deleted", f"Deleted '{title}' from R36S SD card.", parent=self.winfo_toplevel())
        except Exception as e:
            mb.showerror("Delete Failed", f"Could not delete game from SD: {e}", parent=self.winfo_toplevel())

    def _get_ctk_thumb(self, path_str: str) -> Optional[ctk.CTkImage]:
        if path_str in self._thumb_cache:
            return self._thumb_cache[path_str]
        pil_img = cover_manager.load_thumbnail_image(Path(path_str), (40, 40))
        if pil_img:
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(40, 40))
            self._thumb_cache[path_str] = ctk_img
            return ctk_img
        return None

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def prepare_folders(self):
        """Creates the full standard R36S ArkOS folder hierarchy on the active SD card."""
        if not self.active_sd:
            return
        target = self.active_sd.roms_root
        created = sd_detector.create_r36s_folder_structure(target)
        self.refresh()
        import tkinter.messagebox as mb
        mb.showinfo("Folders Ready", f"Created {len(created)} console and box art folders on {target}!", parent=self.winfo_toplevel())

    def backup_saves_now(self):
        """Manual trigger to backup all save files on the SD card."""
        if not self.active_sd:
            return

        def task():
            count, b_bytes, files = sync_manager.backup_handheld_saves(
                self.active_sd.roms_root,
                settings.backup_dir
            )
            self.after(0, lambda: [
                self.refresh(),
                import_mb_info(count, b_bytes)
            ])

        def import_mb_info(count, b_bytes):
            import tkinter.messagebox as mb
            mb.showinfo(
                "Save Backup Complete",
                f"Successfully backed up {count} save file(s) ({b_bytes / 1024:.1f} KB) to your PC!",
                parent=self.winfo_toplevel()
            )

        threading.Thread(target=task, daemon=True).start()

    def open_sd_in_explorer(self):
        if self.active_sd and self.active_sd.roms_root.exists():
            os.startfile(str(self.active_sd.roms_root))
