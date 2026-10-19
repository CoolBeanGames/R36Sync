"""
Browse & Search View for R36Sync.
Allows browsing retro gaming systems and expanding/drilling down to browse all games within a system,
as well as instant archive-wide searching with 1-click downloading, disc numbers, and metadata filtering.
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
    """Unified Browse & Search View: Browse systems or search the entire Minerva Archive catalog."""

    def __init__(self, master, on_download_completed=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_download_completed = on_download_completed

        # Navigation state
        self.active_console: Optional[ConsoleDef] = None
        self.selected_letter: str = "ALL"
        self.exp_current_page: int = 0
        self.exp_total_games: int = 0
        self.exp_current_games: List[Dict[str, Any]] = []

        # Global search state
        self.search_current_page: int = 0
        self.search_total_results: int = 0
        self.search_current_results: List[Dict[str, Any]] = []

        self._search_timer: Optional[threading.Timer] = None
        self._has_loaded: bool = False

        # Build UI containers
        self._create_ui()

        # Listen to download queue updates
        downloader.subscribe(self._on_download_task_update)

    def on_tab_activated(self):
        """Called when user switches to Browse tab."""
        self.update_db_stat()
        if not self._has_loaded:
            self._has_loaded = True
            self.render_systems()
        else:
            if self.systems_container.winfo_ismapped():
                self.render_systems()
            elif self.explorer_container.winfo_ismapped():
                self._run_game_search()
            elif self.search_container.winfo_ismapped():
                self._run_global_search()

    def update_db_stat(self):
        """Refreshes total games cached stat badge."""
        try:
            total = db.get_total_rom_count()
            self.db_stat_badge.configure(text=f"Database: {total:,} games cached")
        except Exception:
            pass

    def _create_ui(self):
        # 1. Top Persistent Header Frame
        self.header_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
        self.header_frame.pack(fill="x", padx=12, pady=(10, 6))

        title_row = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        title_row.pack(fill="x", padx=14, pady=(8, 4))

        ctk.CTkLabel(
            title_row,
            text="Minerva Archive Catalog",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")

        # Mode Switcher (Browse Systems vs Search Archive)
        self.mode_switcher = ctk.CTkSegmentedButton(
            title_row,
            values=["Browse Systems", "Search Archive"],
            command=self._on_mode_switched,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=30
        )
        self.mode_switcher.pack(side="left", padx=16)
        self.mode_switcher.set("Browse Systems")

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

        # Filter & Search Controls Row
        search_row = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        search_row.pack(fill="x", padx=14, pady=(4, 10))

        self.search_entry = ctk.CTkEntry(
            search_row,
            placeholder_text="Search games across Minerva Archive (e.g. Thousand Arms, Mario)...",
            width=380,
            height=34
        )
        self.search_entry.pack(side="left", padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", self._on_search_key)

        self.console_dropdown = ctk.CTkOptionMenu(
            search_row,
            values=["All Systems"] + [c.display_name for c in CONSOLES.values()],
            command=self._on_console_dropdown_changed,
            width=210,
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

        # Active Download Banner
        self.dl_banner = ctk.CTkFrame(self, corner_radius=8, fg_color=("gray80", "gray20"))
        self.dl_banner.pack(fill="x", padx=12, pady=(0, 4))
        self.dl_banner.pack_forget()

        self.dl_lbl = ctk.CTkLabel(self.dl_banner, text="", font=ctk.CTkFont(size=12, weight="bold"))
        self.dl_lbl.pack(side="left", padx=10, pady=4)

        self.dl_prog = ctk.CTkProgressBar(self.dl_banner, width=180)
        self.dl_prog.pack(side="left", padx=10, pady=4)
        self.dl_prog.set(0)

        self.dl_speed_lbl = ctk.CTkLabel(self.dl_banner, text="", font=ctk.CTkFont(size=11), text_color="gray60")
        self.dl_speed_lbl.pack(side="left", padx=6, pady=4)

        # 2. Main View Containers
        self.systems_container = ctk.CTkFrame(self, fg_color="transparent")
        self.explorer_container = ctk.CTkFrame(self, fg_color="transparent")
        self.search_container = ctk.CTkFrame(self, fg_color="transparent")

        self._build_systems_view()
        self._build_game_explorer_view()
        self._build_search_results_view()

        # Show Systems List initially
        self.systems_container.pack(fill="both", expand=True)

    # =========================================================================
    # VIEW 1: SYSTEMS OVERVIEW (Browse Systems)
    # =========================================================================
    def _build_systems_view(self):
        sub_bar = ctk.CTkFrame(self.systems_container, fg_color="transparent")
        sub_bar.pack(fill="x", padx=14, pady=(2, 6))

        self.systems_count_badge = ctk.CTkLabel(
            sub_bar,
            text="22 Systems Available",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="gray60"
        )
        self.systems_count_badge.pack(side="left")

        ctk.CTkButton(
            sub_bar,
            text="Refresh Systems",
            width=110,
            height=28,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self.render_systems
        ).pack(side="right")

        self.systems_scroll = ctk.CTkScrollableFrame(self.systems_container, corner_radius=10)
        self.systems_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    def show_systems_view(self):
        """Displays the systems cards overview."""
        self.explorer_container.pack_forget()
        self.search_container.pack_forget()
        self.systems_container.pack(fill="both", expand=True)
        self.mode_switcher.set("Browse Systems")
        self.render_systems()

    def render_systems(self):
        """Populates system cards based on database and local library stats."""
        for w in self.systems_scroll.winfo_children():
            w.destroy()

        # Check if user entered filter in search entry while in systems view
        filter_text = self.search_entry.get().strip().lower()

        try:
            db_summary = {row["console_code"]: row["count"] for row in db.get_consoles_summary()}
        except Exception:
            db_summary = {}

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

        sorted_consoles = sorted(
            CONSOLES.values(),
            key=lambda c: (-db_summary.get(c.code, 0), c.display_name)
        )

        matching = []
        for c_def in sorted_consoles:
            if filter_text:
                if (filter_text not in c_def.display_name.lower() and
                    filter_text not in c_def.code.lower() and
                    filter_text not in c_def.minerva_group.lower()):
                    continue
            matching.append(c_def)

        self.systems_count_badge.configure(text=f"{len(matching)} Systems Available")

        if not matching:
            empty_box = ctk.CTkFrame(self.systems_scroll, fg_color="transparent")
            empty_box.pack(pady=40)
            ctk.CTkLabel(
                empty_box,
                text="No systems match your filter.",
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="gray60"
            ).pack(pady=4)

            ctk.CTkButton(
                empty_box,
                text="Search All Games in Archive",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color="#3b82f6",
                command=self.activate_search_mode
            ).pack(pady=8)
            return

        for c_def in matching:
            total_in_db = db_summary.get(c_def.code, 0)
            downloaded = lib_counts.get(c_def.code, 0)
            self._render_system_card(c_def, total_in_db, downloaded)

    def _render_system_card(self, c_def: ConsoleDef, total_in_db: int, downloaded: int):
        card = ctk.CTkFrame(self.systems_scroll, corner_radius=10, fg_color=("gray90", "gray18"))
        card.pack(fill="x", padx=6, pady=4)

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

        for widget in [card, info, title_lbl, status_lbl]:
            widget.bind("<Button-1>", lambda e, c=c_def: self.open_system_games(c))

    # =========================================================================
    # VIEW 2: GAME EXPLORER (Drill-down into a selected system)
    # =========================================================================
    def _build_game_explorer_view(self):
        exp_nav = ctk.CTkFrame(self.explorer_container, fg_color="transparent")
        exp_nav.pack(fill="x", padx=12, pady=(4, 4))

        self.back_btn = ctk.CTkButton(
            exp_nav,
            text="← Back to Systems",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=135,
            height=30,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self.back_to_systems
        )
        self.back_btn.pack(side="left", padx=(0, 10))

        self.current_system_lbl = ctk.CTkLabel(
            exp_nav,
            text="System Name",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.current_system_lbl.pack(side="left", padx=4)

        self.exp_count_badge = ctk.CTkLabel(
            exp_nav,
            text="0 Games",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("gray75", "gray25"),
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.exp_count_badge.pack(side="right")

        # Alphabetical A-Z Jumper Bar
        self.alphabet_frame = ctk.CTkFrame(self.explorer_container, fg_color="transparent")
        self.alphabet_frame.pack(fill="x", padx=12, pady=(2, 6))
        self.letter_buttons: Dict[str, ctk.CTkButton] = {}

        # Games List Scroll Frame
        self.games_scroll = ctk.CTkScrollableFrame(self.explorer_container, corner_radius=10)
        self.games_scroll.pack(fill="both", expand=True, padx=12, pady=(2, 6))

        # Pagination Footer
        exp_footer = ctk.CTkFrame(self.explorer_container, fg_color="transparent")
        exp_footer.pack(fill="x", padx=12, pady=(0, 8))

        self.exp_page_info_lbl = ctk.CTkLabel(exp_footer, text="Page 1 of 1", font=ctk.CTkFont(size=12))
        self.exp_page_info_lbl.pack(side="left", padx=6)

        self.exp_next_btn = ctk.CTkButton(exp_footer, text="Next >", width=70, height=28, command=self.exp_next_page)
        self.exp_next_btn.pack(side="right", padx=4)

        self.exp_prev_btn = ctk.CTkButton(exp_footer, text="< Prev", width=70, height=28, command=self.exp_prev_page)
        self.exp_prev_btn.pack(side="right", padx=4)

    def open_system_games(self, console_def: ConsoleDef):
        """Transitions into the expanded game browser for the chosen console."""
        self.active_console = console_def
        self.current_system_lbl.configure(text=f"{console_def.display_name} [{console_def.code.upper()}]")
        self.selected_letter = "ALL"
        self.exp_current_page = 0

        # Update console dropdown to reflect current selection
        self.console_dropdown.set(console_def.display_name)

        self._build_letter_bar()

        self.systems_container.pack_forget()
        self.search_container.pack_forget()
        self.explorer_container.pack(fill="both", expand=True)

        self._run_game_search()

    def back_to_systems(self):
        """Returns from drilled-down system explorer back to systems list."""
        self.active_console = None
        self.console_dropdown.set("All Systems")
        self.search_entry.delete(0, "end")
        self.show_systems_view()

    def _build_letter_bar(self):
        for w in self.alphabet_frame.winfo_children():
            w.destroy()
        self.letter_buttons.clear()

        if not self.active_console:
            return

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
        self.exp_current_page = 0
        for l, btn in self.letter_buttons.items():
            if l == letter:
                btn.configure(fg_color="#3b82f6", font=ctk.CTkFont(size=11, weight="bold"))
            else:
                btn.configure(fg_color=("gray75", "gray28"), font=ctk.CTkFont(size=11, weight="normal"))
        self._run_game_search()

    def exp_next_page(self):
        if (self.exp_current_page + 1) * PAGE_SIZE < self.exp_total_games:
            self.exp_current_page += 1
            self._run_game_search()

    def exp_prev_page(self):
        if self.exp_current_page > 0:
            self.exp_current_page -= 1
            self._run_game_search()

    def _run_game_search(self):
        if not self.active_console:
            return

        query = self.search_entry.get().strip()
        offset = self.exp_current_page * PAGE_SIZE
        code = self.active_console.code

        self.exp_total_games = db.count_games_by_console(
            console_code=code,
            letter=self.selected_letter,
            search=query if query else None
        )
        self.exp_current_games = db.get_games_by_console(
            console_code=code,
            letter=self.selected_letter,
            search=query if query else None,
            limit=PAGE_SIZE,
            offset=offset
        )

        self.after(0, self._render_explorer_games)

    def _render_explorer_games(self):
        total_p = max(1, (self.exp_total_games + PAGE_SIZE - 1) // PAGE_SIZE)
        cur_p = self.exp_current_page + 1
        self.exp_page_info_lbl.configure(text=f"Page {cur_p} of {total_p} • {self.exp_total_games:,} games")
        self.exp_count_badge.configure(text=f"{self.exp_total_games:,} Games")
        self.exp_prev_btn.configure(state="normal" if self.exp_current_page > 0 else "disabled")
        self.exp_next_btn.configure(state="normal" if cur_p < total_p else "disabled")

        for w in self.games_scroll.winfo_children():
            w.destroy()

        if not self.exp_current_games:
            box = ctk.CTkFrame(self.games_scroll, fg_color="transparent")
            box.pack(pady=40)
            ctk.CTkLabel(
                box,
                text="No games found matching the selected letter / query.",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="gray60"
            ).pack()
            return

        for rom in self.exp_current_games:
            self._render_rom_row(self.games_scroll, rom)

        try:
            self.games_scroll._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    # =========================================================================
    # VIEW 3: SEARCH RESULTS (Global / Archive-wide search)
    # =========================================================================
    def _build_search_results_view(self):
        nav_row = ctk.CTkFrame(self.search_container, fg_color="transparent")
        nav_row.pack(fill="x", padx=14, pady=(4, 4))

        self.search_info_lbl = ctk.CTkLabel(
            nav_row,
            text="0 results found in stored database",
            font=ctk.CTkFont(size=12),
            text_color="gray60"
        )
        self.search_info_lbl.pack(side="left")

        # Top Pagination
        self.search_next_btn = ctk.CTkButton(
            nav_row,
            text="Next >",
            width=70,
            height=26,
            command=self.search_next_page
        )
        self.search_next_btn.pack(side="right", padx=4)

        self.search_page_lbl = ctk.CTkLabel(
            nav_row,
            text="Page 1",
            font=ctk.CTkFont(size=12)
        )
        self.search_page_lbl.pack(side="right", padx=8)

        self.search_prev_btn = ctk.CTkButton(
            nav_row,
            text="< Prev",
            width=70,
            height=26,
            command=self.search_prev_page
        )
        self.search_prev_btn.pack(side="right", padx=4)

        # Scroll Frame for search results
        self.search_scroll = ctk.CTkScrollableFrame(self.search_container, corner_radius=10)
        self.search_scroll.pack(fill="both", expand=True, padx=12, pady=(2, 10))

    def show_search_view(self):
        """Displays global archive search results view."""
        self.systems_container.pack_forget()
        self.explorer_container.pack_forget()
        self.search_container.pack(fill="both", expand=True)
        self.mode_switcher.set("Search Archive")

    def activate_search_mode(self, query: str = ""):
        """Public helper to activate search view directly with optional initial query."""
        self.show_search_view()
        if query:
            self.search_entry.delete(0, "end")
            self.search_entry.insert(0, query)
        self.search_entry.focus()
        self._run_global_search()

    def search_next_page(self):
        if (self.search_current_page + 1) * PAGE_SIZE < self.search_total_results:
            self.search_current_page += 1
            self._run_global_search()

    def search_prev_page(self):
        if self.search_current_page > 0:
            self.search_current_page -= 1
            self._run_global_search()

    def _run_global_search(self):
        query = self.search_entry.get().strip()
        console_sel = self.console_dropdown.get()

        selected_code = None
        if console_sel != "All Systems":
            for code, c_def in CONSOLES.items():
                if c_def.display_name == console_sel:
                    selected_code = code
                    break

        offset = self.search_current_page * PAGE_SIZE
        self.search_total_results = db.count_search_results(query=query, console_code=selected_code)
        self.search_current_results = db.search_roms(
            query=query,
            console_code=selected_code,
            limit=PAGE_SIZE,
            offset=offset
        )

        self.after(0, self._render_search_results)

    def _render_search_results(self):
        total_p = max(1, (self.search_total_results + PAGE_SIZE - 1) // PAGE_SIZE)
        cur_p = self.search_current_page + 1

        self.search_page_lbl.configure(text=f"Page {cur_p} of {total_p}")
        self.search_prev_btn.configure(state="normal" if self.search_current_page > 0 else "disabled")
        self.search_next_btn.configure(state="normal" if cur_p < total_p else "disabled")

        query = self.search_entry.get().strip()
        if query:
            self.search_info_lbl.configure(text=f"Found {self.search_total_results:,} games matching '{query}'")
        else:
            self.search_info_lbl.configure(text=f"{self.search_total_results:,} games in catalog")

        for w in self.search_scroll.winfo_children():
            w.destroy()

        if not self.search_current_results:
            box = ctk.CTkFrame(self.search_scroll, fg_color="transparent")
            box.pack(pady=50)

            total_db = db.get_total_rom_count()
            if total_db == 0:
                msg = "The stored Minerva Archive database is currently empty."
                sub_msg = "Minerva Archive will automatically index ROMs on launch,\nor you can visit the Minerva Database tab to scan now."
            else:
                msg = "No games matched your search criteria."
                sub_msg = "Try searching for a different title or select 'All Systems'."

            ctk.CTkLabel(box, text=msg, font=ctk.CTkFont(size=16, weight="bold"), text_color="gray60").pack(pady=4)
            ctk.CTkLabel(box, text=sub_msg, font=ctk.CTkFont(size=13), text_color="gray50").pack(pady=4)
            return

        for rom in self.search_current_results:
            self._render_rom_row(self.search_scroll, rom)

        try:
            self.search_scroll._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    # =========================================================================
    # UNIFIED ROM ROW RENDERING (Shared by Explorer & Search)
    # =========================================================================
    def _render_rom_row(self, scroll_parent: ctk.CTkScrollableFrame, rom: Dict[str, Any]):
        row = ctk.CTkFrame(scroll_parent, corner_radius=8, height=54, fg_color=("gray90", "gray18"))
        row.pack(fill="x", padx=4, pady=3)
        row.pack_propagate(False)

        title = rom.get("title", rom.get("file_name", ""))
        if len(title) > 65:
            title = title[:62] + "..."

        c_code = rom.get("console_code", "")
        c_name = rom.get("console_name", "")
        f_name = rom.get("file_name", "")
        size_str = rom.get("size_str", "")
        region, lang = parse_rom_region_and_language(f_name)
        disc_num = parse_rom_disc_number(f_name)

        # Check if already downloaded (either as archive or extracted file)
        console_lib_dir = Path(settings.library_dir) / c_code
        stem_lower = Path(f_name).stem.lower()
        is_downloaded = (console_lib_dir / f_name).exists()
        if not is_downloaded and console_lib_dir.exists():
            for f in console_lib_dir.iterdir():
                if f.stem.lower() == stem_lower and f.suffix.lower() not in [".torrent", ".magnet"]:
                    is_downloaded = True
                    break

        # Action button container packed FIRST so it stays pinned to the right edge within window
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

        # Info Frame packed SECOND to take up remaining horizontal space
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=10, pady=6)

        ctk.CTkLabel(
            info,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w"
        ).pack(fill="x")

        # Second line: Console name • Disc number (if multi-disc) • Region • Language • Size
        meta_parts = [c_name]
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

    # =========================================================================
    # SEARCH & FILTER INTERACTION (Search as a live filter)
    # =========================================================================
    def _on_search_key(self, event=None):
        if self._search_timer:
            self._search_timer.cancel()

        def do_filter():
            query = self.search_entry.get().strip()
            # If user types search text while looking at systems overview, auto-switch to search results!
            if query and self.systems_container.winfo_ismapped():
                self.show_search_view()
                self._run_global_search()
            elif self.explorer_container.winfo_ismapped():
                self.exp_current_page = 0
                self._run_game_search()
            elif self.search_container.winfo_ismapped():
                self.search_current_page = 0
                self._run_global_search()
            elif not query and self.mode_switcher.get() == "Browse Systems":
                self.show_systems_view()

        self._search_timer = threading.Timer(0.15, do_filter)
        self._search_timer.start()

    def _on_console_dropdown_changed(self, value: str):
        if value == "All Systems":
            if self.explorer_container.winfo_ismapped():
                self.back_to_systems()
            elif self.search_container.winfo_ismapped():
                self.search_current_page = 0
                self._run_global_search()
        else:
            # Find selected console
            for code, c_def in CONSOLES.items():
                if c_def.display_name == value:
                    self.open_system_games(c_def)
                    break

    def _on_mode_switched(self, mode: str):
        if mode == "Browse Systems":
            self.show_systems_view()
        elif mode == "Search Archive":
            self.show_search_view()
            self._run_global_search()

    def clear_search(self):
        self.search_entry.delete(0, "end")
        if self.explorer_container.winfo_ismapped():
            self.exp_current_page = 0
            self._run_game_search()
        elif self.search_container.winfo_ismapped():
            self.search_current_page = 0
            self._run_global_search()
        else:
            self.render_systems()

    # =========================================================================
    # DOWNLOAD & OPTIONS LOGIC
    # =========================================================================
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
                self.dl_banner.pack(fill="x", padx=12, pady=(0, 4), before=self.systems_container if self.systems_container.winfo_ismapped() else (self.explorer_container if self.explorer_container.winfo_ismapped() else self.search_container))
                f_name = task.rom_data.get("file_name", "")
                self.dl_lbl.configure(text=f"Downloading: {f_name[:32]}...")
                self.dl_prog.set(task.progress)
                self.dl_speed_lbl.configure(text=f"{task.speed} ({int(task.progress * 100)}%)")
            elif task.status == "Completed":
                self.dl_lbl.configure(text="Download Complete! Extracted & cover art saved.")
                self.dl_prog.set(1.0)
                self.dl_speed_lbl.configure(text="Done")
                self.after(3000, lambda: self.dl_banner.pack_forget())
                if self.explorer_container.winfo_ismapped():
                    self._render_explorer_games()
                elif self.search_container.winfo_ismapped():
                    self._render_search_results()
                elif self.systems_container.winfo_ismapped():
                    self.render_systems()
                if self.on_download_completed:
                    self.on_download_completed()
            elif task.status == "Failed":
                self.dl_lbl.configure(text=f"Download Error: {task.error_msg}")
                self.after(4000, lambda: self.dl_banner.pack_forget())
        self.after(0, update)
