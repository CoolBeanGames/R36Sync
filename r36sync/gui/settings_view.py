"""
Settings View for R36Sync.
Allows user configuration of library directories, save backup paths, SD card override, and theme.
"""
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk

from ..config import settings


class SettingsView(ctk.CTkFrame):
    """Settings Tab: User configuration and preferences."""

    def __init__(self, master, on_settings_changed=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_settings_changed = on_settings_changed
        self._create_ui()

    def _create_ui(self):
        container = ctk.CTkScrollableFrame(self, corner_radius=10, fg_color=("gray85", "gray17"))
        container.pack(fill="both", expand=True, padx=12, pady=10)

        ctk.CTkLabel(
            container,
            text="Preferences & Configuration",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(anchor="w", padx=14, pady=(12, 16))

        # 1. Library Directory
        self._create_path_section(
            container,
            title="Local Game Library Directory",
            desc="Where downloaded ROMs and games present on disc are stored on your computer.",
            path_var_name="library_dir",
            default_val=settings.library_dir
        )

        # 2. Save Backups Directory
        self._create_path_section(
            container,
            title="Save Backups Directory",
            desc="Where in-game saves (.srm, .sav) and states (.state) are safely backed up during sync.",
            path_var_name="backup_dir",
            default_val=settings.backup_dir
        )

        # 3. Custom SD Card Drive Override
        self._create_path_section(
            container,
            title="Custom SD Card Path Override (Optional)",
            desc="Leave blank for automatic detection of R36S SD cards, or specify a drive/folder.",
            path_var_name="sd_card_dir",
            default_val=settings.sd_card_dir or "",
            allow_clear=True
        )

        # 4. Automation Toggles
        toggle_frame = ctk.CTkFrame(container, fg_color="transparent")
        toggle_frame.pack(fill="x", padx=14, pady=12)

        ctk.CTkLabel(
            toggle_frame,
            text="Automation Settings",
            font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", pady=(0, 6))

        # Auto scan on launch
        self.auto_scan_var = ctk.BooleanVar(value=settings.auto_scan_on_launch)
        ctk.CTkSwitch(
            toggle_frame,
            text="Scan & update Minerva Archive catalog on application launch",
            variable=self.auto_scan_var,
            command=self._save_settings
        ).pack(anchor="w", pady=6)

        # Auto backup saves
        self.auto_backup_var = ctk.BooleanVar(value=settings.auto_backup_saves)
        ctk.CTkSwitch(
            toggle_frame,
            text="Automatically backup handheld saves whenever you sync",
            variable=self.auto_backup_var,
            command=self._save_settings
        ).pack(anchor="w", pady=6)

        # Auto download cover art
        self.auto_cover_var = ctk.BooleanVar(value=settings.download_cover_art)
        ctk.CTkSwitch(
            toggle_frame,
            text="Automatically download box art from Libretro when games are downloaded",
            variable=self.auto_cover_var,
            command=self._save_settings
        ).pack(anchor="w", pady=6)

        # 5. Appearance Theme
        theme_frame = ctk.CTkFrame(container, fg_color="transparent")
        theme_frame.pack(fill="x", padx=14, pady=12)

        ctk.CTkLabel(
            theme_frame,
            text="Appearance",
            font=ctk.CTkFont(size=15, weight="bold")
        ).pack(anchor="w", pady=(0, 6))

        self.theme_dropdown = ctk.CTkOptionMenu(
            theme_frame,
            values=["Dark", "Light", "System"],
            command=self._on_theme_changed,
            width=140
        )
        self.theme_dropdown.set(settings.theme)
        self.theme_dropdown.pack(anchor="w", pady=4)

    def _create_path_section(
        self,
        parent,
        title: str,
        desc: str,
        path_var_name: str,
        default_val: str,
        allow_clear: bool = False
    ):
        sec = ctk.CTkFrame(parent, fg_color="transparent")
        sec.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(
            sec,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w")

        ctk.CTkLabel(
            sec,
            text=desc,
            font=ctk.CTkFont(size=12),
            text_color="gray60"
        ).pack(anchor="w", pady=(2, 6))

        row = ctk.CTkFrame(sec, fg_color="transparent")
        row.pack(fill="x")

        entry = ctk.CTkEntry(row, height=32)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        entry.insert(0, default_val)
        setattr(self, f"{path_var_name}_entry", entry)

        def browse():
            folder = filedialog.askdirectory(initialdir=entry.get() or str(Path.home()))
            if folder:
                entry.delete(0, "end")
                entry.insert(0, folder)
                self._save_settings()

        ctk.CTkButton(
            row,
            text="Browse...",
            width=90,
            command=browse
        ).pack(side="left", padx=4)

        if allow_clear:
            def clear():
                entry.delete(0, "end")
                self._save_settings()
            ctk.CTkButton(
                row,
                text="Clear",
                width=65,
                fg_color=("gray75", "gray28"),
                command=clear
            ).pack(side="left", padx=4)

    def _save_settings(self):
        settings.library_dir = self.library_dir_entry.get().strip() or str(Path.home() / "Documents" / "R36Sync_Library")
        settings.backup_dir = self.backup_dir_entry.get().strip() or str(Path(settings.library_dir) / "backups")
        custom_sd = self.sd_card_dir_entry.get().strip()
        settings.sd_card_dir = custom_sd if custom_sd else None
        settings.auto_scan_on_launch = self.auto_scan_var.get()
        settings.auto_backup_saves = self.auto_backup_var.get()
        settings.download_cover_art = self.auto_cover_var.get()
        settings.save()

        if self.on_settings_changed:
            self.on_settings_changed()

    def _on_theme_changed(self, new_theme: str):
        settings.theme = new_theme
        settings.save()
        ctk.set_appearance_mode(new_theme.lower())
