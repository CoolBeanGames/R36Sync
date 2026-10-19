"""
Multi-Disc Playlist Creator Dialog for R36Sync.
Allows automatic detection and 1-click creation of .m3u / .m3a playlists for multi-disc titles,
as well as manual custom playlist authoring and disc reordering.
"""
from pathlib import Path
from tkinter import filedialog
from typing import Dict, List, Optional
import customtkinter as ctk

from ..config import CONSOLES, settings
from ..m3u_manager import m3u_manager, MultiDiscSet


class MultiDiscDialog(ctkToplevel := ctk.CTkToplevel):
    """Modal dialog for creating and managing .m3u/.m3a playlists for multi-disc titles."""

    def __init__(self, master, on_playlists_updated=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_playlists_updated = on_playlists_updated

        self.title("Multi-Disc Playlist Creator (.m3u / .m3a)")
        self.geometry("780x620")
        self.minsize(680, 500)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        self.detected_sets: List[MultiDiscSet] = []
        self.manual_files: List[Path] = []

        self._create_ui()
        self.refresh_detected_sets()

    def _create_ui(self):
        # Header
        header = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
        header.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            header,
            text="Multi-Disc Game Playlist Creator",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", padx=14, pady=(10, 2))

        ctk.CTkLabel(
            header,
            text="Automatically combines multi-disc titles (PS1, Sega CD, Dreamcast) into single .m3u / .m3a entries\nso ArkOS and RetroArch can swap discs in-game without duplicate menu entries.",
            font=ctk.CTkFont(size=12),
            text_color="gray60",
            justify="left"
        ).pack(anchor="w", padx=14, pady=(0, 10))

        # Tabview: Auto-Detected vs Manual
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.pack(fill="both", expand=True, padx=14, pady=(4, 12))

        self.tab_auto = self.tabview.add("Auto-Detected Sets")
        self.tab_manual = self.tabview.add("Manual Playlist Creator")

        self._build_auto_tab()
        self._build_manual_tab()

    # =========================================================================
    # TAB 1: AUTO DETECTED SETS
    # =========================================================================
    def _build_auto_tab(self):
        top_bar = ctk.CTkFrame(self.tab_auto, fg_color="transparent")
        top_bar.pack(fill="x", padx=8, pady=(4, 8))

        self.format_var = ctk.StringVar(value=".m3u")
        ctk.CTkLabel(top_bar, text="Playlist Extension:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))

        self.format_menu = ctk.CTkOptionMenu(
            top_bar,
            values=[".m3u (Recommended for RetroArch)", ".m3a"],
            width=230,
            command=self._on_format_changed
        )
        self.format_menu.pack(side="left", padx=4)

        self.subfolder_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            top_bar,
            text="Hide discs in subfolder",
            variable=self.subfolder_var
        ).pack(side="left", padx=12)

        self.create_all_btn = ctk.CTkButton(
            top_bar,
            text="Create All Playlists",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            command=self.create_all_playlists
        )
        self.create_all_btn.pack(side="right", padx=4)

        ctk.CTkButton(
            top_bar,
            text="Rescan",
            width=70,
            fg_color=("gray75", "gray28"),
            command=self.refresh_detected_sets
        ).pack(side="right", padx=4)

        # Scrollable Sets Container
        self.sets_scroll = ctk.CTkScrollableFrame(self.tab_auto, corner_radius=8)
        self.sets_scroll.pack(fill="both", expand=True, padx=4, pady=(0, 6))

    def _on_format_changed(self, selection: str):
        self.format_var.set(".m3u" if ".m3u" in selection else ".m3a")

    def refresh_detected_sets(self):
        for w in self.sets_scroll.winfo_children():
            w.destroy()

        self.detected_sets = m3u_manager.scan_library(settings.library_dir)

        if not self.detected_sets:
            box = ctk.CTkFrame(self.sets_scroll, fg_color="transparent")
            box.pack(pady=50)
            ctk.CTkLabel(
                box,
                text="No multi-disc sets found in your library.",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="gray60"
            ).pack(pady=4)
            ctk.CTkLabel(
                box,
                text="Download multi-disc titles (like Final Fantasy VII, Resident Evil 2, or Metal Gear Solid)\ninto your psx or disc folders, then click Rescan.",
                font=ctk.CTkFont(size=12),
                text_color="gray50",
                justify="center"
            ).pack()
            self.create_all_btn.configure(state="disabled")
            return

        self.create_all_btn.configure(state="normal")
        for set_info in self.detected_sets:
            self._render_set_row(set_info)

    def _render_set_row(self, s: MultiDiscSet):
        card = ctk.CTkFrame(self.sets_scroll, corner_radius=8, fg_color=("gray90", "gray18"))
        card.pack(fill="x", padx=4, pady=4)

        # Action / Status Buttons packed FIRST on right
        btn_box = ctk.CTkFrame(card, fg_color="transparent")
        btn_box.pack(side="right", padx=12, pady=8)

        if s.has_playlist:
            badge = ctk.CTkLabel(
                btn_box,
                text=f"✓ Playlist Ready ({s.playlist_extension})",
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color=("#d1fae5", "#064e3b"),
                text_color=("#065f46", "#6ee7b7"),
                corner_radius=6,
                padx=8,
                pady=4
            )
            badge.pack(side="left", padx=4)

            ctk.CTkButton(
                btn_box,
                text="Re-create",
                width=80,
                height=28,
                fg_color=("gray75", "gray28"),
                command=lambda set_i=s: self._create_single_playlist(set_i)
            ).pack(side="left", padx=2)
        else:
            ctk.CTkButton(
                btn_box,
                text="Create Playlist",
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#3b82f6",
                hover_color="#2563eb",
                height=28,
                command=lambda set_i=s: self._create_single_playlist(set_i)
            ).pack(side="left", padx=4)

        # Info Frame packed SECOND to fill remaining space
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=12, pady=8)

        ctk.CTkLabel(
            info,
            text=s.base_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        ).pack(fill="x")

        discs_detail = ", ".join(f.name for f in s.disc_files[:3])
        if len(s.disc_files) > 3:
            discs_detail += f" (+{len(s.disc_files) - 3} more)"

        sub_text = f"{s.console_code.upper()} • {s.disc_count} Discs ({s.size_str}) • {discs_detail}"
        ctk.CTkLabel(
            info,
            text=sub_text,
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            anchor="w"
        ).pack(fill="x")

    def _create_single_playlist(self, set_info: MultiDiscSet):
        ext = self.format_var.get()
        m3u_manager.create_playlist(
            set_info,
            extension=ext,
            organize_subfolder=self.subfolder_var.get()
        )
        self.refresh_detected_sets()
        if self.on_playlists_updated:
            self.on_playlists_updated()

    def create_all_playlists(self):
        ext = self.format_var.get()
        organize = self.subfolder_var.get()
        count = 0
        for s in self.detected_sets:
            m3u_manager.create_playlist(s, extension=ext, organize_subfolder=organize)
            count += 1

        self.refresh_detected_sets()
        if self.on_playlists_updated:
            self.on_playlists_updated()

    # =========================================================================
    # TAB 2: MANUAL PLAYLIST CREATOR
    # =========================================================================
    def _build_manual_tab(self):
        control_frame = ctk.CTkFrame(self.tab_manual, fg_color="transparent")
        control_frame.pack(fill="x", padx=8, pady=(4, 6))

        # 1. Console Selector
        ctk.CTkLabel(control_frame, text="Target Console:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        self.manual_console_menu = ctk.CTkOptionMenu(
            control_frame,
            values=["psx (PlayStation)", "segacd (Sega CD)", "dreamcast (Dreamcast)", "pcengine (PC Engine CD)"],
            width=200
        )
        self.manual_console_menu.pack(side="left", padx=4)

        # 2. Add Discs Button
        ctk.CTkButton(
            control_frame,
            text="+ Add Disc Files...",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=130,
            command=self._manual_add_files
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            control_frame,
            text="Clear",
            width=65,
            fg_color=("gray75", "gray28"),
            command=self._manual_clear_files
        ).pack(side="left", padx=2)

        # 3. Playlist Name
        name_frame = ctk.CTkFrame(self.tab_manual, fg_color="transparent")
        name_frame.pack(fill="x", padx=8, pady=4)

        ctk.CTkLabel(name_frame, text="Playlist Name:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        self.manual_name_entry = ctk.CTkEntry(
            name_frame,
            placeholder_text="e.g. Final Fantasy VII (USA)",
            width=320,
            height=30
        )
        self.manual_name_entry.pack(side="left", padx=4)

        self.manual_ext_menu = ctk.CTkOptionMenu(
            name_frame,
            values=[".m3u", ".m3a"],
            width=80
        )
        self.manual_ext_menu.pack(side="left", padx=4)

        # 4. Scrollable Reorderable List
        self.manual_scroll = ctk.CTkScrollableFrame(self.tab_manual, corner_radius=8)
        self.manual_scroll.pack(fill="both", expand=True, padx=4, pady=6)

        # 5. Bottom Generate Button
        bottom_row = ctk.CTkFrame(self.tab_manual, fg_color="transparent")
        bottom_row.pack(fill="x", padx=8, pady=(4, 6))

        self.manual_generate_btn = ctk.CTkButton(
            bottom_row,
            text="Generate Multi-Disc Playlist",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=34,
            command=self._generate_manual_playlist
        )
        self.manual_generate_btn.pack(side="right", padx=4)

        self._render_manual_list()

    def _manual_add_files(self):
        initial_dir = Path(settings.library_dir) / "psx"
        if not initial_dir.exists():
            initial_dir = Path(settings.library_dir)

        files = filedialog.askopenfilenames(
            title="Select Disc Files in Order",
            initialdir=str(initial_dir),
            filetypes=[
                ("Disc ROMs", "*.chd *.cue *.iso *.pbp *.bin *.img *.cdi *.gdi *.zip"),
                ("All Files", "*.*")
            ]
        )
        if files:
            for f in files:
                p = Path(f)
                if p not in self.manual_files:
                    self.manual_files.append(p)

            # Auto-suggest playlist name from first file
            if not self.manual_name_entry.get().strip() and self.manual_files:
                base, _, _ = m3u_manager.extract_disc_info(self.manual_files[0].name)
                self.manual_name_entry.insert(0, base or self.manual_files[0].stem)

            self._render_manual_list()

    def _manual_clear_files(self):
        self.manual_files.clear()
        self.manual_name_entry.delete(0, "end")
        self._render_manual_list()

    def _render_manual_list(self):
        for w in self.manual_scroll.winfo_children():
            w.destroy()

        if not self.manual_files:
            empty = ctk.CTkLabel(
                self.manual_scroll,
                text="No disc files added yet. Click '+ Add Disc Files...' to select files.",
                font=ctk.CTkFont(size=13),
                text_color="gray60"
            )
            empty.pack(pady=40)
            self.manual_generate_btn.configure(state="disabled")
            return

        self.manual_generate_btn.configure(state="normal")
        for i, fpath in enumerate(self.manual_files):
            row = ctk.CTkFrame(self.manual_scroll, corner_radius=6, fg_color=("gray90", "gray18"))
            row.pack(fill="x", padx=4, pady=2)

            ctk.CTkLabel(
                row,
                text=f"Disc {i + 1}:",
                font=ctk.CTkFont(size=12, weight="bold"),
                width=60,
                anchor="w"
            ).pack(side="left", padx=(10, 4))

            ctk.CTkLabel(
                row,
                text=fpath.name,
                font=ctk.CTkFont(size=12),
                anchor="w"
            ).pack(side="left", fill="x", expand=True, padx=4)

            # Move Up
            if i > 0:
                ctk.CTkButton(
                    row,
                    text="▲",
                    width=28,
                    height=24,
                    command=lambda idx=i: self._move_file(idx, idx - 1)
                ).pack(side="right", padx=2)

            # Move Down
            if i < len(self.manual_files) - 1:
                ctk.CTkButton(
                    row,
                    text="▼",
                    width=28,
                    height=24,
                    command=lambda idx=i: self._move_file(idx, idx + 1)
                ).pack(side="right", padx=2)

            # Delete
            ctk.CTkButton(
                row,
                text="✕",
                width=28,
                height=24,
                fg_color="#ef4444",
                hover_color="#dc2626",
                command=lambda idx=i: self._remove_file(idx)
            ).pack(side="right", padx=(2, 8))

    def _move_file(self, from_idx: int, to_idx: int):
        item = self.manual_files.pop(from_idx)
        self.manual_files.insert(to_idx, item)
        self._render_manual_list()

    def _remove_file(self, idx: int):
        self.manual_files.pop(idx)
        self._render_manual_list()

    def _generate_manual_playlist(self):
        name = self.manual_name_entry.get().strip()
        if not name or not self.manual_files:
            return

        c_choice = self.manual_console_menu.get().split()[0]
        target_dir = Path(settings.library_dir) / c_choice
        target_dir.mkdir(parents=True, exist_ok=True)

        ext = self.manual_ext_menu.get()

        set_info = MultiDiscSet(
            base_name=name,
            console_code=c_choice,
            folder_path=target_dir,
            disc_files=list(self.manual_files),
            disc_labels=[f"Disc {i+1}" for i in range(len(self.manual_files))],
            has_playlist=False,
            playlist_extension=ext
        )

        m3u_manager.create_playlist(set_info, extension=ext)

        self._manual_clear_files()
        self.tabview.set("Auto-Detected Sets")
        self.refresh_detected_sets()
        if self.on_playlists_updated:
            self.on_playlists_updated()
