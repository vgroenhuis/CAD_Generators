"""Simple Tkinter GUI for creating and exporting a LynXP powerbank holder with build123d.
Can be run standalone, or launched as a subprocess from main_menu.py.

Inputs:
- Width (mm) - gap between the two walls, inner face to inner face
- Height (mm) - wall height
- Length (mm) - wall length, along which the hole row runs
- Hole Diameter (mm) - vertical mounting hole diameter
- Outer Wall Thickness (mm) - minimum material beyond each hole, towards the outer face

Wall thickness is not user-specified: it's derived from the width so the
mounting hole row lands exactly on the baseplate's 10 mm grid. The number
of holes that fit is derived from length, and may be even or odd.

Actions:
- Generate: validates inputs, builds the CAD holder, and shows it in the OCP CAD Viewer (VS Code extension).
- Export: saves the latest generated CAD holder as a STEP file.

build123d takes several seconds to import (it pulls in the full OCC CAD
kernel), so the window appears immediately with a loading indicator while
that import runs on a background thread -- see main().
"""

from __future__ import annotations

import os

import json
import sys
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk


# Ensure the repo root is importable so `powerbank_holder_app` resolves as a package,
# whether this file is run directly, via `-m`, or imported by main_menu.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

from PIL import Image, ImageDraw

# Populated by _import_heavy_modules() on a background thread (see main()),
# since importing build123d/ocp_vscode/the model module takes several
# seconds. Nothing references these until after that thread completes.
Part = None
export_step = None
show = None
HOLE_DIAMETER = None
HOLE_OUTER_MARGIN = None
HOLE_PITCH = None
WALL_LENGTH = None
build_powerbank_holder = None
derive_hole_count = None
derive_hole_spacing = None
derive_wall_thickness = None
_load_error: BaseException | None = None


def _import_heavy_modules() -> None:
	global Part, export_step, show, _load_error
	global HOLE_DIAMETER, HOLE_OUTER_MARGIN, HOLE_PITCH, WALL_LENGTH
	global build_powerbank_holder, derive_hole_count, derive_hole_spacing, derive_wall_thickness
	try:
		from build123d import Part as _Part, export_step as _export_step
		from ocp_vscode import show as _show
		from powerbank_holder_app.powerbank_holder_model import (
			HOLE_DIAMETER as _HOLE_DIAMETER,
			HOLE_OUTER_MARGIN as _HOLE_OUTER_MARGIN,
			HOLE_PITCH as _HOLE_PITCH,
			WALL_LENGTH as _WALL_LENGTH,
			build_powerbank_holder as _build_powerbank_holder,
			derive_hole_count as _derive_hole_count,
			derive_hole_spacing as _derive_hole_spacing,
			derive_wall_thickness as _derive_wall_thickness,
		)
	except BaseException as exc:  # surfaced to the UI thread by main()
		_load_error = exc
		return
	Part, export_step, show = _Part, _export_step, _show
	HOLE_DIAMETER, HOLE_OUTER_MARGIN, HOLE_PITCH, WALL_LENGTH = (
		_HOLE_DIAMETER,
		_HOLE_OUTER_MARGIN,
		_HOLE_PITCH,
		_WALL_LENGTH,
	)
	build_powerbank_holder = _build_powerbank_holder
	derive_hole_count = _derive_hole_count
	derive_hole_spacing = _derive_hole_spacing
	derive_wall_thickness = _derive_wall_thickness


_ICON_FILE = Path(__file__).parent / "powerbank_holder_icon.ico"
_CONFIG_FILE = Path(__file__).parent / "powerbank_holder_params.json"


