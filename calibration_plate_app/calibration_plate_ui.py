"""Tkinter GUI for creating a two-colour camera calibration plate with build123d.
Can be run standalone, or launched as a subprocess from main_menu.py.

Top face: checkerboard. Bottom face: Kalibr-style AprilGrid (tag36h11).

Actions:
- Generate: builds the plate and shows it in the OCP CAD Viewer (VS Code extension).
- Export: saves a STEP file with two bodies ("white" and "black") for multimaterial
  printing, plus Kalibr target YAML files for both patterns next to it.
"""

from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

# Populated on a background thread (see main()); build123d takes seconds to import.
model = None
show = None
_load_error: BaseException | None = None

_CONFIG_FILE = Path(__file__).parent / "calibration_plate_params.json"

# (key, label, PlateParams field, type)
_FIELDS = [
	("width", "Width (mm)", "width", float),
	("length", "Length (mm)", "length", float),
	("thickness", "Thickness (mm)", "thickness", float),
	("depth", "Black depth (mm)", "depth", float),
	("margin", "Min. margin (mm)", "margin", float),
	("square_size", "Checker square (mm)", "square_size", float),
	("tag_size", "Tag size (mm)", "tag_size", float),
	("tag_spacing", "Tag spacing (ratio)", "tag_spacing", float),
	("border_bits", "Tag border bits (1/2)", "border_bits", int),
	("first_tag_id", "First tag ID", "first_tag_id", int),
]


def _import_heavy_modules() -> None:
	global model, show, _load_error
	try:
		from ocp_vscode import show as _show
		from calibration_plate_app import calibration_plate_model as _model
	except BaseException as exc:
		_load_error = exc
		return
	model, show = _model, _show


def _load_params() -> dict:
	try:
		return json.loads(_CONFIG_FILE.read_text())
	except Exception:
		return {}


def _save_params(params: dict) -> None:
	try:
		_CONFIG_FILE.write_text(json.dumps(params))
	except Exception:
		pass


