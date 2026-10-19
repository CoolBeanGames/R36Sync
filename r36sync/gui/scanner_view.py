"""
Minerva Archive Database Manager View for R36Sync.
Displays database statistics, console indexing coverage, and manual scanning controls.
"""
from pathlib import Path
import threading
from typing import Dict, List, Optional
import customtkinter as ctk

from ..config import CONSOLES, DB_FILE
from ..database import db
from ..minerva_scanner import scanner


class ScannerView(ctk.CTkFrame):
    """Minerva Database Tab: Controls background indexing of https://minerva-archive.org/"""

    def __init__(self, master, on_db_updated=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_db_updated = on_db_updated
        self._create_ui()
        self.refresh_stats()

    def _create_ui(self):
        # 1. Header Card
        header = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
        header.pack(fill="x", padx=12, pady=(10, 6))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            title_row,
            text="Minerva Archive Database Status",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")

        self.scan_btn = ctk.CTkButton(
            title_row,
            text="Scan Minerva Archive",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#3b82f6",
            hover_color="#2563eb",
            command=self.start_scan
        )
        self.scan_btn.pack(side="right")

        # Stats summary
        self.stats_label = ctk.CTkLabel(
            header,
            text="Total Games Cached: 0   •   Database Size: 0 MB",
            font=ctk.CTkFont(size=13),
            text_color="gray70",
            anchor="w"
        )
        self.stats_label.pack(fill="x", padx=14, pady=4)

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(header, height=12)
        self.progress_bar.pack(fill="x", padx=14, pady=(6, 4))
        self.progress_bar.set(0)

        self.status_detail_lbl = ctk.CTkLabel(
            header,
            text="Ready to scan. The stored database is searched offline during downloads.",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            anchor="w"
        )
        self.status_detail_lbl.pack(fill="x", padx=14, pady=(0, 10))

        # 2. Consoles Coverage Table
        content = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
        content.pack(fill="both", expand=True, padx=12, pady=(6, 10))

        c_header = ctk.CTkFrame(content, fg_color="transparent")
        c_header.pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkLabel(
            c_header,
            text="Indexed Systems Coverage",
            font=ctk.CTkFont(size=15, weight="bold")
        ).pack(side="left")

        ctk.CTkButton(
            c_header,
            text="Refresh Summary",
            width=120,
            command=self.refresh_stats
        ).pack(side="right")

        self.scroll_table = ctk.CTkScrollableFrame(content, corner_radius=8)
        self.scroll_table.pack(fill="both", expand=True, padx=14, pady=(0, 10))

    def refresh_stats(self):
        """Updates total counts and console rows."""
        total = db.get_total_rom_count()
        db_size_mb = (DB_FILE.stat().st_size / (1024 * 1024)) if DB_FILE.exists() else 0.0

        self.stats_label.configure(
            text=f"Total Games Stored: {total:,}   •   Local Database Size: {db_size_mb:.2f} MB"
        )

        for w in self.scroll_table.winfo_children():
            w.destroy()

        summary_map = {row["console_code"]: row["count"] for row in db.get_consoles_summary()}

        for code, c_def in CONSOLES.items():
            count = summary_map.get(code, 0)
            self._render_console_row(code, c_def.display_name, count)

    def _render_console_row(self, code: str, name: str, count: int):
        row = ctk.CTkFrame(self.scroll_table, fg_color=("gray90", "gray18"), corner_radius=6)
        row.pack(fill="x", padx=4, pady=2)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=10, pady=4)

        ctk.CTkLabel(
            info,
            text=name,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).pack(fill="x")

        status_text = f"{count:,} games indexed in database" if count > 0 else "Not yet scanned"
        color = "#10b981" if count > 0 else "gray50"
        ctk.CTkLabel(
            info,
            text=f"Folder: {code} • {status_text}",
            font=ctk.CTkFont(size=11),
            text_color=color,
            anchor="w"
        ).pack(fill="x")

        # Scan single console button
        btn = ctk.CTkButton(
            row,
            text="Scan Now",
            width=80,
            height=26,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
            command=lambda c=code: self.scan_single_console(c)
        )
        btn.pack(side="right", padx=8)

    def scan_single_console(self, code: str):
        c_def = CONSOLES.get(code)
        if not c_def:
            return

        def task():
            self.status_detail_lbl.configure(text=f"Scanning {c_def.display_name}...")
            count = scanner.scan_console(c_def)
            self.after(0, lambda: [
                self.refresh_stats(),
                self.status_detail_lbl.configure(text=f"Done! Indexed {count:,} games for {c_def.display_name}."),
                self.on_db_updated() if self.on_db_updated else None
            ])

        threading.Thread(target=task, daemon=True).start()

    def start_scan(self):
        """Starts asynchronous scan of all consoles."""
        if scanner.is_scanning:
            return

        self.scan_btn.configure(state="disabled", text="Scanning...")

        def on_progress(code, cur, total, msg):
            def update():
                frac = cur / max(total, 1)
                self.progress_bar.set(frac)
                self.status_detail_lbl.configure(text=f"[{cur}/{total}] {msg}")
            self.after(0, update)

        def on_complete(total_added):
            def done():
                self.progress_bar.set(1.0)
                self.scan_btn.configure(state="normal", text="Scan Minerva Archive")
                self.status_detail_lbl.configure(text=f"Scan complete! Total {total_added:,} games processed.")
                self.refresh_stats()
                if self.on_db_updated:
                    self.on_db_updated()
            self.after(0, done)

        def on_error(err):
            def err_ui():
                self.scan_btn.configure(state="normal", text="Scan Minerva Archive")
                self.status_detail_lbl.configure(text=f"Scan encountered an error: {err}")
            self.after(0, err_ui)

        scanner.scan_all_consoles_async(
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error
        )
