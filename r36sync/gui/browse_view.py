"""
Browse View for R36Sync.
Allows browsing retro gaming systems and expanding/drilling down to browse all games within a system.
Features alphabetical A-Z jumping, instant filtering, and 1-click downloads with cover art.
"""
import os
from pathlib import Path
import threading
from typing import Dict, List, Optional, Any
import customtkinter as ctk

from ..config import CONSOLES, ConsoleDef, settings
from ..database import db, parse_rom_region_and_language, parse_rom_disc_number
from ..downloader import downloader, DownloadTask


PAGE_SIZE = 50

# Console branding color accents
CONSOLE_COLORS = {
    "gba": ("#4f46e5", "#3730a3"),
    "gbc": ("#06b6d4", "#0e7490"),
    "gb": ("#10b981", "#047857"),
    "snes": ("#8b5cf6", "#6d28d9"),
    "nes": ("#ef4444", "#b91c1c"),
    "megadrive": ("#f59e0b", "#b45309"),
    "n64": ("#10b981", "#065f46"),
    "psx": ("#3b82f6", "#1d4ed8"),
    "nds": ("#ec4899", "#be185d"),
    "gamegear": ("#0284c7", "#0369a1"),
    "mastersystem": ("#6366f1", "#4338ca"),
    "sega32x": ("#f97316", "#c2410c"),
    "pcengine": ("#eab308", "#a16207"),
    "ngpc": ("#14b8a6", "#0f766e"),
    "wonderswan": ("#84cc16", "#4d7c0f"),
    "atari2600": ("#a855f7", "#7e22ce")
}


