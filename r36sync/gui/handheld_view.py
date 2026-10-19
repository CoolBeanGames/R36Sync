"""
Handheld & SD Card View for R36Sync.
Manages R36S SD card diagnostics, ArkOS folder structure setup, save backup history and restores.
"""
import os
from pathlib import Path
import shutil
import threading
from typing import Optional, List
import customtkinter as ctk

from ..config import CONSOLES, settings
from ..database import db
from ..sd_detector import sd_detector, SDCardInfo
from ..sync_manager import sync_manager


class HandheldView(ctk.CTkFrame):
    """SD Card & Handheld Tab: Hardware inspection, structure validator, save game manager."""

    def __init__(self, master, on_sync_triggered=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_sync_triggered = on_sync_triggered
        self.active_sd: Optional[SDCardInfo] = None
        self._create_ui()
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
            text="Backup All Saves Now",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            command=self.backup_saves_now
        )
        self.backup_saves_btn.pack(side="left", padx=4)

        self.open_sd_btn = ctk.CTkButton(
            action_row,
            text="Open SD in Explorer",
            fg_color=("gray75", "gray28"),
            command=self.open_sd_in_explorer
        )
        self.open_sd_btn.pack(side="left", padx=4)

        # 2. Save Backups Manager Section
        saves_section = ctk.CTkFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
        saves_section.pack(fill="both", expand=True, padx=12, pady=(6, 10))

        s_header = ctk.CTkFrame(saves_section, fg_color="transparent")
        s_header.pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkLabel(
            s_header,
            text="Save Backups History",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(side="left")

        self.open_backups_btn = ctk.CTkButton(
            s_header,
            text="Open Backup Folder",
            width=140,
            command=self.open_backups_folder
        )
        self.open_backups_btn.pack(side="right")

        # Scrollable saves table
        self.saves_scroll = ctk.CTkScrollableFrame(saves_section, corner_radius=8)
        self.saves_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))

    def refresh(self):
        """Scans for SD cards and updates diagnostics and save history."""
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

        self._render_saves_table()

    def _render_saves_table(self):
        for w in self.saves_scroll.winfo_children():
            w.destroy()

        backups = db.get_save_backups(limit=60)
        if not backups:
            empty = ctk.CTkLabel(
                self.saves_scroll,
                text="No save backups recorded yet.\nSaves are automatically backed up whenever you sync with your R36S.",
                font=ctk.CTkFont(size=13),
                text_color="gray60"
            )
            empty.pack(pady=40)
            return

        for save in backups:
            row = ctk.CTkFrame(self.saves_scroll, fg_color=("gray90", "gray18"), corner_radius=6)
            row.pack(fill="x", padx=4, pady=2)

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

            # Restore button
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

    def prepare_folders(self):
        """Creates the full standard R36S ArkOS folder hierarchy on the active SD card."""
        if not self.active_sd:
            return
        target = self.active_sd.roms_root
        created = sd_detector.create_r36s_folder_structure(target)
        self.refresh()
        self._show_alert("Folders Ready", f"Created {len(created)} console and box art folders on {target}!")

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
                self._show_alert(
                    "Save Backup Complete",
                    f"Successfully backed up {count} save file(s) ({b_bytes / 1024:.1f} KB) to your PC!"
                )
            ])

        threading.Thread(target=task, daemon=True).start()

    def restore_save(self, save_record):
        """Restores a backed up save file back to the SD card."""
        if not self.active_sd:
            self._show_alert("No SD Card", "Please connect your R36S SD card first.")
            return

        backup_path = Path(save_record.get("backup_path", ""))
        if not backup_path.exists():
            self._show_alert("Missing File", "The backup file was not found on disk.")
            return

        console_code = save_record.get("console_code", "")
        dest_dir = self.active_sd.roms_root / console_code
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / save_record.get("file_name", "")

        try:
            shutil.copy2(backup_path, dest_file)
            self._show_alert("Save Restored", f"Restored {dest_file.name} to {console_code} on R36S!")
        except Exception as e:
            self._show_alert("Error", f"Failed to restore save: {e}")

    def open_sd_in_explorer(self):
        if self.active_sd and self.active_sd.roms_root.exists():
            os.startfile(str(self.active_sd.roms_root))

    def open_backups_folder(self):
        b_path = Path(settings.backup_dir)
        b_path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(b_path))

    def _show_alert(self, title: str, message: str):
        top = ctk.CTkToplevel(self)
        top.title(title)
        top.geometry("380x180")
        top.transient(self.winfo_toplevel())
        top.grab_set()

        ctk.CTkLabel(top, text=title, font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 8))
        ctk.CTkLabel(top, text=message, font=ctk.CTkFont(size=12), wraplength=340).pack(pady=6, padx=16)
        ctk.CTkButton(top, text="OK", width=90, command=top.destroy).pack(pady=(10, 16))
