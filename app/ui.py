from __future__ import annotations

import os
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
        self.root.geometry("1100x760")
        self.root.minsize(980, 680)
        self._set_window_icon()

        self.config = load_config()
        self.package_cache: dict[str, PackageInfo] = {}
        self.download_zip_paths: list[Path] = []
        self.backup_zip_paths: list[Path] = []
        self.last_source_type = self._normalize_source_type(self.config.last_source_type)

        self.selected_zip_var = tk.StringVar(value=self._normalize_path_text(self.config.last_source_zip))
        self.saved_games_var = tk.StringVar(value=self._normalize_path_text(self.config.saved_games_path))
        self.documents_var = tk.StringVar(value=self._normalize_path_text(self.config.documents_path))
        self.dcs_install_var = tk.StringVar(value=self._normalize_path_text(self.config.dcs_install_path))
        self.dtc_app_var = tk.StringVar(value=self._normalize_path_text(self.config.dtc_app_path))
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
        source_frame.grid_columnconfigure(2, weight=3)

        ttk.Label(source_frame, text="Recent Downloads (latest 10)").grid(
            row=0, column=0, padx=6, pady=4, sticky="w"
        )
        ttk.Label(source_frame, text="Recent Backups (latest 10)").grid(
            row=0, column=1, padx=6, pady=4, sticky="w"
        )

        self.downloads_list = tk.Listbox(source_frame, height=6, exportselection=False)
        self.downloads_list.grid(row=1, column=0, padx=6, pady=4, sticky="nsew")
        self.downloads_list.bind("<<ListboxSelect>>", self._on_download_selected)

        self.backups_list = tk.Listbox(source_frame, height=6, exportselection=False)
        self.backups_list.grid(row=1, column=1, padx=6, pady=4, sticky="nsew")
        self.backups_list.bind("<<ListboxSelect>>", self._on_backup_selected)

        entry_frame = ttk.Frame(source_frame)
        entry_frame.grid(row=1, column=2, padx=6, pady=4, sticky="nsew")
        entry_frame.grid_columnconfigure(0, weight=1)

        ttk.Label(entry_frame, text="Selected ZIP (download or backup)").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(entry_frame, textvariable=self.selected_zip_var).grid(
            row=1, column=0, sticky="ew", pady=(2, 6)
        )

        ttk.Button(entry_frame, text="Pick ZIP Manually...", command=self._browse_zip).grid(
            row=2, column=0, sticky="ew", pady=2
        )
        ttk.Button(entry_frame, text="Refresh ZIP Lists", command=self._refresh_sources).grid(
            row=3, column=0, sticky="ew", pady=2
        )
        ttk.Button(
            entry_frame,
            text="Install Latest Download Now",
            command=self._auto_install_latest_now,
        ).grid(row=4, column=0, sticky="ew", pady=2)

        ttk.Checkbutton(
            entry_frame,
            text="Auto-install latest Downloads ZIP on startup",
            variable=self.auto_install_latest_var,
            command=self._save_config_from_ui,
        ).grid(row=5, column=0, sticky="w", pady=(8, 0))

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

        action_frame = ttk.LabelFrame(self.root, text="Actions")
        action_frame.grid(row=2, column=0, padx=10, pady=6, sticky="ew")

        ttk.Button(action_frame, text="Validate ZIP Package", command=self._validate_package).grid(
            row=0, column=0, padx=6, pady=8, sticky="ew"
        )
        ttk.Button(
            action_frame,
            text="Install Only (Overwrite DKS Files)",
            command=lambda: self._run_install("install_only"),
        ).grid(
            row=0, column=1, padx=6, pady=8, sticky="ew"
        )
        ttk.Button(
            action_frame,
            text="Backup Current + Install",
            command=lambda: self._run_install("backup_install"),
        ).grid(row=0, column=2, padx=6, pady=8, sticky="ew")
        ttk.Button(action_frame, text="Open Logs Folder", command=self._open_logs_folder).grid(
            row=0, column=3, padx=6, pady=8, sticky="ew"
        )
        ttk.Button(
            action_frame,
            text="Open Backup Folder",
            command=self._open_backup_folder,
        ).grid(row=0, column=4, padx=6, pady=8, sticky="ew")
        ttk.Button(
            action_frame,
            text="Open DCS Saved Games Folders",
            command=self._open_dcs_saved_games_folders,
        ).grid(row=0, column=5, padx=6, pady=8, sticky="ew")

        for col in range(6):
            action_frame.grid_columnconfigure(col, weight=1)

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
        if value in {"download", "backup", "manual"}:
            return value
        return "download"

    def _set_source_type(self, source_type: str) -> None:
        self.last_source_type = self._normalize_source_type(source_type)

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

    def _refresh_sources(self) -> None:
        downloads_dir = Path.home() / "Downloads"
        backup_dir = Path(self.backup_dir_var.get().strip() or str(get_default_backup_dir()))

        self.download_zip_paths = list_recent_zip_files(downloads_dir, limit=10)
        self.backup_zip_paths = list_recent_zip_files(backup_dir, limit=10)

        self.downloads_list.delete(0, "end")
        for path in self.download_zip_paths:
            self.downloads_list.insert("end", path.name)

        self.backups_list.delete(0, "end")
        for path in self.backup_zip_paths:
            self.backups_list.insert("end", path.name)

        selected_path = self.selected_zip_var.get().strip()
        selected_exists = bool(selected_path and Path(selected_path).exists())

        if not selected_exists:
            if self.last_source_type == "backup" and self.backup_zip_paths:
                self.selected_zip_var.set(str(self.backup_zip_paths[0]))
            elif self.last_source_type == "download" and self.download_zip_paths:
                self.selected_zip_var.set(str(self.download_zip_paths[0]))
            elif self.download_zip_paths:
                self.selected_zip_var.set(str(self.download_zip_paths[0]))
                self._set_source_type("download")
            elif self.backup_zip_paths:
                self.selected_zip_var.set(str(self.backup_zip_paths[0]))
                self._set_source_type("backup")
            else:
                self.selected_zip_var.set("")

        selected_value = self.selected_zip_var.get().strip()
        self.downloads_list.selection_clear(0, "end")
        self.backups_list.selection_clear(0, "end")

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

        self._append_log(
            f"Sources refreshed: {len(self.download_zip_paths)} download ZIP(s), "
            f"{len(self.backup_zip_paths)} backup ZIP(s). Preferred source: {self.last_source_type}."
        )
        self._save_config_from_ui()

    def _on_download_selected(self, _event: object) -> None:
        selected = self.downloads_list.curselection()
        if not selected:
            return
        index = selected[0]
        if 0 <= index < len(self.download_zip_paths):
            self.selected_zip_var.set(str(self.download_zip_paths[index]))
            self._set_source_type("download")
            self._save_config_from_ui()

    def _on_backup_selected(self, _event: object) -> None:
        selected = self.backups_list.curselection()
        if not selected:
            return
        index = selected[0]
        if 0 <= index < len(self.backup_zip_paths):
            self.selected_zip_var.set(str(self.backup_zip_paths[index]))
            self._set_source_type("backup")
            self._save_config_from_ui()

    def _browse_zip(self) -> None:
        if self.last_source_type == "backup":
            initial_dir = str(Path(self.backup_dir_var.get().strip() or str(get_default_backup_dir())))
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
            self._save_config_from_ui()

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

        options = InstallOptions(
            mode=mode,
            zip_path=zip_path,
            saved_games_path=saved_games_path,
            documents_path=documents_path,
            dcs_install_path=dcs_install_path,
            dtc_app_path=dtc_app_path,
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

        if getattr(result, "dtc_manual_close_required", False):
            messagebox.showwarning(
                "Close DTC.exe",
                "The installer could not stop DTC.exe automatically.\n\n"
                "Please close DTC.exe manually before continuing.",
            )

        summary_lines = self._format_result_lines(result)

        if result.success:
            messagebox.showinfo("Install", "\n".join(summary_lines))
        else:
            messagebox.showerror("Install", "\n".join(summary_lines))

        self._refresh_sources()

    def _auto_install_latest_now(self) -> None:
        if not self.download_zip_paths:
            messagebox.showwarning("Auto Install", "No ZIP files found in Downloads.")
            return

        self.selected_zip_var.set(str(self.download_zip_paths[0]))
        self._set_source_type("download")
        self._run_install("install_only")

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
