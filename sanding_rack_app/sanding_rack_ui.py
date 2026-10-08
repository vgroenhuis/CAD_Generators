"""Tkinter GUI for the Multiboard sanding disc rack (build123d).
Can be run standalone, or launched as a subprocess from main_menu.py.

Enter the grits with their disc counts; the planner sizes the compartments, places
the movable dividers and works out how many trays are needed.

Actions:
- Generate: plans the layout, builds the parts and shows the assembly in the OCP CAD Viewer.
- Export: writes all parts (tray, divider, one label per grit, assembly) as STEP files to a folder.
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
multiconnect = None
export_step = None
show = None
_load_error: BaseException | None = None

_CONFIG_FILE = Path(__file__).parent / "sanding_rack_params.json"

# (key, label, RackParams field, type)
_FIELDS = [
	("disc_diameter", "Disc diameter (mm)", "disc_diameter", float),
	("disc_thickness", "Disc thickness (mm)", "disc_thickness", float),
	("tray_units", "Tray width (25 mm units)", "tray_units", int),
	("back_height", "Back height (mm)", "back_height", float),
	("groove_pitch", "Divider step (mm)", "groove_pitch", float),
	("slot_scale", "Multiconnect slot scale", "slot_scale", float),
]


def _import_heavy_modules() -> None:
	global model, multiconnect, export_step, show, _load_error
	try:
		from build123d import export_step as _export_step
		from ocp_vscode import show as _show
		from sanding_rack_app import multiconnect as _multiconnect
		from sanding_rack_app import sanding_rack_model as _model
	except BaseException as exc:
		_load_error = exc
		return
	model, multiconnect, export_step, show = _model, _multiconnect, _export_step, _show


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


class SandingRackApp:
	def __init__(self, root: tk.Tk | tk.Toplevel | ttk.Window) -> None:
		self.root = root
		self.current = None
		saved = _load_params()
		defaults = model.RackParams()
		self.vars = {
			key: tk.StringVar(value=saved.get(key, f"{getattr(defaults, attr):g}"))
			for key, _, attr, _ in _FIELDS
		}
		self.grits_default = saved.get("grits", model.DEFAULT_GRITS.replace(", ", "\n"))
		self.status_var = tk.StringVar(value="Enter grits and click Generate.")
		self._build_ui()
		self.root.after(0, self.on_generate)

	def _build_ui(self) -> None:
		main = ttk.Frame(self.root, padding=12)
		main.pack(fill=tk.BOTH, expand=True)

		top = ttk.Frame(main)
		top.pack(fill=tk.BOTH, expand=True)

		grits_frame = ttk.Labelframe(top, text="Grits (grit:count, one per line)")
		grits_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))
		self.grits_text = tk.Text(grits_frame, width=18, height=18)
		self.grits_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
		self.grits_text.insert("1.0", self.grits_default)

		right = ttk.Frame(top)
		right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
		controls = ttk.Frame(right)
		controls.pack(fill=tk.X)
		for i, (key, label, _, _) in enumerate(_FIELDS):
			row, col = divmod(i, 2)
			ttk.Label(controls, text=label).grid(row=row, column=col * 2, sticky=tk.W, padx=(0 if col == 0 else 20, 8), pady=4)
			entry = ttk.Entry(controls, textvariable=self.vars[key], width=10)
			entry.grid(row=row, column=col * 2 + 1, sticky=tk.W, pady=4)
			entry.bind("<Return>", lambda e: self.on_generate())

		buttons = ttk.Frame(right)
		buttons.pack(fill=tk.X, pady=(8, 8))
		ttk.Button(buttons, text="Generate", command=self.on_generate).pack(side=tk.LEFT)
		self.export_btn = ttk.Button(buttons, text="Export STEP files...", command=self.on_export, state=tk.DISABLED)
		self.export_btn.pack(side=tk.LEFT, padx=(8, 0))
		ttk.Button(buttons, text="Export slot test piece...", command=self.on_export_test).pack(side=tk.LEFT, padx=(8, 0))
		self.show_btn = ttk.Button(buttons, text="Show in Viewer", command=self.on_show, state=tk.DISABLED)
		self.show_btn.pack(side=tk.LEFT, padx=(8, 0))

		info = ttk.Labelframe(right, text="Layout")
		info.pack(fill=tk.BOTH, expand=True)
		self.layout_text = tk.Text(info, height=10, wrap=tk.WORD, font=("Consolas", 9))
		self.layout_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
		self.layout_text.configure(state=tk.DISABLED)

		ttk.Label(main, textvariable=self.status_var, anchor=tk.W).pack(fill=tk.X, pady=(8, 0))

	def _set_layout_text(self, text: str) -> None:
		self.layout_text.configure(state=tk.NORMAL)
		self.layout_text.delete("1.0", tk.END)
		self.layout_text.insert("1.0", text)
		self.layout_text.configure(state=tk.DISABLED)

	def _parse_inputs(self):
		kwargs = {}
		for key, label, attr, typ in _FIELDS:
			try:
				kwargs[attr] = typ(self.vars[key].get())
			except ValueError as exc:
				raise ValueError(f"{label} must be {'an integer' if typ is int else 'numeric'}.") from exc
		grits_text = self.grits_text.get("1.0", tk.END).strip()
		return model.parse_grits(grits_text.replace("\n", ",")), model.RackParams(**kwargs), grits_text

	def on_generate(self) -> None:
		try:
			grits, params, grits_text = self._parse_inputs()
			self.status_var.set("Generating...")
			self.root.update_idletasks()
			self.current = (model.build_rack(grits, params), params)
			_save_params({**{k: v.get() for k, v in self.vars.items()}, "grits": grits_text})
			self.export_btn.configure(state=tk.NORMAL)
			self.show_btn.configure(state=tk.NORMAL)
			rack = self.current[0]
			n_div = sum(len(t.divider_grooves) for t in rack.trays)
			self._set_layout_text(
				model.describe_layout(rack.trays, params)
				+ f"\n\nPrint: tray x{len(rack.trays)}, divider x{n_div}, one label per grit."
				+ "\nGrooves are numbered from the left, seen from the front."
			)
			self._show()
			self.status_var.set(f"Generated rack: {len(rack.trays)} tray(s), {n_div} dividers, {len(grits)} grits")
		except Exception as exc:
			messagebox.showerror("Generate Failed", str(exc))
			self.status_var.set("Generation failed. Check input values.")

	def _show(self) -> None:
		try:
			show(self.current[0].assembly)
		except Exception:
			pass  # viewer not running; not fatal

	def on_show(self) -> None:
		if self.current is not None:
			self._show()

	def on_export(self) -> None:
		if self.current is None:
			messagebox.showwarning("No Model", "Generate the rack before exporting.")
			return
		folder = filedialog.askdirectory(title="Export STEP files to folder")
		if not folder:
			return
		rack, _ = self.current
		out = Path(folder)
		export_step(rack.assembly, str(out / "sanding_rack_assembly.step"))
		parts = model.print_parts(rack)
		for name, part in parts.items():
			export_step(part, str(out / f"sanding_rack_{name}.step"))
		self.status_var.set(f"Exported {len(parts) + 1} STEP files to {out}")
		messagebox.showinfo("Export Complete", f"Saved {len(parts) + 1} STEP files to:\n{out}")

	def on_export_test(self) -> None:
		out_file = filedialog.asksaveasfilename(
			title="Export slot test piece",
			defaultextension=".step",
			filetypes=[("STEP files", "*.step *.stp"), ("All files", "*.*")],
			initialfile="multiconnect_slot_test.step",
		)
		if out_file:
			try:
				scale = float(self.vars["slot_scale"].get())
			except ValueError:
				messagebox.showerror("Export Failed", "Multiconnect slot scale must be numeric.")
				return
			export_step(multiconnect.slot_test_piece(scale=scale), out_file)
			self.status_var.set(f"Exported slot test piece: {out_file}")


def main() -> None:
	root = ttk.Window(themename="darkly")
	root.title("Sanding Disc Rack Generator")
	root.geometry("900x520")
	root.minsize(780, 440)

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
		SandingRackApp(root)

	root.after(100, check_loaded)
	root.mainloop()


if __name__ == "__main__":
	main()