def _ensure_icon() -> None:
	if _ICON_FILE.exists():
		return
	size = 1024
	img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
	draw = ImageDraw.Draw(img)
	# Two side walls (bars) with a row of mounting holes, facing each other.
	bar_w = int(size * 0.16)
	bar_top = int(size * 0.12)
	bar_bottom = int(size * 0.88)
	left_x = int(size * 0.16)
	right_x = int(size * 0.84) - bar_w
	hole_r = max(2, int(size * 0.035))
	hole_ys = [int(bar_top + (bar_bottom - bar_top) * f) for f in (0.18, 0.4, 0.6, 0.82)]
	for bar_x in (left_x, right_x):
		draw.rounded_rectangle([bar_x, bar_top, bar_x + bar_w, bar_bottom], radius=bar_w // 4, fill=(90, 140, 210, 255))
		for hy in hole_ys:
			hx = bar_x + bar_w // 2
			draw.ellipse([hx - hole_r, hy - hole_r, hx + hole_r, hy + hole_r], fill=(0, 0, 0, 0))
	img.save(_ICON_FILE, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])


def _load_params() -> dict:
	defaults = {
		"width": "25",
		"height": "30",
		"length": f"{WALL_LENGTH:.0f}",
		"hole_diameter": f"{HOLE_DIAMETER:.1f}",
		"outer_margin": f"{HOLE_OUTER_MARGIN:.1f}",
	}
	try:
		defaults.update(json.loads(_CONFIG_FILE.read_text()))
	except Exception:
		pass
	return defaults


def _save_params(width: str, height: str, length: str, hole_diameter: str, outer_margin: str) -> None:
	try:
		_CONFIG_FILE.write_text(
			json.dumps(
				{
					"width": width,
					"height": height,
					"length": length,
					"hole_diameter": hole_diameter,
					"outer_margin": outer_margin,
				}
			)
		)
	except Exception:
		pass


