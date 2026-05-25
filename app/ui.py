from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config import get_default_backup_dir, get_runtime_dir, load_config, save_config
from .detect import detect_environment
from .installer import build_install_preview, install_package
from .logging_utils import get_log_dir, setup_logger
from .models import AppConfig, InstallMode, InstallOptions, PackageInfo
from .package_reader import list_recent_zip_files, read_package_info, validate_package
from .version import APP_TITLE


class DksInstallerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1240x760")
        self.root.minsize(1120, 680)
        self._set_window_icon()
        self._configure_styles()

        self.config = load_config()
        self.package_cache: dict[str, PackageInfo] = {}
        self.download_zip_paths: list[Path] = []
        self.backup_zip_paths: list[Path] = []
        self.custom_zip_paths: list[Path] = []
        self.last_source_type = self._normalize_source_type(self.config.last_source_type)

        self.selected_zip_var = tk.StringVar(value=self._normalize_path_text(self.config.last_source_zip))
        self.saved_games_var = tk.StringVar(value=self._normalize_path_text(self.config.saved_games_path))
        self.documents_var = tk.StringVar(value=self._normalize_path_text(self.config.documents_path))
        self.dcs_install_var = tk.StringVar(value=self._normalize_path_text(self.config.dcs_install_path))
        self.dtc_app_var = tk.StringVar(value=self._normalize_path_text(self.config.dtc_app_path))
        self.custom_kneeboard_var = tk.StringVar(
            value=self._normalize_path_text(self.config.custom_kneeboard_path)
        )
        self.custom_zip_folder_var = tk.StringVar(
            value=self._normalize_path_text(self.config.custom_zip_folder)
        )
        self.backup_dir_var = tk.StringVar(
            value=self._normalize_path_text(self.config.backup_dir or str(get_default_backup_dir()))
        )

        self.auto_install_latest_var = tk.BooleanVar(
            value=self.config.auto_install_latest_enabled
        )

        self.show_restore_preview_var = tk.BooleanVar(
            value=self.config.show_restore_preview
        )
        self.write_manifest_var = tk.BooleanVar(value=self.config.write_install_manifest)
        self.safe_cleanup_mode_var = tk.BooleanVar(value=self.config.safe_cleanup_mode)
        self.open_destinations_var = tk.BooleanVar(
            value=self.config.open_destinations_after_install
        )
        self.kill_dtc_before_launch_var = tk.BooleanVar(
            value=self.config.kill_dtc_before_launch
        )

        self.advanced_visible = False

        self._build_layout()
        self.logger = setup_logger(ui_callback=self._append_log)
        self.logger.info("Launching %s", APP_TITLE)

        self._detect_environment()
        self._refresh_sources()

        self.root.after(400, self._maybe_auto_install_latest)

    def _build_layout(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(4, weight=1)

        source_frame = ttk.LabelFrame(self.root, text="Flight Plan Source")
        source_frame.grid(row=0, column=0, padx=10, pady=(10, 6), sticky="nsew")
        source_frame.grid_columnconfigure(0, weight=1)
        source_frame.grid_columnconfigure(1, weight=1)
        source_frame.grid_columnconfigure(2, weight=1)
        source_frame.grid_columnconfigure(3, weight=2)
        source_frame.grid_rowconfigure(1, weight=1)

        ttk.Label(source_frame, text="Recent Downloads (latest 10)").grid(
            row=0, column=0, padx=6, pady=4, sticky="w"
        )
        ttk.Label(source_frame, text="Recent Backups (latest 10)").grid(
            row=0, column=1, padx=6, pady=4, sticky="w"
        )
        ttk.Label(source_frame, text="Custom DKS ZIP Folder (latest 10)").grid(
            row=0, column=2, padx=6, pady=4, sticky="w"
        )

        self.downloads_list = tk.Listbox(source_frame, height=6, exportselection=False)
        self.downloads_list.grid(row=1, column=0, padx=6, pady=4, sticky="nsew")
        self._configure_source_listbox(self.downloads_list)
        self.downloads_list.bind("<<ListboxSelect>>", self._on_download_selected)

        self.backups_list = tk.Listbox(source_frame, height=6, exportselection=False)
        self.backups_list.grid(row=1, column=1, padx=6, pady=4, sticky="nsew")
        self._configure_source_listbox(self.backups_list)
        self.backups_list.bind("<<ListboxSelect>>", self._on_backup_selected)

        self.custom_zip_list = tk.Listbox(source_frame, height=6, exportselection=False)
        self.custom_zip_list.grid(row=1, column=2, padx=6, pady=4, sticky="nsew")
        self._configure_source_listbox(self.custom_zip_list)
        self.custom_zip_list.bind("<<ListboxSelect>>", self._on_custom_zip_selected)

        ttk.Button(
            source_frame,
            text="Install Latest\nDownload Now",
            command=self._auto_install_latest_now,
            style="SuccessAction.TButton",
        ).grid(row=2, column=0, padx=6, pady=(0, 4), sticky="ew")
        ttk.Button(
            source_frame,
            text="Install Most\nRecent",
            command=lambda: self._install_most_recent_from_source("backup"),
            style="SuccessAction.TButton",
        ).grid(row=2, column=1, padx=6, pady=(0, 4), sticky="ew")
        ttk.Button(
            source_frame,
            text="Install Most\nRecent",
            command=lambda: self._install_most_recent_from_source("custom"),
            style="SuccessAction.TButton",
        ).grid(row=2, column=2, padx=6, pady=(0, 4), sticky="ew")

        entry_frame = ttk.Frame(source_frame)
        entry_frame.grid(row=1, column=3, rowspan=2, padx=6, pady=4, sticky="nsew")
        entry_frame.grid_columnconfigure(0, weight=1)

        ttk.Label(entry_frame, text="Selected ZIP (download, backup, or custom folder)").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(entry_frame, textvariable=self.selected_zip_var).grid(
            row=1, column=0, sticky="ew", pady=(2, 6)
        )

        ttk.Label(entry_frame, text="Custom DKS ZIP Folder").grid(
            row=2, column=0, sticky="w", pady=(2, 0)
        )

        custom_zip_folder_row = ttk.Frame(entry_frame)
        custom_zip_folder_row.grid(row=3, column=0, sticky="ew", pady=(2, 6))
        custom_zip_folder_row.grid_columnconfigure(0, weight=1)

        ttk.Entry(custom_zip_folder_row, textvariable=self.custom_zip_folder_var).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(
            custom_zip_folder_row,
            text="Browse Folder...",
            command=self._browse_custom_zip_folder,
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

        ttk.Button(entry_frame, text="Pick ZIP Manually...", command=self._browse_zip).grid(
            row=4, column=0, sticky="ew", pady=2
        )
        ttk.Button(entry_frame, text="Refresh ZIP Lists", command=self._refresh_sources).grid(
            row=5, column=0, sticky="ew", pady=2
        )

        ttk.Checkbutton(
            entry_frame,
            text="Auto-install latest Downloads ZIP on startup",
            variable=self.auto_install_latest_var,
            command=self._save_config_from_ui,
        ).grid(row=6, column=0, sticky="w", pady=(8, 0))

        env_frame = ttk.LabelFrame(self.root, text="Environment")
        env_frame.grid(row=1, column=0, padx=10, pady=6, sticky="ew")
        env_frame.grid_columnconfigure(1, weight=1)

        self._add_path_row(
            parent=env_frame,
            row=0,
            label="DCS Saved Games Folder",
            variable=self.saved_games_var,
        )
        self._add_path_row(
            parent=env_frame,
            row=1,
            label="Documents",
            variable=self.documents_var,
        )
        self._add_path_row(
            parent=env_frame,
            row=2,
            label="DCS Install (optional)",
            variable=self.dcs_install_var,
        )
        self._add_file_row(
            parent=env_frame,
            row=3,
            label="DTC App Path (DTC.exe, optional)",
            variable=self.dtc_app_var,
            filetypes=[("DTC executable", "DTC.exe"), ("Executables", "*.exe"), ("All files", "*.*")],
        )
        self._add_path_row(
            parent=env_frame,
            row=4,
            label="Backup Folder",
            variable=self.backup_dir_var,
        )
        self._add_path_row(
            parent=env_frame,
            row=5,
            label="Custom Kneeboard Folder (optional)",
            variable=self.custom_kneeboard_var,
        )

        action_frame = ttk.LabelFrame(self.root, text="Actions")
        action_frame.grid(row=2, column=0, padx=10, pady=6, sticky="ew")
        action_frame.grid_columnconfigure(0, weight=1)

        top_actions_row = ttk.Frame(action_frame)
        top_actions_row.grid(row=0, column=0, padx=6, pady=(8, 4), sticky="ew")
        for col in range(3):
            top_actions_row.grid_columnconfigure(col, weight=1, uniform="top_actions")

        ttk.Button(
            top_actions_row,
            text="Validate ZIP\nPackage",
            command=self._validate_package,
            style="UtilityAction.TButton",
            width=25,
        ).grid(row=0, column=0, padx=10, sticky="")
        ttk.Button(
            top_actions_row,
            text="Install Only\n(Overwrite DKS Files)",
            command=lambda: self._run_install("install_only"),
            style="SuccessAction.TButton",
            width=25,
        ).grid(row=0, column=1, padx=10, sticky="")
        ttk.Button(
            top_actions_row,
            text="Backup Current and\nInstall",
            command=lambda: self._run_install("backup_install"),
            style="PrimaryAction.TButton",
            width=25,
        ).grid(row=0, column=2, padx=10, sticky="")

        bottom_actions_row = ttk.Frame(action_frame)
        bottom_actions_row.grid(row=1, column=0, padx=6, pady=(4, 8), sticky="ew")
        for col in range(4):
            bottom_actions_row.grid_columnconfigure(col, weight=1)

        ttk.Button(
            bottom_actions_row,
            text="Open Logs Folder",
            command=self._open_logs_folder,
            style="UtilityAction.TButton",
        ).grid(
            row=0,
            column=0,
            padx=10,
            sticky="ew",
        )
        ttk.Button(
            bottom_actions_row,
            text="Open Backup Folder",
            command=self._open_backup_folder,
            style="UtilityAction.TButton",
        ).grid(row=0, column=1, padx=10, sticky="ew")
        ttk.Button(
            bottom_actions_row,
            text="Open DCS Saved Games Folders",
            command=self._open_dcs_saved_games_folders,
            style="UtilityAction.TButton",
        ).grid(row=0, column=2, padx=10, sticky="ew")
        ttk.Button(
            bottom_actions_row,
            text="Clear Custom Kneeboard Folder",
            command=self._clear_custom_kneeboard_folder,
            style="UtilityAction.TButton",
        ).grid(row=0, column=3, padx=10, sticky="ew")

        advanced_wrap = ttk.LabelFrame(self.root, text="Advanced")
        advanced_wrap.grid(row=3, column=0, padx=10, pady=6, sticky="ew")
        advanced_wrap.grid_columnconfigure(0, weight=1)

        self.advanced_toggle_btn = ttk.Button(
            advanced_wrap,
            text="▶ Show Advanced Options",
            command=self._toggle_advanced,
        )
        self.advanced_toggle_btn.grid(row=0, column=0, padx=6, pady=6, sticky="w")

        self.advanced_frame = ttk.Frame(advanced_wrap)
        self.advanced_frame.grid(row=1, column=0, padx=6, pady=(0, 6), sticky="ew")
        self.advanced_frame.grid_columnconfigure(0, weight=1)

        ttk.Checkbutton(
            self.advanced_frame,
            text="Show detailed restore/install preview before execution",
            variable=self.show_restore_preview_var,
            command=self._save_config_from_ui,
        ).grid(row=0, column=0, sticky="w", pady=2)

        ttk.Checkbutton(
            self.advanced_frame,
            text="Write tracked install manifest after each run",
            variable=self.write_manifest_var,
            command=self._save_config_from_ui,
        ).grid(row=1, column=0, sticky="w", pady=2)

        ttk.Checkbutton(
            self.advanced_frame,
            text="Safe cleanup mode (only files for current package/design)",
            variable=self.safe_cleanup_mode_var,
            command=self._save_config_from_ui,
        ).grid(row=2, column=0, sticky="w", pady=2)

        ttk.Checkbutton(
            self.advanced_frame,
            text="Open destination folders after successful install",
            variable=self.open_destinations_var,
            command=self._save_config_from_ui,
        ).grid(row=3, column=0, sticky="w", pady=2)

        ttk.Checkbutton(
            self.advanced_frame,
            text="Kill running DTC.exe before auto-launch (legacy behavior)",
            variable=self.kill_dtc_before_launch_var,
            command=self._save_config_from_ui,
        ).grid(row=4, column=0, sticky="w", pady=2)

        ttk.Label(
            self.advanced_frame,
            text="Default when Safe Cleanup is OFF: Aggressive bat-like cleanup.",
        ).grid(row=5, column=0, sticky="w", pady=(4, 0))

        self.advanced_frame.grid_remove()

        status_frame = ttk.LabelFrame(self.root, text="Status")
        status_frame.grid(row=4, column=0, padx=10, pady=(6, 10), sticky="nsew")
        status_frame.grid_rowconfigure(1, weight=1)
        status_frame.grid_columnconfigure(0, weight=1)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            status_frame,
            variable=self.progress_var,
            maximum=100,
        )
        self.progress_bar.grid(row=0, column=0, padx=6, pady=6, sticky="ew")

        self.log_text = ScrolledText(status_frame, height=14, state="disabled")
        self.log_text.grid(row=1, column=0, padx=6, pady=(0, 6), sticky="nsew")

    def _set_window_icon(self) -> None:
        icon_candidates: list[Path] = []

        if getattr(sys, "frozen", False):
            icon_candidates.append(Path(sys.executable))

        icon_candidates.append(get_runtime_dir() / "assets" / "dks-web-favicon.ico")

        for candidate in icon_candidates:
            try:
                if candidate.exists():
                    self.root.iconbitmap(str(candidate))
                    return
            except (tk.TclError, OSError):
                continue

    def _focus_installer_window(self) -> None:
        def apply_focus() -> None:
            try:
                if not self.root.winfo_exists():
                    return
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
                self.root.attributes("-topmost", True)
                self.root.after(25, lambda: self.root.attributes("-topmost", False))
            except tk.TclError:
                return

        # Run several focus pulses since external app launches (e.g. DTC)
        # can grab focus asynchronously after process start.
        for delay_ms in (0, 140, 420, 900):
            self.root.after(delay_ms, apply_focus)

    def _configure_styles(self) -> None:
        base_bg = "#EEF3FB"
        panel_bg = "#FFFFFF"
        text_color = "#111827"
        primary_button_bg = "#0B3A86"
        primary_button_active = "#0A3170"

        self.root.configure(bg=base_bg)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", font=("Segoe UI", 9))
        style.configure("TFrame", background=base_bg)
        style.configure("TLabelframe", background=panel_bg, borderwidth=1, relief="solid")
        style.configure(
            "TLabelframe.Label",
            background=panel_bg,
            foreground=text_color,
            font=("Segoe UI", 9, "bold"),
        )
        style.configure("TLabel", background=panel_bg, foreground=text_color)
        style.configure("TCheckbutton", background=panel_bg, foreground=text_color)
        style.map("TCheckbutton", background=[("active", panel_bg)])
        style.configure(
            "TButton",
            padding=(10, 6),
            font=("Segoe UI", 9, "bold"),
            anchor="center",
        )

        style.configure(
            "PrimaryAction.TButton",
            background=primary_button_bg,
            foreground="white",
            borderwidth=2,
            anchor="center",
            relief="raised",
            lightcolor="#4F7CC7",
            darkcolor="#07295F",
            bordercolor="#082B63",
        )
        style.map(
            "PrimaryAction.TButton",
            background=[
                ("pressed", "#082B63"),
                ("active", "#1A4C9D"),
                ("disabled", "#93A4C4"),
            ],
            foreground=[("disabled", "#F3F4F6")],
            relief=[("pressed", "sunken"), ("active", "raised")],
        )

        style.configure(
            "UtilityAction.TButton",
            background="#D3D6DC",
            foreground=text_color,
            borderwidth=2,
            anchor="center",
            relief="raised",
            lightcolor="#F5F6F8",
            darkcolor="#8B919A",
            bordercolor="#A8AFB8",
        )
        style.map(
            "UtilityAction.TButton",
            background=[("pressed", "#BCC1C9"), ("active", "#E4E7EC")],
            relief=[("pressed", "sunken"), ("active", "raised")],
        )

        style.configure(
            "SuccessAction.TButton",
            background="#0B6E24",
            foreground="white",
            borderwidth=2,
            anchor="center",
            relief="raised",
            lightcolor="#40A75A",
            darkcolor="#064814",
            bordercolor="#08561C",
        )
        style.map(
            "SuccessAction.TButton",
            background=[
                ("pressed", "#064814"),
                ("active", "#0E7F2A"),
                ("disabled", "#8FB89A"),
            ],
            foreground=[("disabled", "#F3F4F6")],
            relief=[("pressed", "sunken"), ("active", "raised")],
        )

        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#E5EAF4",
            background="#1D4ED8",
            bordercolor="#E5EAF4",
            lightcolor="#1D4ED8",
            darkcolor="#1D4ED8",
        )

    @staticmethod
    def _configure_source_listbox(listbox: tk.Listbox) -> None:
        listbox.configure(
            bg="#FFFFFF",
            fg="#1F2937",
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#D5DCE8",
            highlightcolor="#1D4ED8",
            selectbackground="#DCEAFE",
            selectforeground="#0F172A",
            activestyle="none",
        )

    def _add_path_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, padx=6, pady=4, sticky="w")
        ttk.Entry(parent, textvariable=variable).grid(
            row=row,
            column=1,
            padx=6,
            pady=4,
            sticky="ew",
        )
        ttk.Button(
            parent,
            text="Browse...",
            command=lambda var=variable: self._browse_folder(var),
        ).grid(row=row, column=2, padx=6, pady=4, sticky="ew")

    def _toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_toggle_btn.configure(text="▼ Hide Advanced Options")
            self.advanced_frame.grid()
        else:
            self.advanced_toggle_btn.configure(text="▶ Show Advanced Options")
            self.advanced_frame.grid_remove()

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()

    @staticmethod
    def _normalize_path_text(path_value: str | Path) -> str:
        if not path_value:
            return ""
        return os.path.normpath(str(path_value))

    @staticmethod
    def _looks_like_saved_games_root(folder: Path) -> bool:
        if folder.name.lower() == "saved games":
            return True

        if folder.exists() and folder.is_dir() and not folder.name.upper().startswith("DCS"):
            try:
                for child in folder.iterdir():
                    if child.is_dir() and child.name.upper().startswith("DCS"):
                        return True
            except OSError:
                return False

        return False

    @staticmethod
    def _normalize_source_type(value: str) -> str:
        if value in {"download", "backup", "custom", "manual"}:
            return value
        return "download"

    def _set_source_type(self, source_type: str) -> None:
        self.last_source_type = self._normalize_source_type(source_type)

    def _get_source_state(self, source_type: str) -> tuple[list[Path], tk.Listbox, str]:
        if source_type == "download":
            return self.download_zip_paths, self.downloads_list, "Recent Downloads"
        if source_type == "backup":
            return self.backup_zip_paths, self.backups_list, "Recent Backups"
        return self.custom_zip_paths, self.custom_zip_list, "Custom DKS ZIP Folder"

    def _clear_source_list_selections(self, keep: str | None = None) -> None:
        if keep != "download":
            self.downloads_list.selection_clear(0, "end")
        if keep != "backup":
            self.backups_list.selection_clear(0, "end")
        if keep != "custom":
            self.custom_zip_list.selection_clear(0, "end")

    def _select_source_zip(self, source_type: str, index: int) -> None:
        source_paths, source_listbox, _source_label = self._get_source_state(source_type)

        if not (0 <= index < len(source_paths)):
            return

        self.selected_zip_var.set(str(source_paths[index]))
        self._set_source_type(source_type)
        self._clear_source_list_selections(keep=source_type)
        source_listbox.selection_set(index)
        source_listbox.see(index)
        self._save_config_from_ui()

    def _install_most_recent_from_source(self, source_type: str) -> None:
        source_paths, _source_listbox, source_label = self._get_source_state(source_type)
        if not source_paths:
            if source_type == "custom" and not self.custom_zip_folder_var.get().strip():
                messagebox.showwarning(
                    "Install Most Recent",
                    "Select a Custom DKS ZIP Folder first.",
                )
            else:
                messagebox.showwarning(
                    "Install Most Recent",
                    f"No ZIP files found in {source_label}.",
                )
            return

        self._select_source_zip(source_type, 0)
        self._run_install("install_only")

    def _add_file_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        filetypes: list[tuple[str, str]],
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, padx=6, pady=4, sticky="w")
        ttk.Entry(parent, textvariable=variable).grid(
            row=row,
            column=1,
            padx=6,
            pady=4,
            sticky="ew",
        )
        ttk.Button(
            parent,
            text="Browse...",
            command=lambda var=variable, ft=filetypes: self._browse_file(var, ft),
        ).grid(row=row, column=2, padx=6, pady=4, sticky="ew")

    def _set_progress(self, value: int, message: str) -> None:
        self.progress_var.set(max(0, min(100, value)))
        if message:
            self._append_log(message)

    def _detect_environment(self) -> None:
        detected = detect_environment()

        current_saved_games = self.saved_games_var.get().strip()
        detected_dcs_folder = self._normalize_path_text(detected.dcs_saved_games_folder)
        if not current_saved_games:
            self.saved_games_var.set(detected_dcs_folder)
        else:
            current_path = Path(current_saved_games)
            if self._looks_like_saved_games_root(current_path) and current_path != Path(detected_dcs_folder):
                self.saved_games_var.set(detected_dcs_folder)
                self._append_log(
                    "Auto-updated DCS Saved Games Folder from Saved Games root "
                    f"to detected DCS folder: {detected_dcs_folder}"
                )

        if not self.documents_var.get().strip():
            self.documents_var.set(self._normalize_path_text(detected.documents_path))
        if not self.dcs_install_var.get().strip() and detected.dcs_install_path is not None:
            self.dcs_install_var.set(self._normalize_path_text(detected.dcs_install_path))
        if not self.dtc_app_var.get().strip() and detected.dtc_app_path is not None:
            self.dtc_app_var.set(self._normalize_path_text(detected.dtc_app_path))

        self._save_config_from_ui()

    def _refresh_sources(self, force_preferred_source: bool = False) -> None:
        downloads_dir = Path.home() / "Downloads"
        backup_dir = Path(self.backup_dir_var.get().strip() or str(get_default_backup_dir()))
        custom_zip_dir_raw = self.custom_zip_folder_var.get().strip()
        custom_zip_dir = Path(custom_zip_dir_raw) if custom_zip_dir_raw else None

        self.download_zip_paths = list_recent_zip_files(downloads_dir, limit=10)
        self.backup_zip_paths = list_recent_zip_files(backup_dir, limit=10)
        self.custom_zip_paths = (
            list_recent_zip_files(custom_zip_dir, limit=10)
            if custom_zip_dir is not None
            else []
        )

        self.downloads_list.delete(0, "end")
        for path in self.download_zip_paths:
            self.downloads_list.insert("end", path.name)

        self.backups_list.delete(0, "end")
        for path in self.backup_zip_paths:
            self.backups_list.insert("end", path.name)

        self.custom_zip_list.delete(0, "end")
        for path in self.custom_zip_paths:
            self.custom_zip_list.insert("end", path.name)

        selected_path = self.selected_zip_var.get().strip()
        selected_exists = bool(selected_path and Path(selected_path).exists())

        if force_preferred_source or not selected_exists:
            if self.last_source_type == "custom" and self.custom_zip_paths:
                self.selected_zip_var.set(str(self.custom_zip_paths[0]))
            elif self.last_source_type == "backup" and self.backup_zip_paths:
                self.selected_zip_var.set(str(self.backup_zip_paths[0]))
            elif self.last_source_type == "download" and self.download_zip_paths:
                self.selected_zip_var.set(str(self.download_zip_paths[0]))
            elif self.download_zip_paths:
                self.selected_zip_var.set(str(self.download_zip_paths[0]))
                self._set_source_type("download")
            elif self.custom_zip_paths:
                self.selected_zip_var.set(str(self.custom_zip_paths[0]))
                self._set_source_type("custom")
            elif self.backup_zip_paths:
                self.selected_zip_var.set(str(self.backup_zip_paths[0]))
                self._set_source_type("backup")
            else:
                self.selected_zip_var.set("")

        selected_value = self.selected_zip_var.get().strip()
        self._clear_source_list_selections()

        for index, path in enumerate(self.download_zip_paths):
            if str(path) == selected_value:
                self.downloads_list.selection_set(index)
                self.downloads_list.see(index)
                break

        for index, path in enumerate(self.backup_zip_paths):
            if str(path) == selected_value:
                self.backups_list.selection_set(index)
                self.backups_list.see(index)
                break

        for index, path in enumerate(self.custom_zip_paths):
            if str(path) == selected_value:
                self.custom_zip_list.selection_set(index)
                self.custom_zip_list.see(index)
                break

        self._append_log(
            f"Sources refreshed: {len(self.download_zip_paths)} download ZIP(s), "
            f"{len(self.backup_zip_paths)} backup ZIP(s), "
            f"{len(self.custom_zip_paths)} custom ZIP(s). Preferred source: {self.last_source_type}."
        )

        if custom_zip_dir_raw and not self.custom_zip_paths:
            self._append_log(
                "Custom DKS ZIP folder is set but no ZIP files were found there: "
                f"{self._normalize_path_text(custom_zip_dir_raw)}"
            )

        self._save_config_from_ui()

    def _on_download_selected(self, _event: object) -> None:
        selected = self.downloads_list.curselection()
        if not selected:
            return
        self._select_source_zip("download", selected[0])

    def _on_backup_selected(self, _event: object) -> None:
        selected = self.backups_list.curselection()
        if not selected:
            return
        self._select_source_zip("backup", selected[0])

    def _on_custom_zip_selected(self, _event: object) -> None:
        selected = self.custom_zip_list.curselection()
        if not selected:
            return
        self._select_source_zip("custom", selected[0])

    def _browse_zip(self) -> None:
        if self.last_source_type == "backup":
            initial_dir = str(Path(self.backup_dir_var.get().strip() or str(get_default_backup_dir())))
        elif self.last_source_type == "custom" and self.custom_zip_folder_var.get().strip():
            initial_dir = self.custom_zip_folder_var.get().strip()
        else:
            initial_dir = str(Path.home() / "Downloads")
        selected = filedialog.askopenfilename(
            title="Pick flight-plan ZIP",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
            initialdir=initial_dir,
        )
        if selected:
            self.selected_zip_var.set(self._normalize_path_text(selected))
            self._set_source_type("manual")
            self._clear_source_list_selections()
            self._save_config_from_ui()

    def _browse_custom_zip_folder(self) -> None:
        initial_dir = self.custom_zip_folder_var.get().strip() or str(Path.home())
        selected = filedialog.askdirectory(
            title="Select custom DKS ZIP folder",
            initialdir=initial_dir,
        )
        if selected:
            self.custom_zip_folder_var.set(self._normalize_path_text(selected))
            self._set_source_type("custom")
            self._refresh_sources(force_preferred_source=True)

    def _browse_file(self, var: tk.StringVar, filetypes: list[tuple[str, str]]) -> None:
        initial_dir = str(Path(var.get().strip()).parent) if var.get().strip() else str(Path.home())
        selected = filedialog.askopenfilename(
            title="Select file",
            filetypes=filetypes,
            initialdir=initial_dir,
        )
        if selected:
            var.set(self._normalize_path_text(selected))
            self._save_config_from_ui()

    def _browse_folder(self, var: tk.StringVar) -> None:
        initial_dir = var.get().strip() or str(Path.home())
        selected = filedialog.askdirectory(title="Select folder", initialdir=initial_dir)
        if selected:
            var.set(self._normalize_path_text(selected))
            self._save_config_from_ui()

    def _get_package_info(self, zip_path: Path) -> PackageInfo:
        key = str(zip_path.resolve())
        cached = self.package_cache.get(key)
        if cached is not None:
            return cached

        info = read_package_info(zip_path)
        self.package_cache[key] = info
        return info

    def _validate_package(self) -> None:
        zip_path = Path(self.selected_zip_var.get().strip())
        if not zip_path.exists():
            messagebox.showerror("Validate Package", "Selected ZIP path does not exist.")
            return

        result = validate_package(zip_path)
        if not result.is_valid:
            messagebox.showerror("Validate Package", "\n".join(result.errors))
            return

        details: list[str] = ["Package looks valid."]
        if result.package_info:
            details.append(f"Type: {result.package_info.kind}")
            if result.package_info.kind == "standard" and result.package_info.manifest:
                details.append(
                    f"Design: {result.package_info.manifest.design.name} / Pilot: {result.package_info.manifest.design.pilot_name}"
                )
                details.append(
                    f"PNG pages: {len(result.package_info.pilot_png_entries)}"
                )
                details.append(
                    f"Loadout files: {len(result.package_info.loadout_entries)}"
                )
            if result.package_info.kind == "backup_snapshot" and result.package_info.backup_manifest:
                details.append(
                    "Restore entries: "
                    f"{len(result.package_info.backup_manifest.restore_entries)}"
                )

        if result.warnings:
            details.append("")
            details.append("Warnings:")
            details.extend([f"- {warning}" for warning in result.warnings])

        messagebox.showinfo("Validate Package", "\n".join(details))

    def _show_preview_dialog(self, title: str, preview_text: str) -> bool:
        approved = {"value": False}

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("900x620")
        dialog.minsize(760, 520)
        dialog.transient(self.root)
        dialog.grab_set()

        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)

        ttk.Label(
            dialog,
            text="Review planned actions before continuing:",
        ).grid(row=0, column=0, padx=10, pady=(10, 6), sticky="w")

        preview_box = ScrolledText(dialog, wrap="word")
        preview_box.grid(row=1, column=0, padx=10, pady=6, sticky="nsew")
        preview_box.insert("1.0", preview_text)
        preview_box.configure(state="disabled")

        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=2, column=0, padx=10, pady=(6, 10), sticky="e")

        def approve() -> None:
            approved["value"] = True
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        ttk.Button(button_frame, text="Cancel", command=cancel).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(button_frame, text="Proceed", command=approve).grid(row=0, column=1)

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.bind("<Escape>", lambda _event: cancel())
        dialog.bind("<Control-Return>", lambda _event: approve())

        dialog.focus_set()
        self.root.wait_window(dialog)
        return approved["value"]

    def _format_result_lines(self, result: object) -> list[str]:
        # Keep this helper tiny and tolerant while still giving users a clean summary.
        lines: list[str] = []
        if hasattr(result, "summary"):
            lines.append(getattr(result, "summary") or "Operation completed.")

        if hasattr(result, "dtc_manual_close_required") and getattr(
            result,
            "dtc_manual_close_required",
            False,
        ):
            lines.append("Manual action required: close DTC.exe before continuing.")

        if hasattr(result, "installed_files"):
            lines.append(f"Installed files: {len(getattr(result, 'installed_files', []))}")
        if hasattr(result, "removed_files"):
            lines.append(f"Removed files: {len(getattr(result, 'removed_files', []))}")
        if hasattr(result, "skipped_items"):
            lines.append(f"Skipped items: {len(getattr(result, 'skipped_items', []))}")
        if hasattr(result, "warnings"):
            lines.append(f"Warnings: {len(getattr(result, 'warnings', []))}")

        if hasattr(result, "backup_zip") and getattr(result, "backup_zip", None):
            lines.append(f"Backup ZIP: {getattr(result, 'backup_zip')}")

        skipped_items = getattr(result, "skipped_items", [])
        if skipped_items:
            lines.append("")
            lines.append("Skipped details:")
            lines.extend([f"- {item}" for item in skipped_items])

        warnings = getattr(result, "warnings", [])
        if warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend([f"- {warning}" for warning in warnings])

        return lines

    def _build_install_options(self, mode: InstallMode) -> InstallOptions | None:
        zip_path = Path(self.selected_zip_var.get().strip())
        if not zip_path.exists():
            messagebox.showerror("Install", "Selected ZIP path does not exist.")
            return None

        saved_games_raw = self.saved_games_var.get().strip()
        documents_raw = self.documents_var.get().strip()
        backup_dir = Path(self.backup_dir_var.get().strip() or str(get_default_backup_dir()))

        if not saved_games_raw:
            messagebox.showerror("Install", "DCS Saved Games Folder is required.")
            return None
        if not documents_raw:
            messagebox.showerror("Install", "Documents path is required.")
            return None

        saved_games_path = Path(saved_games_raw)
        documents_path = Path(documents_raw)

        dcs_install_raw = self.dcs_install_var.get().strip()
        dcs_install_path = Path(dcs_install_raw) if dcs_install_raw else None
        dtc_app_raw = self.dtc_app_var.get().strip()
        dtc_app_path = Path(dtc_app_raw) if dtc_app_raw else None
        custom_kneeboard_raw = self.custom_kneeboard_var.get().strip()
        custom_kneeboard_path = Path(custom_kneeboard_raw) if custom_kneeboard_raw else None

        options = InstallOptions(
            mode=mode,
            zip_path=zip_path,
            saved_games_path=saved_games_path,
            documents_path=documents_path,
            dcs_install_path=dcs_install_path,
            dtc_app_path=dtc_app_path,
            custom_kneeboard_path=custom_kneeboard_path,
            kill_dtc_before_launch=self.kill_dtc_before_launch_var.get(),
            backup_dir=backup_dir,
            show_restore_preview=self.show_restore_preview_var.get(),
            write_install_manifest=self.write_manifest_var.get(),
            safe_cleanup_mode=self.safe_cleanup_mode_var.get(),
            open_destinations_after_install=self.open_destinations_var.get(),
        )
        return options

    def _run_install(self, mode: InstallMode) -> None:
        options = self._build_install_options(mode)
        if options is None:
            return

        try:
            package_info = self._get_package_info(options.zip_path)
        except Exception as exc:  # pylint: disable=broad-except
            messagebox.showerror("Install", str(exc))
            return

        if options.show_restore_preview:
            preview = build_install_preview(package_info, options)
            if package_info.warnings:
                preview += "\n\nPackage warnings:\n" + "\n".join(
                    f"- {warning}" for warning in package_info.warnings
                )
            if not self._show_preview_dialog("Install Preview", preview):
                return

        action_label = "Backup Current + Install" if mode == "backup_install" else "Install Only"
        cleanup_label = (
            "Safe cleanup (current package only)"
            if options.safe_cleanup_mode
            else "Aggressive cleanup (bat-like)"
        )
        dtc_line = f"DTC app path: {options.dtc_app_path}\n" if options.dtc_app_path else ""
        custom_kneeboard_line = (
            f"Custom kneeboard folder: {options.custom_kneeboard_path}\n"
            if options.custom_kneeboard_path
            else ""
        )
        dtc_kill_line = (
            "Kill running DTC.exe before auto-launch: "
            f"{'Yes' if options.kill_dtc_before_launch else 'No'}\n"
        )
        if not messagebox.askyesno(
            "Confirm Install",
            (
                f"Action: {action_label}\n"
                f"DCS Saved Games Folder: {options.saved_games_path}\n"
                f"{dtc_line}"
                f"{custom_kneeboard_line}"
                f"{dtc_kill_line}"
                f"Cleanup: {cleanup_label}\n\n"
                f"Source:\n{options.zip_path}\n\n"
                "Continue?"
            ),
        ):
            return

        self._save_config_from_ui()
        self._set_progress(0, "Starting...")

        result = install_package(
            package_info=package_info,
            options=options,
            log=lambda msg: self.logger.info(msg),
            progress=self._set_progress,
        )

        self._focus_installer_window()

        if getattr(result, "dtc_manual_close_required", False):
            messagebox.showwarning(
                "Close DTC.exe",
                "The installer could not stop DTC.exe automatically.\n\n"
                "Please close DTC.exe manually before continuing.",
            )
            self._focus_installer_window()

        summary_lines = self._format_result_lines(result)

        if result.success:
            messagebox.showinfo("Install", "\n".join(summary_lines))
        else:
            messagebox.showerror("Install", "\n".join(summary_lines))

        self._focus_installer_window()

        self._refresh_sources()

    def _auto_install_latest_now(self) -> None:
        self._install_most_recent_from_source("download")

    def _maybe_auto_install_latest(self) -> None:
        if not self.auto_install_latest_var.get():
            return

        if not self.download_zip_paths:
            return

        if messagebox.askyesno(
            "Auto Install",
            f"Auto-install latest ZIP now?\n\n{self.download_zip_paths[0]}",
        ):
            self.selected_zip_var.set(str(self.download_zip_paths[0]))
            self._set_source_type("download")
            self._run_install("install_only")

    def _open_logs_folder(self) -> None:
        os.startfile(str(get_log_dir()))

    def _open_backup_folder(self) -> None:
        backup_dir = Path(self.backup_dir_var.get().strip() or str(get_default_backup_dir()))
        backup_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(backup_dir))

    def _clear_custom_kneeboard_folder(self) -> None:
        custom_folder_raw = self.custom_kneeboard_var.get().strip()
        if not custom_folder_raw:
            messagebox.showerror(
                "Clear Custom Folder",
                "Custom Kneeboard Folder is empty.",
            )
            return

        custom_folder = Path(custom_folder_raw)
        normalized = Path(os.path.normpath(str(custom_folder)))
        if str(normalized) in {normalized.anchor, "", "."}:
            messagebox.showerror(
                "Clear Custom Folder",
                "Refusing to clear a root path. Pick a specific folder.",
            )
            return

        if not messagebox.askyesno(
            "Clear Custom Folder",
            (
                "Delete everything inside the custom kneeboard folder?\n\n"
                f"{normalized}\n\n"
                "This will remove all files/subfolders in that location."
            ),
        ):
            return

        try:
            if normalized.exists():
                shutil.rmtree(normalized)
            normalized.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                "Clear Custom Folder",
                f"Failed to clear folder: {exc}",
            )
            return

        self._append_log(f"Cleared custom kneeboard folder: {normalized}")
        messagebox.showinfo(
            "Clear Custom Folder",
            f"Custom kneeboard folder cleared:\n{normalized}",
        )

    def _open_dcs_saved_games_folders(self) -> None:
        saved_games_raw = self.saved_games_var.get().strip()
        documents_raw = self.documents_var.get().strip()
        if not saved_games_raw or not documents_raw:
            messagebox.showerror(
                "Open Folders",
                "DCS Saved Games Folder and Documents paths are required.",
            )
            return

        dcs_saved_games_folder = Path(saved_games_raw)
        kneeboard_dir = dcs_saved_games_folder / "Kneeboard"
        loadouts_dir = dcs_saved_games_folder / "MissionEditor" / "UnitPayloads"
        dtc_presets_dir = Path(documents_raw) / "DCS-DTC" / "Presets"

        folders = [dcs_saved_games_folder, kneeboard_dir, loadouts_dir, dtc_presets_dir]
        opened: list[Path] = []

        try:
            for folder in folders:
                folder.mkdir(parents=True, exist_ok=True)
                os.startfile(str(folder))
                opened.append(folder)
        except OSError as exc:
            messagebox.showerror("Open Folders", f"Failed to open folders: {exc}")
            return

        self._append_log(
            f"Opened {len(opened)} folder(s) for DCS Saved Games Folder {dcs_saved_games_folder}: "
            + ", ".join(str(path) for path in opened)
        )

    def _save_config_from_ui(self) -> None:
        data = AppConfig(
            saved_games_path=self._normalize_path_text(self.saved_games_var.get().strip()),
            documents_path=self._normalize_path_text(self.documents_var.get().strip()),
            dcs_install_path=self._normalize_path_text(self.dcs_install_var.get().strip()),
            dtc_app_path=self._normalize_path_text(self.dtc_app_var.get().strip()),
            custom_kneeboard_path=self._normalize_path_text(self.custom_kneeboard_var.get().strip()),
            custom_zip_folder=self._normalize_path_text(self.custom_zip_folder_var.get().strip()),
            kill_dtc_before_launch=self.kill_dtc_before_launch_var.get(),
            last_source_zip=self._normalize_path_text(self.selected_zip_var.get().strip()),
            last_source_type=self.last_source_type,
            backup_dir=self._normalize_path_text(self.backup_dir_var.get().strip()),
            auto_install_latest_enabled=self.auto_install_latest_var.get(),
            show_restore_preview=self.show_restore_preview_var.get(),
            write_install_manifest=self.write_manifest_var.get(),
            safe_cleanup_mode=self.safe_cleanup_mode_var.get(),
            open_destinations_after_install=self.open_destinations_var.get(),
        )
        save_config(data)


def run() -> None:
    root = tk.Tk()
    DksInstallerApp(root)
    root.mainloop()
