"""Simple Tkinter GUI for creating and exporting a ring with build123d.

Inputs:
- OD (mm)
- ID (mm)
- Thickness (mm)

Actions:
- Generate: validates inputs, builds CAD ring, and shows it in an interactive 3D viewport in this app.
- Export: saves the latest generated CAD ring as a STEP file.
"""

import json
import math
import os
import subprocess
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk

from build123d import Part, export_step
from PIL import Image, ImageDraw, ImageTk
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkFiltersModeling import vtkLinearExtrusionFilter
from vtkmodules.vtkFiltersSources import vtkDiskSource
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkRenderWindow, vtkRenderer
from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter

try:
	from .ring_model import build_ring
except ImportError:
	from ring_model import build_ring

_ICON_FILE = Path(__file__).parent / "ring_icon.ico"
_CONFIG_FILE = Path(__file__).parent / "ring_params.json"


def _ensure_icon() -> None:
	if _ICON_FILE.exists():
		return
	size = 64
	img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
	draw = ImageDraw.Draw(img)
	draw.ellipse([2, 2, size - 2, size - 2], fill=(90, 140, 210, 255))
	margin = size // 4
	draw.ellipse([margin, margin, size - margin, size - margin], fill=(0, 0, 0, 0))
	img.save(_ICON_FILE, format="ICO", sizes=[(64, 64), (32, 32), (16, 16)])


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
		self.renderer: vtkRenderer | None = None
		self.render_window: vtkRenderWindow | None = None
		self.ring_actor: vtkActor | None = None
		self._preview_photo: ImageTk.PhotoImage | None = None
		self._last_mouse_pos: tuple[int, int] | None = None
		self._last_pan_pos: tuple[int, int] | None = None
		self._cam_focal = [0.0, 0.0, 0.0]
		self._cam_distance = 100.0
		self._cam_yaw_deg = 35.0
		self._cam_pitch_deg = 25.0
		self._default_cam_focal = [0.0, 0.0, 0.0]
		self._default_cam_distance = 100.0
		self._default_cam_yaw_deg = 35.0
		self._default_cam_pitch_deg = 25.0

		self._build_ui()
		self._draw_empty_preview()
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
		od_entry.bind("<FocusOut>", lambda e: self.on_generate())

		ttk.Label(controls, text="ID (mm)").grid(row=0, column=2, sticky=tk.W, padx=(20, 8), pady=4)
		id_entry = ttk.Entry(controls, textvariable=self.id_var, width=12)
		id_entry.grid(row=0, column=3, sticky=tk.W, pady=4)
		id_entry.bind("<Return>", lambda e: self.on_generate())
		id_entry.bind("<FocusOut>", lambda e: self.on_generate())

		ttk.Label(controls, text="Thickness (mm)").grid(row=0, column=4, sticky=tk.W, padx=(20, 8), pady=4)
		thickness_entry = ttk.Entry(controls, textvariable=self.thickness_var, width=12)
		thickness_entry.grid(row=0, column=5, sticky=tk.W, pady=4)
		thickness_entry.bind("<Return>", lambda e: self.on_generate())
		thickness_entry.bind("<FocusOut>", lambda e: self.on_generate())

		buttons = ttk.Frame(main)
		buttons.pack(fill=tk.X, pady=(8, 8))

		ttk.Button(buttons, text="Generate", command=self.on_generate).pack(side=tk.LEFT)
		self.export_btn = ttk.Button(buttons, text="Export", command=self.on_export, state=tk.DISABLED)
		self.export_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.bambu_btn = ttk.Button(buttons, text="Open in BambuStudio", command=self.on_open_in_bambu_studio, state=tk.DISABLED)
		self.bambu_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.prusa_btn = ttk.Button(buttons, text="Open in PrusaSlicer", command=self.on_open_in_prusa_slicer, state=tk.DISABLED)
		self.prusa_btn.pack(side=tk.LEFT, padx=(8, 0))
		self.reset_view_btn = ttk.Button(buttons, text="Reset View", command=self.on_reset_view, state=tk.DISABLED)
		self.reset_view_btn.pack(side=tk.LEFT, padx=(8, 0))

		viewer_frame = ttk.Labelframe(main, text="Viewer")
		viewer_frame.pack(fill=tk.BOTH, expand=True)

		self.viewer_label = ttk.Label(viewer_frame, text="No model generated yet", anchor=tk.CENTER)
		self.viewer_label.pack(fill=tk.BOTH, expand=True)
		self.viewer_label.bind("<Configure>", self._on_preview_resize)
		self.viewer_label.bind("<ButtonPress-1>", self._on_mouse_down)
		self.viewer_label.bind("<B1-Motion>", self._on_mouse_drag)
		self.viewer_label.bind("<ButtonPress-3>", self._on_pan_down)
		self.viewer_label.bind("<B3-Motion>", self._on_pan_drag)
		self.viewer_label.bind("<MouseWheel>", self._on_mouse_wheel)

		renderer = vtkRenderer()
		renderer.SetBackground(0.95, 0.97, 0.99)
		render_window = vtkRenderWindow()
		render_window.SetOffScreenRendering(1)
		render_window.SetSize(800, 480)
		render_window.AddRenderer(renderer)
		self.renderer = renderer
		self.render_window = render_window

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
		try:
			od, inner_d, thickness = self._parse_inputs()
			self.current_part = build_ring(od, inner_d, thickness)
			self.current_dims = (od, inner_d, thickness)
			_save_params(self.od_var.get(), self.id_var.get(), self.thickness_var.get())
			self.export_btn.configure(state=tk.NORMAL)
			self.bambu_btn.configure(state=tk.NORMAL)
			self.prusa_btn.configure(state=tk.NORMAL)
			self.reset_view_btn.configure(state=tk.NORMAL)
			self._render_ring(od, inner_d, thickness)
			self.status_var.set(
				f"Generated ring: OD={od:.3f} mm, ID={inner_d:.3f} mm, thickness={thickness:.3f} mm"
			)
		except Exception as exc:
			messagebox.showerror("Generate Failed", str(exc))
			self.status_var.set("Generation failed. Check input values.")

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

	def on_reset_view(self) -> None:
		if not self.renderer:
			return
		self._cam_focal = self._default_cam_focal.copy()
		self._cam_distance = self._default_cam_distance
		self._cam_yaw_deg = self._default_cam_yaw_deg
		self._cam_pitch_deg = self._default_cam_pitch_deg
		self._apply_camera()
		self.renderer.ResetCameraClippingRange()
		self._render_to_label()

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

	def _draw_empty_preview(self) -> None:
		if not self.renderer or not self.render_window:
			return
		self.renderer.RemoveAllViewProps()
		self.renderer.ResetCamera()
		self._render_to_label()

	def _render_ring(self, od: float, inner_d: float, thickness: float) -> None:
		if not self.renderer or not self.render_window:
			return

		disk = vtkDiskSource()
		disk.SetInnerRadius(inner_d / 2.0)
		disk.SetOuterRadius(od / 2.0)
		disk.SetCircumferentialResolution(140)
		disk.SetRadialResolution(8)

		extrude = vtkLinearExtrusionFilter()
		extrude.SetInputConnection(disk.GetOutputPort())
		extrude.SetExtrusionTypeToVectorExtrusion()
		extrude.SetVector(0.0, 0.0, 1.0)
		extrude.SetScaleFactor(thickness)
		extrude.CappingOn()

		mapper = vtkPolyDataMapper()
		mapper.SetInputConnection(extrude.GetOutputPort())

		actor = vtkActor()
		actor.SetMapper(mapper)
		actor.GetProperty().SetColor(0.35, 0.55, 0.82)
		actor.GetProperty().SetSpecular(0.2)
		actor.GetProperty().SetSpecularPower(15)

		self.renderer.RemoveAllViewProps()
		self.renderer.AddActor(actor)
		self.ring_actor = actor
		self.renderer.ResetCamera()
		self._sync_camera_from_renderer()
		# Use a gentler default perspective instead of a near top-down view.
		self._cam_pitch_deg = 30.0
		self._cam_yaw_deg = 35.0
		self._apply_camera()
		self.renderer.ResetCameraClippingRange()
		self._capture_default_camera_state()
		self._render_to_label()

	def _on_preview_resize(self, event: tk.Event) -> None:
		if not self.render_window:
			return
		width = max(int(event.width), 120)
		height = max(int(event.height), 120)
		self.render_window.SetSize(width, height)
		self._render_to_label()

	def _on_mouse_down(self, event: tk.Event) -> None:
		self._last_mouse_pos = (int(event.x), int(event.y))
		self._last_pan_pos = None

	def _on_mouse_drag(self, event: tk.Event) -> None:
		if not self.renderer or self._last_mouse_pos is None:
			return
		last_x, last_y = self._last_mouse_pos
		dx = int(event.x) - last_x
		dy = int(event.y) - last_y
		self._last_mouse_pos = (int(event.x), int(event.y))

		self._cam_yaw_deg = (self._cam_yaw_deg - dx * 0.45) % 360.0
		self._cam_pitch_deg = max(-90.0, min(90.0, self._cam_pitch_deg + dy * 0.45))
		self._apply_camera()
		self.renderer.ResetCameraClippingRange()
		self._render_to_label()

	def _on_pan_down(self, event: tk.Event) -> None:
		self._last_pan_pos = (int(event.x), int(event.y))
		self._last_mouse_pos = None

	def _on_pan_drag(self, event: tk.Event) -> None:
		if not self.renderer or self._last_pan_pos is None:
			return
		last_x, last_y = self._last_pan_pos
		dx = int(event.x) - last_x
		dy = int(event.y) - last_y
		self._last_pan_pos = (int(event.x), int(event.y))

		camera = self.renderer.GetActiveCamera()
		pos = camera.GetPosition()
		focal = camera.GetFocalPoint()
		up = camera.GetViewUp()

		forward = [focal[0] - pos[0], focal[1] - pos[1], focal[2] - pos[2]]
		fwd_len = math.sqrt(forward[0] ** 2 + forward[1] ** 2 + forward[2] ** 2) or 1.0
		forward = [forward[0] / fwd_len, forward[1] / fwd_len, forward[2] / fwd_len]

		right = [
			forward[1] * up[2] - forward[2] * up[1],
			forward[2] * up[0] - forward[0] * up[2],
			forward[0] * up[1] - forward[1] * up[0],
		]
		right_len = math.sqrt(right[0] ** 2 + right[1] ** 2 + right[2] ** 2) or 1.0
		right = [right[0] / right_len, right[1] / right_len, right[2] / right_len]

		cam_up = [
			right[1] * forward[2] - right[2] * forward[1],
			right[2] * forward[0] - right[0] * forward[2],
			right[0] * forward[1] - right[1] * forward[0],
		]

		pan_scale = self._cam_distance * 0.0018
		tx = (-dx * right[0] + dy * cam_up[0]) * pan_scale
		ty = (-dx * right[1] + dy * cam_up[1]) * pan_scale
		tz = (-dx * right[2] + dy * cam_up[2]) * pan_scale

		self._cam_focal[0] += tx
		self._cam_focal[1] += ty
		self._cam_focal[2] += tz
		self._apply_camera()
		self.renderer.ResetCameraClippingRange()
		self._render_to_label()

	def _on_mouse_wheel(self, event: tk.Event) -> None:
		if not self.renderer:
			return
		if event.delta > 0:
			self._cam_distance *= 0.92
		else:
			self._cam_distance *= 1.08
		self._cam_distance = max(self._cam_distance, 0.001)
		self._apply_camera()
		self.renderer.ResetCameraClippingRange()
		self._render_to_label()

	def _sync_camera_from_renderer(self) -> None:
		if not self.renderer:
			return
		camera = self.renderer.GetActiveCamera()
		pos = camera.GetPosition()
		focal = camera.GetFocalPoint()

		vx = pos[0] - focal[0]
		vy = pos[1] - focal[1]
		vz = pos[2] - focal[2]
		dist = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0

		self._cam_focal = [float(focal[0]), float(focal[1]), float(focal[2])]
		self._cam_distance = float(dist)

		yaw = math.degrees(math.atan2(vy, vx))
		hyp = math.sqrt(vx * vx + vy * vy)
		pitch = math.degrees(math.atan2(vz, hyp))

		self._cam_yaw_deg = float(yaw % 360.0)
		self._cam_pitch_deg = float(max(-90.0, min(90.0, pitch)))

	def _capture_default_camera_state(self) -> None:
		self._default_cam_focal = self._cam_focal.copy()
		self._default_cam_distance = self._cam_distance
		self._default_cam_yaw_deg = self._cam_yaw_deg
		self._default_cam_pitch_deg = self._cam_pitch_deg

	def _apply_camera(self) -> None:
		if not self.renderer:
			return
		camera = self.renderer.GetActiveCamera()

		yaw = math.radians(self._cam_yaw_deg)
		pitch = math.radians(self._cam_pitch_deg)

		cp = math.cos(pitch)
		sp = math.sin(pitch)
		cy = math.cos(yaw)
		sy = math.sin(yaw)

		px = self._cam_focal[0] + self._cam_distance * cp * cy
		py = self._cam_focal[1] + self._cam_distance * cp * sy
		pz = self._cam_focal[2] + self._cam_distance * sp

		camera.SetFocalPoint(self._cam_focal[0], self._cam_focal[1], self._cam_focal[2])
		camera.SetPosition(px, py, pz)

		# Keep a stable reference up-vector with pitch constrained to [-90, 90].
		camera.SetViewUp(0.0, 0.0, 1.0)

	def _render_to_label(self) -> None:
		if not self.render_window:
			return

		self.render_window.Render()
		w2if = vtkWindowToImageFilter()
		w2if.SetInput(self.render_window)
		w2if.ReadFrontBufferOff()
		w2if.Update()

		img = w2if.GetOutput()
		width, height, _ = img.GetDimensions()
		if width <= 0 or height <= 0:
			return

		scalars = img.GetPointData().GetScalars()
		if scalars is None:
			return

		arr = vtk_to_numpy(scalars)
		components = scalars.GetNumberOfComponents()
		arr = arr.reshape(height, width, components)
		arr = arr[::-1, :, :]

		if components == 4:
			pil_img = Image.fromarray(arr, mode="RGBA")
		else:
			pil_img = Image.fromarray(arr[:, :, :3], mode="RGB")

		self._preview_photo = ImageTk.PhotoImage(pil_img)
		self.viewer_label.configure(image=self._preview_photo, text="")


def main() -> None:
	root = ttk.Window(themename="darkly")
	RingApp(root)
	root.minsize(640, 420)
	root.mainloop()


def launch_in_toplevel(parent: tk.Misc) -> None:
	window = tk.Toplevel(parent)
	RingApp(window)
	window.minsize(640, 420)


if __name__ == "__main__":
	main()