class BrowseView(ctk.CTkFrame):
    """Browse Tab: Browse by System -> Expand to browse by Game."""

    def __init__(self, master, on_download_completed=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_download_completed = on_download_completed

        # Current navigation state
        self.active_console: Optional[ConsoleDef] = None
        self.selected_letter: str = "ALL"
        self.current_page: int = 0
        self.total_games_in_view: int = 0
        self.current_games: List[Dict[str, Any]] = []
        self._search_timer: Optional[threading.Timer] = None

        self._has_loaded: bool = False

        # Build UI containers
        self._create_ui()

        # Listen to download queue updates
        downloader.subscribe(self._on_download_task_update)

    def on_tab_activated(self):
        """Called when user switches to Browse tab."""
        if not self._has_loaded:
            self._has_loaded = True
            self.render_systems()
        else:
            if self.systems_container.winfo_ismapped():
                self.render_systems()

    def _create_ui(self):
        # 1. Main View Containers: Systems List vs Game Explorer
        self.systems_container = ctk.CTkFrame(self, fg_color="transparent")
        self.explorer_container = ctk.CTkFrame(self, fg_color="transparent")

        self._build_systems_view()
        self._build_game_explorer_view()

        # Show Systems List initially (container only, defer rendering until tab active)
        self.systems_container.pack(fill="both", expand=True)

    # =========================================================================
    # VIEW 1: SYSTEMS LIST (Browse by System)
    # =========================================================================
    def _build_systems_view(self):
        # Header Card
        header = ctk.CTkFrame(self.systems_container, corner_radius=10, fg_color=("gray85", "gray17"))
        header.pack(fill="x", padx=12, pady=(10, 6))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            title_row,
            text="Browse Archives by System",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")

        self.systems_count_badge = ctk.CTkLabel(
            title_row,
            text="22 Systems Available",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("gray75", "gray25"),
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.systems_count_badge.pack(side="right")

        # Search / Filter Bar for Systems
        filter_row = ctk.CTkFrame(header, fg_color="transparent")
        filter_row.pack(fill="x", padx=14, pady=(4, 10))

        self.system_search_entry = ctk.CTkEntry(
            filter_row,
            placeholder_text="Filter systems (e.g. Nintendo, Sega, Sony, Game Boy)...",
            width=360,
            height=34
        )
        self.system_search_entry.pack(side="left", padx=(0, 10))
        self.system_search_entry.bind("<KeyRelease>", lambda e: self.render_systems())

        ctk.CTkButton(
            filter_row,
            text="Refresh",
            width=80,
            height=34,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self.render_systems
        ).pack(side="left")

        # Scrollable Systems Grid Frame
        self.systems_scroll = ctk.CTkScrollableFrame(self.systems_container, corner_radius=10)
        self.systems_scroll.pack(fill="both", expand=True, padx=12, pady=(4, 10))

    def show_systems_view(self):
        """Displays the systems grid view."""
        self.explorer_container.pack_forget()
        self.systems_container.pack(fill="both", expand=True)
        self.render_systems()

    def render_systems(self):
        """Populates system cards based on database stats."""
        for w in self.systems_scroll.winfo_children():
            w.destroy()

        filter_text = self.system_search_entry.get().strip().lower()

        # Get DB summary
        db_summary = {row["console_code"]: row["count"] for row in db.get_consoles_summary()}

        # Scan local library to count downloaded games per console
        lib_path = Path(settings.library_dir)
        lib_counts = {}
        for code in CONSOLES.keys():
            c_dir = lib_path / code
            if c_dir.exists():
                try:
                    count = len([f for f in c_dir.iterdir() if f.is_file() and not f.name.endswith(('.png', '.jpg', '.torrent', '.magnet'))])
                    lib_counts[code] = count
                except Exception:
                    lib_counts[code] = 0

        # Sort consoles: systems with cached games first, then by name
        sorted_consoles = sorted(
            CONSOLES.values(),
            key=lambda c: (-db_summary.get(c.code, 0), c.display_name)
        )

        matching_consoles = []
        for c_def in sorted_consoles:
            if filter_text:
                if (filter_text not in c_def.display_name.lower() and
                    filter_text not in c_def.code.lower() and
                    filter_text not in c_def.minerva_group.lower()):
                    continue
            matching_consoles.append(c_def)

        self.systems_count_badge.configure(text=f"{len(matching_consoles)} Systems Found")

        if not matching_consoles:
            empty_box = ctk.CTkFrame(self.systems_scroll, fg_color="transparent")
            empty_box.pack(pady=40)
            ctk.CTkLabel(
                empty_box,
                text="No systems match your filter.",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="gray60"
            ).pack()
            return

        for c_def in matching_consoles:
            total_in_db = db_summary.get(c_def.code, 0)
            downloaded = lib_counts.get(c_def.code, 0)
            self._render_system_card(c_def, total_in_db, downloaded)

    def _render_system_card(self, c_def: ConsoleDef, total_in_db: int, downloaded: int):
        card = ctk.CTkFrame(self.systems_scroll, corner_radius=10, fg_color=("gray90", "gray18"))
        card.pack(fill="x", padx=6, pady=4)

        # Color Accent Badge
        accent_color = CONSOLE_COLORS.get(c_def.code, ("#3b82f6", "#1d4ed8"))[0]
        badge = ctk.CTkLabel(
            card,
            text=c_def.code.upper(),
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=accent_color,
            text_color="#ffffff",
            corner_radius=6,
            width=60,
            height=36
        )
        badge.pack(side="left", padx=(12, 10), pady=10)

        # Action: Expand / Browse Button packed FIRST on right
        browse_btn = ctk.CTkButton(
            card,
            text="Browse Games →" if total_in_db > 0 else "Scan & Browse",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=130,
            height=32,
            fg_color=accent_color,
            hover_color=CONSOLE_COLORS.get(c_def.code, ("#2563eb", "#1e40af"))[1],
            command=lambda c=c_def: self.open_system_games(c)
        )
        browse_btn.pack(side="right", padx=12, pady=10)

        # Info Frame packed SECOND to occupy remaining space
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, pady=8)

        title_lbl = ctk.CTkLabel(
            info,
            text=c_def.display_name,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w"
        )
        title_lbl.pack(fill="x")

        status_parts = []
        if total_in_db > 0:
            status_parts.append(f"{total_in_db:,} games in catalog")
        else:
            status_parts.append("Not yet scanned")

        if downloaded > 0:
            status_parts.append(f"✓ {downloaded} in Library")

        status_lbl = ctk.CTkLabel(
            info,
            text=" • ".join(status_parts),
            font=ctk.CTkFont(size=12),
            text_color="#10b981" if downloaded > 0 else "gray60",
            anchor="w"
        )
        status_lbl.pack(fill="x")

        # Make entire card clickable
        for widget in [card, info, title_lbl, status_lbl]:
            widget.bind("<Button-1>", lambda e, c=c_def: self.open_system_games(c))

    # =========================================================================
    # VIEW 2: GAME EXPLORER (Browse by Game inside selected System)
    # =========================================================================
    def _build_game_explorer_view(self):
        # 1. Explorer Header
        self.exp_header = ctk.CTkFrame(self.explorer_container, corner_radius=10, fg_color=("gray85", "gray17"))
        self.exp_header.pack(fill="x", padx=12, pady=(10, 6))

        top_row = ctk.CTkFrame(self.exp_header, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(10, 4))

        # Back Button
        self.back_btn = ctk.CTkButton(
            top_row,
            text="← Back to Systems",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=140,
            height=32,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self.show_systems_view
        )
        self.back_btn.pack(side="left", padx=(0, 10))

        self.current_system_lbl = ctk.CTkLabel(
            top_row,
            text="Game Boy Advance",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.current_system_lbl.pack(side="left", padx=4)

        self.exp_count_badge = ctk.CTkLabel(
            top_row,
            text="0 Games",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("gray75", "gray25"),
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.exp_count_badge.pack(side="right")

        # Search Bar inside System
        search_row = ctk.CTkFrame(self.exp_header, fg_color="transparent")
        search_row.pack(fill="x", padx=14, pady=(4, 6))

        self.game_search_entry = ctk.CTkEntry(
            search_row,
            placeholder_text="Filter games in this system...",
            width=320,
            height=32
        )
        self.game_search_entry.pack(side="left", padx=(0, 8))
        self.game_search_entry.bind("<KeyRelease>", self._on_game_search_key)

        ctk.CTkButton(
            search_row,
            text="Clear",
            width=65,
            height=32,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self._clear_game_search
        ).pack(side="left", padx=2)

        # 2. Alphabetical A-Z Jumper Bar
        self.alphabet_frame = ctk.CTkFrame(self.exp_header, fg_color="transparent")
        self.alphabet_frame.pack(fill="x", padx=14, pady=(2, 10))
        self.letter_buttons: Dict[str, ctk.CTkButton] = {}

        # 3. Active Download Banner (in explorer view)
        self.dl_banner = ctk.CTkFrame(self.explorer_container, corner_radius=8, fg_color=("gray80", "gray20"))
        self.dl_banner.pack(fill="x", padx=12, pady=(0, 4))
        self.dl_banner.pack_forget()

        self.dl_lbl = ctk.CTkLabel(self.dl_banner, text="", font=ctk.CTkFont(size=12, weight="bold"))
        self.dl_lbl.pack(side="left", padx=10, pady=4)

        self.dl_prog = ctk.CTkProgressBar(self.dl_banner, width=180)
        self.dl_prog.pack(side="left", padx=10, pady=4)
        self.dl_prog.set(0)

        # 4. Games List Scroll Frame
        self.games_scroll = ctk.CTkScrollableFrame(self.explorer_container, corner_radius=10)
        self.games_scroll.pack(fill="both", expand=True, padx=12, pady=(2, 6))

        # 5. Pagination Footer
        nav_footer = ctk.CTkFrame(self.explorer_container, fg_color="transparent")
        nav_footer.pack(fill="x", padx=12, pady=(0, 8))

        self.page_info_lbl = ctk.CTkLabel(nav_footer, text="Page 1 of 1", font=ctk.CTkFont(size=12))
        self.page_info_lbl.pack(side="left", padx=6)

        self.next_btn = ctk.CTkButton(nav_footer, text="Next >", width=70, height=28, command=self.next_page)
        self.next_btn.pack(side="right", padx=4)

        self.prev_btn = ctk.CTkButton(nav_footer, text="< Prev", width=70, height=28, command=self.prev_page)
        self.prev_btn.pack(side="right", padx=4)

    def open_system_games(self, console_def: ConsoleDef):
        """Transitions into the expanded game browser for the chosen console."""
        self.active_console = console_def
        self.current_system_lbl.configure(text=f"{console_def.display_name} [{console_def.code.upper()}]")
        self.selected_letter = "ALL"
        self.current_page = 0
        self.game_search_entry.delete(0, "end")

        # Build dynamic A-Z letters bar
        self._build_letter_bar()

        # Switch view
        self.systems_container.pack_forget()
        self.explorer_container.pack(fill="both", expand=True)

        self._run_game_search()

    def _build_letter_bar(self):
        """Constructs the A-Z jumper bar based on letters present in the system."""
        for w in self.alphabet_frame.winfo_children():
            w.destroy()
        self.letter_buttons.clear()

        if not self.active_console:
            return

        available_letters = db.get_console_letters(self.active_console.code)
        all_letters = ["ALL", "#"] + [chr(i) for i in range(ord('A'), ord('Z') + 1)]

        for letter in all_letters:
            is_active = (letter == self.selected_letter)
            fg = "#3b82f6" if is_active else ("gray75", "gray28")

            btn = ctk.CTkButton(
                self.alphabet_frame,
                text=letter,
                width=28,
                height=24,
                font=ctk.CTkFont(size=11, weight="bold" if is_active else "normal"),
                fg_color=fg,
                hover_color=("#2563eb", "#1d4ed8"),
                command=lambda l=letter: self.select_letter(l)
            )
            btn.pack(side="left", padx=1, pady=2)
            self.letter_buttons[letter] = btn

    def select_letter(self, letter: str):
        self.selected_letter = letter
        self.current_page = 0
        # Update button styles
        for l, btn in self.letter_buttons.items():
            if l == letter:
                btn.configure(fg_color="#3b82f6", font=ctk.CTkFont(size=11, weight="bold"))
            else:
                btn.configure(fg_color=("gray75", "gray28"), font=ctk.CTkFont(size=11, weight="normal"))
        self._run_game_search()

    def _on_game_search_key(self, event):
        if self._search_timer:
            self._search_timer.cancel()
        self._search_timer = threading.Timer(0.15, self._run_game_search)
        self._search_timer.start()

    def _clear_game_search(self):
        self.game_search_entry.delete(0, "end")
        self.current_page = 0
        self._run_game_search()

    def next_page(self):
        if (self.current_page + 1) * PAGE_SIZE < self.total_games_in_view:
            self.current_page += 1
            self._run_game_search()

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._run_game_search()

    def _run_game_search(self):
        if not self.active_console:
            return

        query = self.game_search_entry.get().strip()
        offset = self.current_page * PAGE_SIZE
        code = self.active_console.code

        self.total_games_in_view = db.count_games_by_console(
            console_code=code,
            letter=self.selected_letter,
            search=query if query else None
        )
        self.current_games = db.get_games_by_console(
            console_code=code,
            letter=self.selected_letter,
            search=query if query else None,
            limit=PAGE_SIZE,
            offset=offset
        )

        self.after(0, self._render_games)

    def _render_games(self):
        total_p = max(1, (self.total_games_in_view + PAGE_SIZE - 1) // PAGE_SIZE)
        cur_p = self.current_page + 1
        self.page_info_lbl.configure(text=f"Page {cur_p} of {total_p} • {self.total_games_in_view:,} games")
        self.exp_count_badge.configure(text=f"{self.total_games_in_view:,} Games")
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_btn.configure(state="normal" if cur_p < total_p else "disabled")

        for w in self.games_scroll.winfo_children():
            w.destroy()

        if not self.current_games:
            box = ctk.CTkFrame(self.games_scroll, fg_color="transparent")
            box.pack(pady=40)
            ctk.CTkLabel(
                box,
                text="No games found matching the selected letter / query.",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="gray60"
            ).pack()
            return

        lib_dir = Path(settings.library_dir) / self.active_console.code

        for rom in self.current_games:
            self._render_game_row(rom, lib_dir)

        try:
            self.games_scroll._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _render_game_row(self, rom: Dict[str, Any], console_lib_dir: Path):
        row = ctk.CTkFrame(self.games_scroll, corner_radius=8, height=54, fg_color=("gray90", "gray18"))
        row.pack(fill="x", padx=4, pady=3)
        row.pack_propagate(False)

        title = rom.get("title", rom.get("file_name", ""))
        if len(title) > 65:
            title = title[:62] + "..."

        f_name = rom.get("file_name", "")
        size_str = rom.get("size_str", "")
        region, lang = parse_rom_region_and_language(f_name)
        disc_num = parse_rom_disc_number(f_name)

        # Check if already downloaded (either as archive or extracted file)
        stem_lower = Path(f_name).stem.lower()
        is_downloaded = (console_lib_dir / f_name).exists()
        if not is_downloaded and console_lib_dir.exists():
            for f in console_lib_dir.iterdir():
                if f.stem.lower() == stem_lower and f.suffix.lower() not in [".torrent", ".magnet"]:
                    is_downloaded = True
                    break

        # Action button container packed FIRST so it stays pinned to the right edge
        btn_box = ctk.CTkFrame(row, fg_color="transparent")
        btn_box.pack(side="right", padx=10, pady=6)

        if is_downloaded:
            badge = ctk.CTkLabel(
                btn_box,
                text="✓ In Library",
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
                btn_box,
                text="Download to Library",
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#3b82f6",
                hover_color="#2563eb",
                height=30,
                command=lambda r=rom: self.download_game(r)
            )
            dl_btn.pack(side="left", padx=4)

        opt_btn = ctk.CTkButton(
            btn_box,
            text="•••",
            width=32,
            height=30,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=lambda r=rom: self._show_rom_options(r)
        )
        opt_btn.pack(side="left", padx=2)

        # Info Frame packed SECOND to take up remaining space cleanly
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=10, pady=6)

        ctk.CTkLabel(
            info,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        ).pack(fill="x")

        meta_parts = []
        if disc_num:
            meta_parts.append(f"Disc: {disc_num}")
        meta_parts.extend([f"Region: {region}", f"Lang: {lang}", size_str])
        sub_text = " • ".join(meta_parts)

        ctk.CTkLabel(
            info,
            text=sub_text,
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            anchor="w"
        ).pack(fill="x")

    def download_game(self, rom: Dict[str, Any]):
        downloader.enqueue_download(rom)

    def _show_rom_options(self, rom: Dict[str, Any]):
        top = ctk.CTkToplevel(self)
        top.title(rom.get("title", "Game Options"))
        top.geometry("450x260")
        top.transient(self.winfo_toplevel())
        top.grab_set()

        ctk.CTkLabel(top, text=rom.get("title", ""), font=ctk.CTkFont(size=14, weight="bold"), wraplength=400).pack(pady=(16, 6))
        ctk.CTkLabel(top, text=f"File: {rom.get('file_name')}\nConsole: {rom.get('console_name')} • Size: {rom.get('size_str')}", font=ctk.CTkFont(size=12), text_color="gray60").pack(pady=4)

        btn_box = ctk.CTkFrame(top, fg_color="transparent")
        btn_box.pack(pady=12)

        def save_torrent():
            cache_dir = Path(settings.library_dir) / ".cache"
            fname = Path(rom.get("file_name", "game")).stem + ".torrent"
            save_path = cache_dir / fname
            downloader.download_torrent_file_only(rom, save_path)
            try:
                os.startfile(str(cache_dir))
            except Exception:
                pass
            top.destroy()

        ctk.CTkButton(btn_box, text="Save .torrent File", width=160, command=save_torrent).pack(pady=4)

        def open_magnet():
            downloader.open_magnet_link(rom.get("magnet_url", ""))
            top.destroy()

        ctk.CTkButton(btn_box, text="Open Magnet Link", width=160, command=open_magnet).pack(pady=4)

        def open_minerva():
            import webbrowser
            webbrowser.open(rom.get("rom_url") or "https://minerva-archive.org")
            top.destroy()

        ctk.CTkButton(btn_box, text="Open Minerva Page", width=160, fg_color=("gray75", "gray28"), command=open_minerva).pack(pady=4)

    def _on_download_task_update(self, task: DownloadTask):
        def update():
            if task.status == "Downloading":
                self.dl_banner.pack(fill="x", padx=12, pady=(0, 4), before=self.games_scroll)
                f_name = task.rom_data.get("file_name", "")
                self.dl_lbl.configure(text=f"Downloading: {f_name[:32]}... ({task.speed})")
                self.dl_prog.set(task.progress)
            elif task.status == "Completed":
                self.dl_lbl.configure(text="Download Complete! Cover art saved.")
                self.dl_prog.set(1.0)
                self.after(3000, lambda: self.dl_banner.pack_forget())
                self._render_games()
                if self.on_download_completed:
                    self.on_download_completed()
            elif task.status == "Failed":
                self.dl_lbl.configure(text=f"Download Error: {task.error_msg}")
                self.after(4000, lambda: self.dl_banner.pack_forget())
        self.after(0, update)
