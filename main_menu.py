"""
Main menu for launching the Ring App and Sandbox App.
"""

import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk

from ring_app.ring_ui import launch_in_toplevel as launch_ring_window
from pneumatic_cylinder_app.cylinder_ui import launch_in_toplevel as launch_pneumatic_cylinder_window
from sandbox.sandbox_app import launch_in_toplevel as launch_sandbox_window

# Launches any of the child apps. launcher is a function that takes a tk.Misc parent and launches the app in a new window.
def launch_app(root: tk.Misc, launcher, name: str) -> None:
	try:
		launcher(root)
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
		command=lambda: launch_app(root, launch_ring_window, "Ring App"),
	)
	ring_btn.pack(pady=6)

	cylinder_btn = ttk.Button(
		frame,
		text="Pneumatic Cylinder App",
		width=24,
		command=lambda: launch_app(root, launch_pneumatic_cylinder_window, "Pneumatic Cylinder App"),
	)
	cylinder_btn.pack(pady=6)

	sandbox_btn = ttk.Button(
		frame,
		text="Sandbox App",
		width=24,
		command=lambda: launch_app(root, launch_sandbox_window, "Sandbox App"),
	)
	sandbox_btn.pack(pady=6)
	root.mainloop()

main()
    