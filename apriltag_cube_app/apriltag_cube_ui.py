"""Tkinter GUI for creating a two-colour AprilTag (tag16h5) cube with build123d.
Can be run standalone, or launched as a subprocess from main_menu.py.

Inputs:
- Tag ID (0-29, AprilTag family tag16h5)
- Cube size (mm)
- Black layer depth (mm)

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
export_apriltag_cube = None
show = None
_load_error: BaseException | None = None

_CONFIG_FILE = Path(__file__).parent / "apriltag_cube_params.json"
_DEFAULTS = {"tag_id": "0", "size": "30", "depth": "1"}


def _import_heavy_modules() -> None:
	global build_apriltag_cube, export_apriltag_cube, show, _load_error
	try:
		from ocp_vscode import show as _show
		from apriltag_cube_app.apriltag_cube_model import build_apriltag_cube as _b, export_apriltag_cube as _e
	except BaseException as exc:
		_load_error = exc
		return
	build_apriltag_cube, export_apriltag_cube, show = _b, _e, _show


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
		self.id_var = tk.StringVar(value=p["tag_id"])
		self.size_var = tk.StringVar(value=p["size"])
		self.depth_var = tk.StringVar(value=p["depth"])
		self.status_var = tk.StringVar(value="Enter parameters and click Generate.")
		self._build_ui()
		self.root.after(0, self.on_generate)

	def _build_ui(self) -> None:
		main = ttk.Frame(self.root, padding=12)
		main.pack(fill=tk.BOTH, expand=True)
		controls = ttk.Frame(main)
		controls.pack(fill=tk.X)
		for col, (label, var) in enumerate(
			[("Tag ID (0-29)", self.id_var), ("Cube size (mm)", self.size_var), ("Black depth (mm)", self.depth_var)]
		):
			ttk.Label(controls, text=label).grid(row=0, column=col * 2, sticky=tk.W, padx=(0 if col == 0 else 20, 8), pady=4)
			entry = ttk.Entry(controls, textvariable=var, width=10)
			entry.grid(row=0, column=col * 2 + 1, sticky=tk.W, pady=4)
			entry.bind("<Return>", lambda e: self.on_generate())

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
			text="The same tag16h5 code is placed on all six faces.\n"
			"The STEP file contains two bodies: 'white' (cube with pockets) and 'black' (tag cells).",
			anchor=tk.CENTER,
			justify=tk.CENTER,
		).pack(fill=tk.BOTH, expand=True)
		ttk.Label(main, textvariable=self.status_var, anchor=tk.W).pack(fill=tk.X, pady=(8, 0))

	def _parse_inputs(self) -> tuple[int, float, float]:
		try:
			tag_id = int(self.id_var.get())
			size = float(self.size_var.get())
			depth = float(self.depth_var.get())
		except ValueError as exc:
			raise ValueError("Tag ID must be an integer; size and depth must be numeric.") from exc
		return tag_id, size, depth

	def on_generate(self) -> None:
		try:
			tag_id, size, depth = self._parse_inputs()
			self.current_cube = build_apriltag_cube(tag_id, size, depth)
			_save_params({"tag_id": self.id_var.get(), "size": self.size_var.get(), "depth": self.depth_var.get()})
			self.export_btn.configure(state=tk.NORMAL)
			self.show_btn.configure(state=tk.NORMAL)
			self._show()
			self.status_var.set(f"Generated cube: tag16h5 id {tag_id}, {size:g} mm, black depth {depth:g} mm")
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
			initialfile=f"apriltag_cube_{int(self.id_var.get()):02d}.step",
		)
		if not out_file:
			return
		export_apriltag_cube(self.current_cube, out_file)
		self.status_var.set(f"Exported STEP file: {out_file}")
		messagebox.showinfo("Export Complete", f"Saved STEP file to:\n{out_file}")


def main() -> None:
	root = ttk.Window(themename="darkly")
	root.title("AprilTag Cube Generator")
	root.geometry("760x360")
	root.minsize(640, 300)

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
