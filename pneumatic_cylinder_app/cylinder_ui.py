"""Tkinter UI for generating and exporting pneumatic cylinder CAD geometry.

This module provides a lightweight desktop interface to:
- enter cylinder dimensions (OD, ID, thickness),
- generate a `build123d.Part` via `build_cylinder`,
- export the model as STEP,
- open the model in BambuStudio or PrusaSlicer,
- send the model to the OCP viewer.

The last-used dimension values are persisted in `cylinder_params.json`.

Can be run standalone, or launched as a subprocess from main_menu.py.

build123d takes several seconds to import (it pulls in the full OCC CAD
kernel), so the window appears immediately with a loading indicator while
that import runs on a background thread -- see main().
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk

# Ensure the repo root is importable so `pneumatic_cylinder_app` resolves as a package,
# whether this file is run directly, via `-m`, or imported by main_menu.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

from pneumatic_cylinder_app.cylinder_create_icon import ensure_icon_file

# Populated by _import_heavy_modules() on a background thread (see main()),
# since importing build123d/ocp_vscode/the model module takes several
# seconds. Nothing references these until after that thread completes.
Part = None
export_step = None
show = None
build_cylinder = None
_load_error: BaseException | None = None


def _import_heavy_modules() -> None:
	global Part, export_step, show, build_cylinder, _load_error
	try:
		from build123d import Part as _Part, export_step as _export_step
		from ocp_vscode import show as _show
		from pneumatic_cylinder_app.models.cylinder_model import build_cylinder as _build_cylinder
	except BaseException as exc:  # surfaced to the UI thread by main()
		_load_error = exc
		return
	Part, export_step, show, build_cylinder = _Part, _export_step, _show, _build_cylinder


_CONFIG_FILE = Path(__file__).parent / "cylinder_params.json"
_ICON_FILE = Path(__file__).parent / "cylinder_icon.ico"

def _load_params() -> dict:
	"""Load persisted UI dimension values, falling back to defaults on failure."""
	defaults = {"od": "20", "id": "10", "thickness": "5", "auto_show": True}
	try:
		loaded = json.loads(_CONFIG_FILE.read_text())
		if not isinstance(loaded, dict):
			return defaults
		auto_show_raw = loaded.get("auto_show", defaults["auto_show"])
		auto_show = auto_show_raw if isinstance(auto_show_raw, bool) else str(auto_show_raw).lower() in ("1", "true", "yes", "on")
		return {
			"od": str(loaded.get("od", defaults["od"])),
			"id": str(loaded.get("id", defaults["id"])),
			"thickness": str(loaded.get("thickness", defaults["thickness"])),
			"auto_show": auto_show,
		}
	except Exception:
		return defaults


def _save_params(od: str, id_: str, thickness: str, auto_show: bool) -> None:
	"""Persist current UI dimension values; ignore write errors silently."""
	try:
		_CONFIG_FILE.write_text(json.dumps({"od": od, "id": id_, "thickness": thickness, "auto_show": bool(auto_show)}))
	except Exception:
		pass


class CylinderApp:
	"""Main cylinder generator window controller and event handlers."""

	def __init__(self, root: tk.Tk | tk.Toplevel | ttk.Window) -> None:
		"""Initialize state, ensure icon exists, build widgets, and auto-generate once."""
		self.root = root
		self.root.title("Cylinder Generator")
		ensure_icon_file(_ICON_FILE)
		self.root.iconbitmap(str(_ICON_FILE))

		self.current_part: Part | None = None
		self.current_dims: tuple[float, float, float] | None = None  # (od, id, thickness)

		_params = _load_params()
		self.od_var = tk.StringVar(value=_params["od"])
		self.id_var = tk.StringVar(value=_params["id"])
		self.thickness_var = tk.StringVar(value=_params["thickness"])
		self.auto_show_var = tk.BooleanVar(value=bool(_params["auto_show"]))
		self.status_var = tk.StringVar(value="Enter dimensions and click Generate.")

		self._build_ui()
		self._fit_window_to_content()
		self.root.after(0, self.on_generate)

	def _fit_window_to_content(self) -> None:
		"""Size the initial window to fit all controls, including the full button row."""
		self.root.update_idletasks()
		req_width = self.root.winfo_reqwidth()
		req_height = self.root.winfo_reqheight()
		self.root.geometry(f"{req_width}x{req_height}")
		self.root.minsize(req_width, req_height)

	def _update_status_wraplength(self, event: tk.Event) -> None:
		"""Keep status label wrapping aligned with current content width."""
		self.status_label.configure(wraplength=max(120, event.width - 24))

	def _build_ui(self) -> None:
		"""Construct all form inputs, action buttons, and status label widgets."""
		main = ttk.Frame(self.root, padding=12)
		main.pack(fill=tk.BOTH, expand=True)

		controls = ttk.Frame(main)
		controls.pack(fill=tk.X)

		ttk.Label(controls, text="OD (mm)").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
		od_entry = ttk.Entry(controls, textvariable=self.od_var, width=12)
		od_entry.grid(row=0, column=1, sticky=tk.W, pady=4)
		od_entry.bind("<Return>", lambda e: self.on_generate())
		od_entry.bind("<FocusOut>", lambda e: self._on_generate_silent())

		ttk.Label(controls, text="ID (mm)").grid(row=0, column=2, sticky=tk.W, padx=(20, 8), pady=4)
		id_entry = ttk.Entry(controls, textvariable=self.id_var, width=12)
		id_entry.grid(row=0, column=3, sticky=tk.W, pady=4)
		id_entry.bind("<Return>", lambda e: self.on_generate())
		id_entry.bind("<FocusOut>", lambda e: self._on_generate_silent())

		ttk.Label(controls, text="Thickness (mm)").grid(row=0, column=4, sticky=tk.W, padx=(20, 8), pady=4)
		thickness_entry = ttk.Entry(controls, textvariable=self.thickness_var, width=12)
		thickness_entry.grid(row=0, column=5, sticky=tk.W, pady=4)
		thickness_entry.bind("<Return>", lambda e: self.on_generate())
		thickness_entry.bind("<FocusOut>", lambda e: self._on_generate_silent())

		buttons = ttk.Frame(main)
		buttons.pack(fill=tk.X, pady=(8, 8))

		primary_buttons = ttk.Frame(buttons)
		primary_buttons.pack(fill=tk.X)
		secondary_buttons = ttk.Frame(buttons)
		secondary_buttons.pack(fill=tk.X, pady=(6, 0))

		ttk.Button(primary_buttons, text="Generate", command=self.on_generate).pack(side=tk.LEFT)
		self.ocp_btn = ttk.Button(primary_buttons, text="Show in CAD Viewer", command=self.on_show_in_ocp, state=tk.DISABLED, bootstyle="info")
		self.ocp_btn.pack(side=tk.LEFT, padx=(8, 0))
		ttk.Checkbutton(
			primary_buttons,
			text="Auto-show when generating",
			variable=self.auto_show_var,
			command=lambda: _save_params(self.od_var.get(), self.id_var.get(), self.thickness_var.get(), self.auto_show_var.get()),
		).pack(side=tk.LEFT, padx=(16, 0))
		self.export_btn = ttk.Button(secondary_buttons, text="Export STEP", command=self.on_export, state=tk.DISABLED)
		self.export_btn.pack(side=tk.LEFT)
		self.bambu_btn = ttk.Button(secondary_buttons, text="Open in BambuStudio", command=self.on_open_in_bambu_studio, state=tk.DISABLED)
		self.bambu_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.prusa_btn = ttk.Button(secondary_buttons, text="Open in PrusaSlicer", command=self.on_open_in_prusa_slicer, state=tk.DISABLED)
		self.prusa_btn.pack(side=tk.LEFT, padx=(8, 0))

		self.status_label = ttk.Label(main, textvariable=self.status_var, anchor=tk.W, justify=tk.LEFT, wraplength=120)
		self.status_label.pack(fill=tk.X, pady=(8, 0))
		main.bind("<Configure>", self._update_status_wraplength)

	def _parse_inputs(self) -> tuple[float, float, float]:
		"""Parse and validate OD/ID/thickness from text inputs.

		Returns:
			A tuple `(od, inner_d, thickness)` as floats in millimeters.

		Raises:
			ValueError: If any field is non-numeric or outside valid constraints.
		"""
		try:
			od = float(self.od_var.get())
			inner_d = float(self.id_var.get())
			thickness = float(self.thickness_var.get())
		except ValueError as exc:
			raise ValueError("OD, ID, and thickness must be numeric values.") from exc

		if od <= 0 or inner_d <= 0 or thickness <= 0:
			raise ValueError("OD, ID, and thickness must be greater than 0.")
		if od <= inner_d:
			raise ValueError("OD must be greater than ID.")

		return od, inner_d, thickness

	def on_generate(self) -> None:
		"""Generate the cylinder model, reporting failures in a dialog."""
		self._generate(show_errors=True)

	def _on_generate_silent(self) -> None:
		"""Regenerate on <FocusOut> without error dialogs.

		FocusOut also fires when switching to another window, and just before the
		Generate button's own click handler runs, so a dialog here would pop up
		duplicate errors for one problem. Failures go to the status bar instead.
		"""
		self._generate(show_errors=False)

	def _generate(self, show_errors: bool) -> None:
		"""Generate the cylinder model and enable post-generation actions."""
		try:
			od, inner_d, thickness = self._parse_inputs()
			self.current_part = build_cylinder(od, inner_d, thickness)
			self.current_dims = (od, inner_d, thickness)
			_save_params(self.od_var.get(), self.id_var.get(), self.thickness_var.get(), self.auto_show_var.get())
			self.export_btn.configure(state=tk.NORMAL)
			self.bambu_btn.configure(state=tk.NORMAL)
			self.prusa_btn.configure(state=tk.NORMAL)
			self.ocp_btn.configure(state=tk.NORMAL)
			status = f"Generated cylinder: OD={od:.3f} mm, ID={inner_d:.3f} mm, thickness={thickness:.3f} mm"

			if self.auto_show_var.get():
				try:
					show(self.current_part)
					status += " and sent to OCP Viewer."
				except Exception as exc:
					messagebox.showerror("OCP Viewer Error", f"Failed to show in OCP Viewer:\n{exc}")

			self.status_var.set(status)
		except ValueError as exc:
			self.status_var.set(f"Invalid input: {exc}")
		except Exception as exc:
			if show_errors:
				messagebox.showerror("Generate Failed", str(exc))
			self.status_var.set("Generation failed. Check input values.")

	def on_open_in_bambu_studio(self) -> None:
		"""Export a temporary STEP and launch it in BambuStudio."""
		if self.current_part is None:
			messagebox.showwarning("No Model", "Generate a cylinder before opening in BambuStudio.")
			return

		try:
			# Create a temporary STEP file
			with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
				tmp_path = tmp.name
		
			export_step(self.current_part, tmp_path)
			
			# Open with BambuStudio
			bambu_exe = Path(os.environ["PROGRAMFILES"]) / "Bambu Studio" / "bambu-studio.exe"
			subprocess.Popen([str(bambu_exe), tmp_path])
			self.status_var.set(f"Opened in BambuStudio: {tmp_path}")
		except FileNotFoundError:
			messagebox.showerror(
				"BambuStudio Not Found",
				"Could not find BambuStudio. Please ensure it is installed."
			)
			self.status_var.set("Error: BambuStudio not found.")
		except Exception as exc:
			messagebox.showerror("Error", f"Failed to open in BambuStudio: {exc}")
			self.status_var.set("Failed to open in BambuStudio.")

	def on_open_in_prusa_slicer(self) -> None:
		"""Export a temporary STEP and launch it in PrusaSlicer."""
		if self.current_part is None:
			messagebox.showwarning("No Model", "Generate a cylinder before opening in PrusaSlicer.")
			return

		try:
			# Create a temporary STEP file
			with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
				tmp_path = tmp.name
		
			export_step(self.current_part, tmp_path)
			
			# Open with PrusaSlicer
			prusa_exe = Path(os.environ["PROGRAMFILES"]) / "Prusa3D" / "PrusaSlicer" / "prusa-slicer.exe"
			subprocess.Popen([str(prusa_exe), "--single-instance", tmp_path])
			self.status_var.set(f"Opened in PrusaSlicer: {tmp_path}")
		except FileNotFoundError:
			messagebox.showerror(
				"PrusaSlicer Not Found",
				"Could not find PrusaSlicer. Please ensure it is installed."
			)
			self.status_var.set("Error: PrusaSlicer not found.")
		except Exception as exc:
			messagebox.showerror("Error", f"Failed to open in PrusaSlicer: {exc}")
			self.status_var.set("Failed to open in PrusaSlicer.")

	def on_show_in_ocp(self) -> None:
		"""Send the current model to the OCP viewer session."""
		if self.current_part is None:
			messagebox.showwarning("No Model", "Generate a cylinder before showing in OCP Viewer.")
			return
		try:
			show(self.current_part)
			self.status_var.set("Sent to OCP Viewer.")
		except Exception as exc:
			messagebox.showerror("OCP Viewer Error", f"Failed to show in OCP Viewer:\n{exc}")
			self.status_var.set("Failed to send to OCP Viewer.")

	def on_export(self) -> None:
		"""Export the current model to a user-selected STEP file path."""
		if self.current_part is None:
			messagebox.showwarning("No Model", "Generate a cylinder before exporting.")
			return

		out_file = filedialog.asksaveasfilename(
			title="Export STEP File",
			defaultextension=".step",
			filetypes=[("STEP files", "*.step *.stp"), ("All files", "*.*")],
			initialfile="cylinder.step",
		)
		if not out_file:
			return

		export_step(self.current_part, str(Path(out_file)))
		self.status_var.set(f"Exported STEP file: {out_file}")
		messagebox.showinfo("Export Complete", f"Saved STEP file to:\n{out_file}")

def main() -> None:
	root = ttk.Window(themename="darkly")
	root.title("Cylinder Generator")

	loading = ttk.Frame(root, padding=40)
	loading.pack(fill=tk.BOTH, expand=True)
	ttk.Label(loading, text="Loading build123d...", font=("Segoe UI", 12)).pack(pady=(60, 12))
	progress = ttk.Progressbar(loading, mode="indeterminate", length=280)
	progress.pack()
	progress.start(10)

	threading.Thread(target=_import_heavy_modules, daemon=True).start()

	def check_loaded() -> None:
		if build_cylinder is None and _load_error is None:
			root.after(100, check_loaded)
			return
		progress.stop()
		loading.destroy()
		if _load_error is not None:
			messagebox.showerror("Startup Failed", f"Failed to load build123d:\n{_load_error}")
			root.destroy()
			return
		CylinderApp(root)

	root.after(100, check_loaded)
	root.mainloop()


if __name__ == "__main__":
	main()
