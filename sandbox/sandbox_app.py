# This is the sandbox app for testing out ideas and concepts without affecting the main apps.

import tkinter as tk
import ttkbootstrap as ttk

# This is a simple sandbox app to test out ideas and concepts without affecting the main apps.
def _build_ui(window: tk.Toplevel | ttk.Window) -> None:
    window.title("Sandbox App")
    window.geometry("300x100")
    label = ttk.Label(window, text="Hello World!", font=("Segoe UI", 16, "bold"))
    label.pack(pady=20)

# This function is used by the main menu to launch the sandbox app in a new window.
def launch_in_toplevel(parent: tk.Misc) -> None:
    window = tk.Toplevel(parent)
    _build_ui(window)

# This function is used when launching the sandbox app directly (not from the main menu).
# def main() -> None:
#     root = ttk.Window(themename="darkly")
#     _build_ui(root)
#     root.mainloop()

# This allows the sandbox app to be run directly for testing purposes.
# if __name__ == "__main__":
#     main()