class CalibrationPlateApp:
	def __init__(self, root: tk.Tk | tk.Toplevel | ttk.Window) -> None:
		self.root = root
		self.current_plate = None
		self.current_layout = None
		self.current_params = None
		saved = _load_params()
		defaults = model.PlateParams()
		self.vars = {
			key: tk.StringVar(value=saved.get(key, f"{getattr(defaults, attr):g}"))
			for key, _, attr, _ in _FIELDS
		}
		self.corner_var = tk.BooleanVar(value=saved.get("corner_squares", defaults.corner_squares))
		self.status_var = tk.StringVar(value="Enter parameters and click Generate.")
		self.info_var = tk.StringVar(value="")
		self.warning_var = tk.StringVar(value="")
		self._build_ui()
		self.root.after(0, self.on_generate)

	def _build_ui(self) -> None:
		main = ttk.Frame(self.root, padding=12)
		main.pack(fill=tk.BOTH, expand=True)
		controls = ttk.Frame(main)
		controls.pack(fill=tk.X)
		for i, (key, label, _, _) in enumerate(_FIELDS):
			row, col = divmod(i, 3)
			ttk.Label(controls, text=label).grid(row=row, column=col * 2, sticky=tk.W, padx=(0 if col == 0 else 20, 8), pady=4)
			entry = ttk.Entry(controls, textvariable=self.vars[key], width=10)
			entry.grid(row=row, column=col * 2 + 1, sticky=tk.W, pady=4)
			entry.bind("<Return>", lambda e: self.on_generate())
		ttk.Checkbutton(controls, text="Corner squares (Kalibr)", variable=self.corner_var).grid(
			row=(len(_FIELDS) - 1) // 3, column=4, columnspan=2, sticky=tk.W, padx=(20, 0)
		)
		# Border bits and corner squares belong together; warn as soon as either changes.
		self.corner_var.trace_add("write", lambda *_: self._update_warning())
		self.vars["border_bits"].trace_add("write", lambda *_: self._update_warning())
		ttk.Label(main, textvariable=self.warning_var, bootstyle="warning", wraplength=800, justify=tk.LEFT).pack(
			fill=tk.X, pady=(6, 0)
		)

		buttons = ttk.Frame(main)
		buttons.pack(fill=tk.X, pady=(8, 8))
		ttk.Button(buttons, text="Generate", command=self.on_generate).pack(side=tk.LEFT)
		self.export_btn = ttk.Button(buttons, text="Export STEP", command=self.on_export, state=tk.DISABLED)
		self.export_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.show_btn = ttk.Button(buttons, text="Show in Viewer", command=self.on_show, state=tk.DISABLED)
		self.show_btn.pack(side=tk.LEFT, padx=(8, 0))

		info = ttk.Labelframe(main, text="Model")
		info.pack(fill=tk.BOTH, expand=True)
		ttk.Label(info, textvariable=self.info_var, anchor=tk.NW, justify=tk.LEFT, font=("Consolas", 9)).pack(
			fill=tk.BOTH, expand=True, padx=8, pady=8
		)
		ttk.Label(main, textvariable=self.status_var, anchor=tk.W).pack(fill=tk.X, pady=(8, 0))

	def _parse_inputs(self):
		kwargs = {}
		for key, label, attr, typ in _FIELDS:
			try:
				kwargs[attr] = typ(self.vars[key].get())
			except ValueError as exc:
				raise ValueError(f"{label} must be {'an integer' if typ is int else 'numeric'}.") from exc
		kwargs["corner_squares"] = bool(self.corner_var.get())
		return model.PlateParams(**kwargs)

	def _update_warning(self) -> None:
		try:
			bits = int(self.vars["border_bits"].get())
		except ValueError:
			return  # reported by Generate
		warning = model.pattern_warning(model.PlateParams(border_bits=bits, corner_squares=bool(self.corner_var.get())))
		self.warning_var.set(f"Warning: {warning}" if warning else "")

	def on_generate(self) -> None:
		try:
			params = self._parse_inputs()
			self._update_warning()
			self.status_var.set("Generating... (this can take up to a minute)")
			self.root.update_idletasks()
			self.current_plate, self.current_layout = model.build_calibration_plate(params)
			self.current_params = params
			_save_params({**{k: v.get() for k, v in self.vars.items()}, "corner_squares": params.corner_squares})
			self.export_btn.configure(state=tk.NORMAL)
			self.show_btn.configure(state=tk.NORMAL)
			lay = self.current_layout
			last_id = params.first_tag_id + lay.tag_cols * lay.tag_rows - 1
			self.info_var.set(
				f"Top: checkerboard {lay.checker_cols}x{lay.checker_rows} squares "
				f"({lay.checker_cols - 1}x{lay.checker_rows - 1} inner corners)\n"
				f"Bottom: AprilGrid {lay.tag_cols}x{lay.tag_rows} tag36h11 tags, ids {params.first_tag_id}-{last_id}\n\n"
				+ lay.kalibr_yaml(params)
			)
			self._show()
			self.status_var.set(f"Generated plate {params.width:g} x {params.length:g} x {params.thickness:g} mm")
		except Exception as exc:
			messagebox.showerror("Generate Failed", str(exc))
			self.status_var.set("Generation failed. Check input values.")

	def _show(self) -> None:
		try:
			show(self.current_plate)
		except Exception:
			pass  # viewer not running; not fatal

	def on_show(self) -> None:
		if self.current_plate is not None:
			self._show()

	def on_export(self) -> None:
		if self.current_plate is None:
			messagebox.showwarning("No Model", "Generate a plate before exporting.")
			return
		out_file = filedialog.asksaveasfilename(
			title="Export STEP File",
			defaultextension=".step",
			filetypes=[("STEP files", "*.step *.stp"), ("All files", "*.*")],
			initialfile="calibration_plate.step",
		)
		if not out_file:
			return
		out = Path(out_file)
		model.export_calibration_plate(self.current_plate, str(out))
		aprilgrid_yaml = out.with_name(out.stem + "_aprilgrid.yaml")
		checker_yaml = out.with_name(out.stem + "_checkerboard.yaml")
		aprilgrid_yaml.write_text(self.current_layout.kalibr_yaml(self.current_params))
		checker_yaml.write_text(self.current_layout.checkerboard_yaml(self.current_params))
		self.status_var.set(f"Exported STEP file: {out}")
		messagebox.showinfo(
			"Export Complete",
			f"Saved STEP file to:\n{out}\n\nKalibr target files:\n{aprilgrid_yaml.name}\n{checker_yaml.name}",
		)


def main() -> None:
	root = ttk.Window(themename="darkly")
	root.title("Calibration Plate Generator")
	root.geometry("860x460")
	root.minsize(760, 400)

	loading = ttk.Frame(root, padding=40)
	loading.pack(fill=tk.BOTH, expand=True)
	ttk.Label(loading, text="Loading build123d...", font=("Segoe UI", 12)).pack(pady=(60, 12))
	progress = ttk.Progressbar(loading, mode="indeterminate", length=280)
	progress.pack()
	progress.start(10)

	threading.Thread(target=_import_heavy_modules, daemon=True).start()

	def check_loaded() -> None:
		if model is None and _load_error is None:
			root.after(100, check_loaded)
			return
		progress.stop()
		loading.destroy()
		if _load_error is not None:
			messagebox.showerror("Startup Failed", f"Failed to load build123d:\n{_load_error}")
			root.destroy()
			return
		CalibrationPlateApp(root)

	root.after(100, check_loaded)
	root.mainloop()


if __name__ == "__main__":
	main()
