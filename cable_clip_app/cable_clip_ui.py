"""Tkinter GUI for the cable clip (one countersunk wood screw) with build123d.
Can be run standalone, or launched as a subprocess from main_menu.py.

Actions:
- Generate: builds the clip(s) in print orientation (on their side) and shows them in
  the OCP CAD Viewer (VS Code extension).
- Export 3MF / STEP: saves them for slicing or for CAD.
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
export_step = None
shape_to_3mf = None
show = None
_load_error: BaseException | None = None

_CONFIG_FILE = Path(__file__).parent / "cable_clip_params.json"

# (key, label, ClipParams field); all values are in mm except the angle and the count
_FIELDS = [
	("diameter", "Round cable diameter", "diameter"),
	("flat_width", "Flat cable width", "flat_width"),
	("flat_height", "Flat cable height", "flat_height"),
	("squeeze", "Squeeze", "squeeze"),
	("clip_width", "Clip width (along cable)", "clip_width"),
	("strap", "Strap thickness", "strap"),
	("tab_thickness", "Tab thickness", "tab_thickness"),
	("foot", "Foot length", "foot"),
	("screw_diameter", "Screw diameter", "screw_diameter"),
	("screw_head", "Screw head diameter", "screw_head"),
	("hole_clearance", "Hole clearance", "hole_clearance"),
	("countersink_angle", "Head angle (deg)", "countersink_angle"),
	("count", "Number of clips", "count"),
]


def _import_heavy_modules() -> None:
	global model, export_step, shape_to_3mf, show, _load_error
	try:
		from build123d import export_step as _export_step
		from ocp_vscode import show as _show
		from cad_common.mesh_export import shape_to_3mf as _shape_to_3mf
		from cable_clip_app import cable_clip_model as _model
	except BaseException as exc:
		_load_error = exc
		return
	model, export_step, shape_to_3mf, show = _model, _export_step, _shape_to_3mf, _show


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


class CableClipApp:
	def __init__(self, root: tk.Tk | tk.Toplevel | ttk.Window) -> None:
		self.root = root
		self.current = None
		saved = _load_params()
		defaults = model.ClipParams()
		self.vars = {key: tk.StringVar(value=saved.get(key, f"{getattr(defaults, attr):g}")) for key, _, attr in _FIELDS}
		self.flat_var = tk.BooleanVar(value=saved.get("flat", defaults.flat))
		self.status_var = tk.StringVar(value="Enter dimensions and click Generate.")
		self.info_var = tk.StringVar(value="")
		self._build_ui()
		self.root.after(0, self.on_generate)

	def _build_ui(self) -> None:
		main = ttk.Frame(self.root, padding=12)
		main.pack(fill=tk.BOTH, expand=True)
		controls = ttk.Frame(main)
		controls.pack(fill=tk.X)
		for i, (key, label, _) in enumerate(_FIELDS):
			row, col = divmod(i, 3)
			ttk.Label(controls, text=label).grid(row=row, column=col * 2, sticky=tk.W, padx=(0 if col == 0 else 20, 8), pady=4)
			entry = ttk.Entry(controls, textvariable=self.vars[key], width=8)
			entry.grid(row=row, column=col * 2 + 1, sticky=tk.W, pady=4)
			entry.bind("<Return>", lambda e: self.on_generate())
		ttk.Checkbutton(controls, text="Flat cable (width x height instead of a diameter)",
						variable=self.flat_var, command=self.on_generate).grid(
			row=len(_FIELDS) // 3, column=0, columnspan=6, sticky=tk.W, pady=(6, 0))

		buttons = ttk.Frame(main)
		buttons.pack(fill=tk.X, pady=(8, 8))
		ttk.Button(buttons, text="Generate", command=self.on_generate).pack(side=tk.LEFT)
		self.export_3mf_btn = ttk.Button(buttons, text="Export 3MF...", command=lambda: self.on_export("3mf"), state=tk.DISABLED)
		self.export_3mf_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.export_step_btn = ttk.Button(buttons, text="Export STEP...", command=lambda: self.on_export("step"), state=tk.DISABLED)
		self.export_step_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.show_btn = ttk.Button(buttons, text="Show in Viewer", command=self._show, state=tk.DISABLED)
		self.show_btn.pack(side=tk.LEFT, padx=(8, 0))

		ttk.Label(main, textvariable=self.info_var, anchor=tk.W, justify=tk.LEFT, wraplength=720).pack(fill=tk.X, pady=(4, 0))
		ttk.Label(main, textvariable=self.status_var, anchor=tk.W).pack(fill=tk.X, pady=(8, 0))

	def _parse_inputs(self):
		kwargs = {}
		for key, label, attr in _FIELDS:
			try:
				kwargs[attr] = int(self.vars[key].get()) if attr == "count" else float(self.vars[key].get())
			except ValueError as exc:
				raise ValueError(f"{label} must be {'a whole number' if attr == 'count' else 'numeric'}.") from exc
		kwargs["flat"] = bool(self.flat_var.get())
		return model.ClipParams(**kwargs)

	def on_generate(self) -> None:
		try:
			params = self._parse_inputs()
			self.current = (model.build_print_layout(params), params)
			_save_params({**{k: v.get() for k, v in self.vars.items()}, "flat": params.flat})
			for btn in (self.export_3mf_btn, self.export_step_btn, self.show_btn):
				btn.configure(state=tk.NORMAL)
			self.info_var.set(model.describe(params))
			self._show()
			self.status_var.set("Generated.")
		except Exception as exc:
			messagebox.showerror("Generate Failed", str(exc))
			self.status_var.set("Generation failed. Check input values.")

	def _show(self) -> None:
		if self.current is None:
			return
		try:
			show(self.current[0])
		except Exception:
			pass  # viewer not running; not fatal

	def on_export(self, fmt: str) -> None:
		if self.current is None:
			messagebox.showwarning("No Model", "Generate a part before exporting.")
			return
		part, params = self.current
		size = f"flat_{params.flat_width:g}x{params.flat_height:g}" if params.flat else f"{params.diameter:g}mm"
		name = f"cable_clip_{size}" + (f"_x{params.count}" if params.count > 1 else "")
		out_file = filedialog.asksaveasfilename(
			title=f"Export {fmt.upper()} File",
			defaultextension=f".{fmt}",
			filetypes=[("3MF files", "*.3mf")] if fmt == "3mf" else [("STEP files", "*.step *.stp")],
			initialfile=f"{name}.{fmt}",
		)
		if not out_file:
			return
		if fmt == "3mf":
			Path(out_file).write_bytes(shape_to_3mf(part, "cable_clip", tolerance=0.01))
		else:
			export_step(part, out_file)
		self.status_var.set(f"Exported: {out_file}")


def main() -> None:
	root = ttk.Window(themename="darkly")
	root.title("Cable Clip Generator")
	root.geometry("820x380")
	root.minsize(720, 340)

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
		CableClipApp(root)

	root.after(100, check_loaded)
	root.mainloop()


if __name__ == "__main__":
	main()