class PowerbankHolderApp:
	def __init__(self, root: tk.Tk | tk.Toplevel | ttk.Window) -> None:
		self.root = root

		self.current_part: Part | None = None
		self.current_dims: tuple[float, float, float] | None = None  # (width, height, derived thickness)

		_params = _load_params()
		self.width_var = tk.StringVar(value=_params["width"])
		self.height_var = tk.StringVar(value=_params["height"])
		self.length_var = tk.StringVar(value=_params["length"])
		self.hole_diameter_var = tk.StringVar(value=_params["hole_diameter"])
		self.outer_margin_var = tk.StringVar(value=_params["outer_margin"])
		self.status_var = tk.StringVar(value="Enter dimensions and click Generate.")

		self._build_ui()
		self.root.after(0, self.on_generate)

	def _build_ui(self) -> None:
		main = ttk.Frame(self.root, padding=12)
		main.pack(fill=tk.BOTH, expand=True)

		controls = ttk.Frame(main)
		controls.pack(fill=tk.X)

		ttk.Label(controls, text="Width (mm)").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
		width_entry = ttk.Entry(controls, textvariable=self.width_var, width=12)
		width_entry.grid(row=0, column=1, sticky=tk.W, pady=4)
		width_entry.bind("<Return>", lambda e: self.on_generate())
		width_entry.bind("<FocusOut>", lambda e: self._on_generate_silent())

		ttk.Label(controls, text="Height (mm)").grid(row=0, column=2, sticky=tk.W, padx=(20, 8), pady=4)
		height_entry = ttk.Entry(controls, textvariable=self.height_var, width=12)
		height_entry.grid(row=0, column=3, sticky=tk.W, pady=4)
		height_entry.bind("<Return>", lambda e: self.on_generate())
		height_entry.bind("<FocusOut>", lambda e: self._on_generate_silent())

		ttk.Label(controls, text="Length (mm)").grid(row=0, column=4, sticky=tk.W, padx=(20, 8), pady=4)
		length_entry = ttk.Entry(controls, textvariable=self.length_var, width=12)
		length_entry.grid(row=0, column=5, sticky=tk.W, pady=4)
		length_entry.bind("<Return>", lambda e: self.on_generate())
		length_entry.bind("<FocusOut>", lambda e: self._on_generate_silent())

		ttk.Label(controls, text="Hole Diameter (mm)").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=4)
		hole_diameter_entry = ttk.Entry(controls, textvariable=self.hole_diameter_var, width=12)
		hole_diameter_entry.grid(row=1, column=1, sticky=tk.W, pady=4)
		hole_diameter_entry.bind("<Return>", lambda e: self.on_generate())
		hole_diameter_entry.bind("<FocusOut>", lambda e: self._on_generate_silent())

		ttk.Label(controls, text="Outer Wall Thickness (mm)").grid(row=1, column=2, sticky=tk.W, padx=(20, 8), pady=4)
		outer_margin_entry = ttk.Entry(controls, textvariable=self.outer_margin_var, width=12)
		outer_margin_entry.grid(row=1, column=3, sticky=tk.W, pady=4)
		outer_margin_entry.bind("<Return>", lambda e: self.on_generate())
		outer_margin_entry.bind("<FocusOut>", lambda e: self._on_generate_silent())

		info_label = ttk.Label(
			main,
			text=(
				f"Hole pitch: {HOLE_PITCH:.0f} mm, full height (fixed)  |  "
				"Wall thickness: auto (derived from width to land holes on the grid)  |  "
				"Hole count: auto (derived from length)"
			),
			anchor=tk.W,
			justify=tk.LEFT,
		)
		info_label.pack(fill=tk.X, pady=(4, 0))
		info_label.bind("<Configure>", lambda e: e.widget.configure(wraplength=e.width))

		buttons = ttk.Frame(main)
		buttons.pack(fill=tk.X, pady=(8, 8))

		ttk.Button(buttons, text="Generate", command=self.on_generate).pack(side=tk.LEFT)
		self.export_btn = ttk.Button(buttons, text="Export", command=self.on_export, state=tk.DISABLED)
		self.export_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.bambu_btn = ttk.Button(buttons, text="Open in BambuStudio", command=self.on_open_in_bambu_studio, state=tk.DISABLED)
		self.bambu_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.prusa_btn = ttk.Button(buttons, text="Open in PrusaSlicer", command=self.on_open_in_prusa_slicer, state=tk.DISABLED)
		self.prusa_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.show_viewer_btn = ttk.Button(buttons, text="Show in Viewer", command=self.on_show_in_viewer, state=tk.DISABLED)
		self.show_viewer_btn.pack(side=tk.LEFT, padx=(8, 0))

		viewer_frame = ttk.Labelframe(main, text="Viewer")
		viewer_frame.pack(fill=tk.BOTH, expand=True)

		self.viewer_label = ttk.Label(
			viewer_frame,
			text="No model generated yet.\nGenerate a holder to view it in the OCP CAD Viewer (VS Code extension).",
			anchor=tk.CENTER,
			justify=tk.CENTER,
		)
		self.viewer_label.pack(fill=tk.BOTH, expand=True)

		status_label = ttk.Label(main, textvariable=self.status_var, anchor=tk.W, justify=tk.LEFT)
		status_label.pack(fill=tk.X, pady=(8, 0))
		status_label.bind("<Configure>", lambda e: e.widget.configure(wraplength=e.width))

	def _parse_inputs(self) -> tuple[float, float, float, float, float]:
		try:
			width = float(self.width_var.get())
			height = float(self.height_var.get())
			length = float(self.length_var.get())
			hole_diameter = float(self.hole_diameter_var.get())
			outer_margin = float(self.outer_margin_var.get())
		except ValueError as exc:
			raise ValueError(
				"Width, height, length, hole diameter, and outer wall thickness must be numeric values."
			) from exc

		if width <= 0 or height <= 0 or length <= 0 or hole_diameter <= 0 or outer_margin <= 0:
			raise ValueError(
				"Width, height, length, hole diameter, and outer wall thickness must be greater than 0."
			)

		return width, height, length, hole_diameter, outer_margin

	def on_generate(self) -> None:
		self._generate(show_errors=True)

	def _on_generate_silent(self) -> None:
		# Bound to <FocusOut>, which also fires when switching to another
		# window/app. Regenerating is a convenience here, not an explicit
		# user action, so failures update the status bar instead of popping
		# up an error dialog -- otherwise merely tabbing away (or clicking
		# Generate itself, which also triggers a FocusOut just before its
		# own click handler runs) shows duplicate popups for one problem.
		self._generate(show_errors=False)

	def _generate(self, show_errors: bool) -> None:
		try:
			width, height, length, hole_diameter, outer_margin = self._parse_inputs()
			thickness = derive_wall_thickness(width, hole_diameter=hole_diameter, outer_margin=outer_margin)
			hole_spacing = derive_hole_spacing(width, hole_diameter=hole_diameter, outer_margin=outer_margin)
			hole_count = derive_hole_count(length, hole_diameter=hole_diameter)
			self.current_part = build_powerbank_holder(
				width, height, length=length, hole_diameter=hole_diameter, outer_margin=outer_margin
			)
			self.current_dims = (width, height, thickness)
			_save_params(
				self.width_var.get(),
				self.height_var.get(),
				self.length_var.get(),
				self.hole_diameter_var.get(),
				self.outer_margin_var.get(),
			)
			self.export_btn.configure(state=tk.NORMAL)
			self.bambu_btn.configure(state=tk.NORMAL)
			self.prusa_btn.configure(state=tk.NORMAL)
			self.show_viewer_btn.configure(state=tk.NORMAL)
			self.viewer_label.configure(
				text=(
					f"Holder generated: width={width:.3f} mm, height={height:.3f} mm, length={length:.3f} mm\n"
					f"Derived thickness={thickness:.3f} mm, hole spacing (wall to wall)={hole_spacing:.3f} mm, "
					f"hole count per wall={hole_count}\n"
					"Shown in the OCP CAD Viewer (VS Code extension)."
				)
			)
			show(self.current_part)
			self.status_var.set(
				f"Generated powerbank holder: width={width:.3f} mm, height={height:.3f} mm, length={length:.3f} mm, "
				f"derived thickness={thickness:.3f} mm, hole spacing={hole_spacing:.3f} mm, hole count={hole_count}"
			)
		except Exception as exc:
			if show_errors:
				messagebox.showerror("Generate Failed", str(exc))
			self.status_var.set("Generation failed. Check input values.")

	def on_show_in_viewer(self) -> None:
		if self.current_part is None:
			messagebox.showwarning("No Model", "Generate a holder before showing it in the viewer.")
			return
		show(self.current_part)

	def on_open_in_bambu_studio(self) -> None:
		if self.current_part is None:
			messagebox.showwarning("No Model", "Generate a holder before opening in BambuStudio.")
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
		if self.current_part is None:
			messagebox.showwarning("No Model", "Generate a holder before opening in PrusaSlicer.")
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

	def on_export(self) -> None:
		if self.current_part is None:
			messagebox.showwarning("No Model", "Generate a holder before exporting.")
			return

		out_file = filedialog.asksaveasfilename(
			title="Export STEP File",
			defaultextension=".step",
			filetypes=[("STEP files", "*.step *.stp"), ("All files", "*.*")],
			initialfile="powerbank_holder.step",
		)
		if not out_file:
			return

		export_step(self.current_part, str(Path(out_file)))
		self.status_var.set(f"Exported STEP file: {out_file}")
		messagebox.showinfo("Export Complete", f"Saved STEP file to:\n{out_file}")

def main() -> None:
	root = ttk.Window(themename="darkly")
	root.title("Powerbank Holder Generator")
	root.geometry("1020x520")
	root.minsize(640, 420)
	_ensure_icon()
	root.iconbitmap(str(_ICON_FILE))

	loading = ttk.Frame(root, padding=40)
	loading.pack(fill=tk.BOTH, expand=True)
	ttk.Label(loading, text="Loading build123d...", font=("Segoe UI", 12)).pack(pady=(60, 12))
	progress = ttk.Progressbar(loading, mode="indeterminate", length=280)
	progress.pack()
	progress.start(10)

	threading.Thread(target=_import_heavy_modules, daemon=True).start()

	def check_loaded() -> None:
		if build_powerbank_holder is None and _load_error is None:
			root.after(100, check_loaded)
			return
		progress.stop()
		loading.destroy()
		if _load_error is not None:
			messagebox.showerror("Startup Failed", f"Failed to load build123d:\n{_load_error}")
			root.destroy()
			return
		PowerbankHolderApp(root)

	root.after(100, check_loaded)
	root.mainloop()


if __name__ == "__main__":
	main()
