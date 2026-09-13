"""Simple Tkinter GUI for creating and exporting a ring with build123d.
Can be run standalone, or launched as a subprocess from main_menu.py.

Inputs:
- OD (mm)
- ID (mm)
- Thickness (mm)

Actions:
- Generate: validates inputs, builds CAD ring, and shows it in the OCP CAD Viewer (VS Code extension).
- Export: saves the latest generated CAD ring as a STEP file.
"""

import os

import json
import sys
import subprocess
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk


# Ensure the repo root is importable so `ring_app` resolves as a package,
# whether this file is run directly, via `-m`, or imported by main_menu.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))

from build123d import Part, export_step
from ocp_vscode import show
from PIL import Image, ImageDraw
from ring_app.ring_model import build_ring

_ICON_FILE = Path(__file__).parent / "ring_icon.ico"
_CONFIG_FILE = Path(__file__).parent / "ring_params.json"


def _ensure_icon() -> None:
	if _ICON_FILE.exists():
		return
	size = 1024
	img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
	draw = ImageDraw.Draw(img)
	draw.ellipse([2, 2, size - 2, size - 2], fill=(90, 140, 210, 255))
	margin = size // 4
	draw.ellipse([margin, margin, size - margin, size - margin], fill=(0, 0, 0, 0))
	img.save(_ICON_FILE, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])


def _load_params() -> dict:
	try:
		return json.loads(_CONFIG_FILE.read_text())
	except Exception:
		return {"od": "20", "id": "10", "thickness": "5"}


def _save_params(od: str, id_: str, thickness: str) -> None:
	try:
		_CONFIG_FILE.write_text(json.dumps({"od": od, "id": id_, "thickness": thickness}))
	except Exception:
		pass


class RingApp:
	def __init__(self, root: tk.Tk | tk.Toplevel | ttk.Window) -> None:
		self.root = root
		self.root.title("Ring Generator")
		self.root.geometry("760x500")
		_ensure_icon()
		self.root.iconbitmap(str(_ICON_FILE))

		self.current_part: Part | None = None
		self.current_dims: tuple[float, float, float] | None = None  # (od, id, thickness)

		_params = _load_params()
		self.od_var = tk.StringVar(value=_params["od"])
		self.id_var = tk.StringVar(value=_params["id"])
		self.thickness_var = tk.StringVar(value=_params["thickness"])
		self.status_var = tk.StringVar(value="Enter dimensions and click Generate.")

		self._build_ui()
		self.root.after(0, self.on_generate)

	def _build_ui(self) -> None:
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
			text="No model generated yet.\nGenerate a ring to view it in the OCP CAD Viewer (VS Code extension).",
			anchor=tk.CENTER,
			justify=tk.CENTER,
		)
		self.viewer_label.pack(fill=tk.BOTH, expand=True)

		ttk.Label(main, textvariable=self.status_var, anchor=tk.W).pack(fill=tk.X, pady=(8, 0))

	def _parse_inputs(self) -> tuple[float, float, float]:
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
			od, inner_d, thickness = self._parse_inputs()
			self.current_part = build_ring(od, inner_d, thickness)
			self.current_dims = (od, inner_d, thickness)
			_save_params(self.od_var.get(), self.id_var.get(), self.thickness_var.get())
			self.export_btn.configure(state=tk.NORMAL)
			self.bambu_btn.configure(state=tk.NORMAL)
			self.prusa_btn.configure(state=tk.NORMAL)
			self.show_viewer_btn.configure(state=tk.NORMAL)
			self.viewer_label.configure(
				text=(
					f"Ring generated: OD={od:.3f} mm, ID={inner_d:.3f} mm, thickness={thickness:.3f} mm\n"
					"Shown in the OCP CAD Viewer (VS Code extension)."
				)
			)
			show(self.current_part)
			self.status_var.set(
				f"Generated ring: OD={od:.3f} mm, ID={inner_d:.3f} mm, thickness={thickness:.3f} mm"
			)
		except Exception as exc:
			if show_errors:
				messagebox.showerror("Generate Failed", str(exc))
			self.status_var.set("Generation failed. Check input values.")

	def on_show_in_viewer(self) -> None:
		if self.current_part is None:
			messagebox.showwarning("No Model", "Generate a ring before showing it in the viewer.")
			return
		show(self.current_part)

	def on_open_in_bambu_studio(self) -> None:
		if self.current_part is None:
			messagebox.showwarning("No Model", "Generate a ring before opening in BambuStudio.")
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
			messagebox.showwarning("No Model", "Generate a ring before opening in PrusaSlicer.")
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
			messagebox.showwarning("No Model", "Generate a ring before exporting.")
			return

		out_file = filedialog.asksaveasfilename(
			title="Export STEP File",
			defaultextension=".step",
			filetypes=[("STEP files", "*.step *.stp"), ("All files", "*.*")],
			initialfile="ring.step",
		)
		if not out_file:
			return

		export_step(self.current_part, str(Path(out_file)))
		self.status_var.set(f"Exported STEP file: {out_file}")
		messagebox.showinfo("Export Complete", f"Saved STEP file to:\n{out_file}")

def main() -> None:
	root = ttk.Window(themename="darkly")
	RingApp(root)
	root.minsize(640, 420)
	root.mainloop()


if __name__ == "__main__":
	main()


