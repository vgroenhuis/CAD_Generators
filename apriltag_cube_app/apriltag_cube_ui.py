"""Tkinter GUI for creating a two-colour AprilTag (tag16h5) cube with build123d.
Can be run standalone, or launched as a subprocess from main_menu.py.

Inputs:
- Either one tag ID (same tag on all faces) or six tag IDs (comma-separated, one per face in die
  order: 1 = +X, 2 = +Y, 3 = +Z, 4 = -Z, 5 = -Y, 6 = -X). AprilTag family tag16h5, IDs 0-29.
- Cube size (mm)
- Black layer depth (mm)
- Optional red (+X) / green (+Y) world-frame arrows on the floor beside the cube

Actions:
- Generate: builds the cube and shows it in the OCP CAD Viewer (VS Code extension).
- Export: saves a STEP file with two bodies ("white" and "black") for multimaterial printing.
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
build_apriltag_cube = None
build_apriltag_cube_grid = None
grid_dimension = None
parse_tag_ids = None
export_apriltag_cube = None
show = None
_load_error: BaseException | None = None

_CONFIG_FILE = Path(__file__).parent / "apriltag_cube_params.json"
# The tag is 6 cells wide inside a 1-cell white margin on an 8-cell face.
_TAG_FRACTION = 6 / 8
_GRID_SPACING = 2.0  # mm between cubes; keep in sync with GRID_SPACING in apriltag_cube_model.py
_DEFAULTS = {
	"tag_mode": "same",  # "same": one tag on all faces; "dice": six different tags
	"tag_id": "0",
	"tag_ids": "0,1,2,3,4,5",
	"size": "40",
	"depth": "1",
	"axes": False,
}


def _import_heavy_modules() -> None:
	global build_apriltag_cube, build_apriltag_cube_grid, grid_dimension, parse_tag_ids
	global export_apriltag_cube, show, _load_error
	try:
		from ocp_vscode import show as _show
		from apriltag_cube_app.apriltag_cube_model import (
			build_apriltag_cube as _b,
			build_apriltag_cube_grid as _g,
			export_apriltag_cube as _e,
			grid_dimension as _d,
			parse_tag_ids as _p,
		)
	except BaseException as exc:
		_load_error = exc
		return
	build_apriltag_cube_grid, grid_dimension, parse_tag_ids, show = _g, _d, _p, _show
	export_apriltag_cube = _e
	build_apriltag_cube = _b  # assigned last: main() polls this to know loading has finished


def _load_params() -> dict:
	try:
		return {**_DEFAULTS, **json.loads(_CONFIG_FILE.read_text())}
	except Exception:
		return dict(_DEFAULTS)


def _save_params(params: dict) -> None:
	try:
		_CONFIG_FILE.write_text(json.dumps(params))
	except Exception:
		pass


class AprilTagCubeApp:
	def __init__(self, root: tk.Tk | tk.Toplevel | ttk.Window) -> None:
		self.root = root
		self.current_cube = None
		p = _load_params()
		self.mode_var = tk.StringVar(value="dice" if p["tag_mode"] == "dice" else "same")
		self.id_var = tk.StringVar(value=p["tag_id"])
		self.ids_var = tk.StringVar(value=p["tag_ids"])
		self.axes_var = tk.BooleanVar(value=bool(p["axes"]))
		self.size_var = tk.StringVar(value=p["size"])
		self.depth_var = tk.StringVar(value=p["depth"])
		self.tag_size_var = tk.StringVar()
		self._syncing = False
		self._sync_tag_from_cube()
		self.size_var.trace_add("write", lambda *_: self._sync_tag_from_cube())
		self.tag_size_var.trace_add("write", lambda *_: self._sync_cube_from_tag())
		self.status_var = tk.StringVar(value="Enter parameters and click Generate.")
		self._build_ui()
		self._fit_window_to_content()
		self.root.after(0, self.on_generate)

	def _fit_window_to_content(self) -> None:
		"""Size the window to fit all controls, and don't let it shrink below that."""
		self.root.update_idletasks()
		width, height = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
		self.root.geometry(f"{width}x{height}")
		self.root.minsize(width, height)

	def _build_ui(self) -> None:
		main = ttk.Frame(self.root, padding=12)
		main.pack(fill=tk.BOTH, expand=True)
		tags = ttk.Labelframe(main, text="Tags (tag16h5, IDs 0-29)", padding=(8, 4))
		tags.pack(fill=tk.X)
		ttk.Radiobutton(
			tags, text="Same tag on all faces", value="same", variable=self.mode_var, command=self._update_mode
		).grid(row=0, column=0, sticky=tk.W, padx=(0, 16), pady=2)
		self.id_entry = ttk.Entry(tags, textvariable=self.id_var, width=24)
		self.id_entry.grid(row=0, column=1, sticky=tk.W, pady=2)
		ttk.Label(
			tags,
			text="One ID, or several (e.g. 0,1,2): one cube per ID in a square grid, "
			f"{_GRID_SPACING:g} mm apart.",
			foreground="gray",
		).grid(row=0, column=2, sticky=tk.W, padx=(12, 0))
		ttk.Radiobutton(
			tags, text="Six different tags (die order)", value="dice", variable=self.mode_var, command=self._update_mode
		).grid(row=1, column=0, sticky=tk.W, padx=(0, 16), pady=2)
		self.ids_entry = ttk.Entry(tags, textvariable=self.ids_var, width=24)
		self.ids_entry.grid(row=1, column=1, sticky=tk.W, pady=2)
		ttk.Label(
			tags,
			text="IDs for faces 1-6, comma-separated. Faces 1, 2, 3 point along +X, +Y, +Z (right-hand rule); "
			"4, 5, 6 are opposite to 3, 2, 1.",
			foreground="gray",
		).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(2, 0))
		for entry in (self.id_entry, self.ids_entry):
			entry.bind("<Return>", lambda e: self.on_generate())

		controls = ttk.Frame(main)
		controls.pack(fill=tk.X, pady=(8, 0))
		for col, (label, var) in enumerate(
			[
				("Cube size (mm)", self.size_var),
				("Tag size (mm)", self.tag_size_var),
				("Black depth (mm)", self.depth_var),
			]
		):
			ttk.Label(controls, text=label).grid(row=0, column=col * 2, sticky=tk.W, padx=(0 if col == 0 else 20, 8), pady=4)
			entry = ttk.Entry(controls, textvariable=var, width=10)
			entry.grid(row=0, column=col * 2 + 1, sticky=tk.W, pady=4)
			entry.bind("<Return>", lambda e: self.on_generate())
		ttk.Checkbutton(
			controls, text="Add red/green axes (X/Y) on floor", variable=self.axes_var, command=self.on_generate
		).grid(row=1, column=0, columnspan=6, sticky=tk.W, pady=(4, 0))
		self._update_mode()

		buttons = ttk.Frame(main)
		buttons.pack(fill=tk.X, pady=(8, 8))
		ttk.Button(buttons, text="Generate", command=self.on_generate).pack(side=tk.LEFT)
		self.export_btn = ttk.Button(buttons, text="Export STEP", command=self.on_export, state=tk.DISABLED)
		self.export_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.show_btn = ttk.Button(buttons, text="Show in Viewer", command=self.on_show, state=tk.DISABLED)
		self.show_btn.pack(side=tk.LEFT, padx=(8, 0))

		info = ttk.Labelframe(main, text="Model")
		info.pack(fill=tk.BOTH, expand=True)
		ttk.Label(
			info,
			text="The STEP file contains two bodies: 'white' (cube with pockets) and 'black' (tag cells).\n"
			"With axes enabled, 'red' (+X) and 'green' (+Y) arrows lie flat on the floor beside the cube, on its X and Y axes.",
			anchor=tk.CENTER,
			justify=tk.CENTER,
		).pack(fill=tk.BOTH, expand=True)
		ttk.Label(main, textvariable=self.status_var, anchor=tk.W).pack(fill=tk.X, pady=(8, 0))

	def _sync_tag_from_cube(self) -> None:
		if self._syncing:
			return
		try:
			value = float(self.size_var.get()) * _TAG_FRACTION
		except ValueError:
			return
		self._syncing = True
		self.tag_size_var.set(f"{value:.4g}")
		self._syncing = False

	def _sync_cube_from_tag(self) -> None:
		if self._syncing:
			return
		try:
			value = float(self.tag_size_var.get()) / _TAG_FRACTION
		except ValueError:
			return
		self._syncing = True
		self.size_var.set(f"{value:.4g}")
		self._syncing = False

	def _update_mode(self) -> None:
		"""Enable only the entry belonging to the selected tag mode."""
		dice = self.mode_var.get() == "dice"
		self.id_entry.configure(state=tk.DISABLED if dice else tk.NORMAL)
		self.ids_entry.configure(state=tk.NORMAL if dice else tk.DISABLED)

	def _tag_ids(self) -> list[int]:
		"""Tag IDs for the selected mode: one or more IDs (one cube each), or six in die order."""
		if self.mode_var.get() == "dice":
			return parse_tag_ids(self.ids_var.get(), per_face=True)
		return parse_tag_ids(self.id_var.get(), per_face=False)

	def _parse_inputs(self) -> tuple[list[int], float, float]:
		tag_ids = self._tag_ids()
		try:
			size = float(self.size_var.get())
			depth = float(self.depth_var.get())
		except ValueError as exc:
			raise ValueError("Size and depth must be numeric.") from exc
		return tag_ids, size, depth

	def on_generate(self) -> None:
		try:
			tag_ids, size, depth = self._parse_inputs()
			dice = self.mode_var.get() == "dice"
			if dice:
				self.current_cube = build_apriltag_cube(tag_ids, size, depth, axes=self.axes_var.get())
			else:
				self.current_cube = build_apriltag_cube_grid(tag_ids, size, depth, axes=self.axes_var.get())
			_save_params(
				{
					"tag_mode": self.mode_var.get(),
					"tag_id": self.id_var.get(),
					"tag_ids": self.ids_var.get(),
					"size": self.size_var.get(),
					"depth": self.depth_var.get(),
					"axes": self.axes_var.get(),
				}
			)
			self.export_btn.configure(state=tk.NORMAL)
			self.show_btn.configure(state=tk.NORMAL)
			self._show()
			ids_text = ", ".join(map(str, tag_ids))
			if not dice and len(tag_ids) > 1:
				n = grid_dimension(len(tag_ids))
				what = f"{len(tag_ids)} cubes in a {n}x{n} grid: tag16h5 ids {ids_text}"
			else:
				what = f"cube: tag16h5 {'id' if len(tag_ids) == 1 else 'ids'} {ids_text}"
			self.status_var.set(f"Generated {what}, {size:g} mm, black depth {depth:g} mm")
		except Exception as exc:
			messagebox.showerror("Generate Failed", str(exc))
			self.status_var.set("Generation failed. Check input values.")

	def _show(self) -> None:
		try:
			show(self.current_cube)
		except Exception:
			pass  # viewer not running; not fatal

	def on_show(self) -> None:
		if self.current_cube is not None:
			self._show()

	def on_export(self) -> None:
		if self.current_cube is None:
			messagebox.showwarning("No Model", "Generate a cube before exporting.")
			return
		out_file = filedialog.asksaveasfilename(
			title="Export STEP File",
			defaultextension=".step",
			filetypes=[("STEP files", "*.step *.stp"), ("All files", "*.*")],
			initialfile="apriltag_cube_" + "-".join(f"{i:02d}" for i in self._tag_ids()) + ".step",
		)
		if not out_file:
			return
		export_apriltag_cube(self.current_cube, out_file)
		self.status_var.set(f"Exported STEP file: {out_file}")
		messagebox.showinfo("Export Complete", f"Saved STEP file to:\n{out_file}")


def main() -> None:
	root = ttk.Window(themename="darkly")
	root.title("AprilTag Cube Generator")
	root.geometry("760x420")

	loading = ttk.Frame(root, padding=40)
	loading.pack(fill=tk.BOTH, expand=True)
	ttk.Label(loading, text="Loading build123d...", font=("Segoe UI", 12)).pack(pady=(60, 12))
	progress = ttk.Progressbar(loading, mode="indeterminate", length=280)
	progress.pack()
	progress.start(10)

	threading.Thread(target=_import_heavy_modules, daemon=True).start()

	def check_loaded() -> None:
		if build_apriltag_cube is None and _load_error is None:
			root.after(100, check_loaded)
			return
		progress.stop()
		loading.destroy()
		if _load_error is not None:
			messagebox.showerror("Startup Failed", f"Failed to load build123d:\n{_load_error}")
			root.destroy()
			return
		AprilTagCubeApp(root)

	root.after(100, check_loaded)
	root.mainloop()


if __name__ == "__main__":
	main()
