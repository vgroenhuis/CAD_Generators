"""
Main menu for launching the Ring App and Sandbox App.
"""

import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk

from ring_app.ring_vincent import launch_in_toplevel as launch_ring_window
from sandbox.sandbox_app import launch_in_toplevel as launch_sandbox_window

def launch_app(root: tk.Misc, launcher, name: str) -> None:
	try:
		launcher(root)
	except Exception as exc:
		messagebox.showerror("Launch Error", f"Failed to launch {name}:\n{exc}")


def main() -> None:
	root = ttk.Window(themename="darkly")
	root.title("Main Menu")
	root.geometry("360x180")
	root.resizable(False, False)

	frame = ttk.Frame(root, padding=20)
	frame.pack(fill=tk.BOTH, expand=True)

	title = ttk.Label(frame, text="Select an app to launch", font=("Segoe UI", 12, "bold"))
	title.pack(pady=(0, 12))

	ring_btn = ttk.Button(
		frame,
		text="Launch Ring App",
		width=24,
		command=lambda: launch_app(root, launch_ring_window, "Ring App"),
	)
	ring_btn.pack(pady=6)

	sandbox_btn = ttk.Button(
		frame,
		text="Launch Sandbox App",
		width=24,
		command=lambda: launch_app(root, launch_sandbox_window, "Sandbox App"),
	)
	sandbox_btn.pack(pady=6)

	root.mainloop()


if __name__ == "__main__":
    main()
