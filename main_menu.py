"""
Main menu for launching different CAD generator apps.
"""

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
import ttkbootstrap as ttk

_APP_DIR = Path(__file__).parent
_RING_UI_SCRIPT = _APP_DIR / "ring_app" / "ring_ui.py"
_CYLINDER_UI_SCRIPT = _APP_DIR / "pneumatic_cylinder_app" / "cylinder_ui.py"
_SANDBOX_APP_SCRIPT = _APP_DIR / "sandbox" / "sandbox_app.py"

# Each child app runs standalone in its own process, so launching from the
# main menu just starts that app's script the same way a user would directly.
def launch_app_process(script_path: Path, name: str) -> None:
	try:
		subprocess.Popen([sys.executable, str(script_path)])
	except Exception as exc:
		messagebox.showerror("Launch Error", f"Failed to launch {name}:\n{exc}")


def main() -> None:
	root = ttk.Window(themename="darkly")
	root.title("Main Menu")
	root.geometry("360x260")
	root.resizable(True, True)

	frame = ttk.Frame(root, padding=20)
	frame.pack(fill=tk.BOTH, expand=True)

	title = ttk.Label(frame, text="Select an app to launch", font=("Segoe UI", 12, "bold"))
	title.pack(pady=(0, 12))

	ring_btn = ttk.Button(
		frame,
		text="Ring App",
		width=24,
		command=lambda: launch_app_process(_RING_UI_SCRIPT, "Ring App"),
	)
	ring_btn.pack(pady=6)

	cylinder_btn = ttk.Button(
		frame,
		text="Pneumatic Cylinder App",
		width=24,
		command=lambda: launch_app_process(_CYLINDER_UI_SCRIPT, "Pneumatic Cylinder App"),
	)
	cylinder_btn.pack(pady=6)

	sandbox_btn = ttk.Button(
		frame,
		text="Sandbox App",
		width=24,
		command=lambda: launch_app_process(_SANDBOX_APP_SCRIPT, "Sandbox App"),
	)
	sandbox_btn.pack(pady=6)
	root.mainloop()

main()
    