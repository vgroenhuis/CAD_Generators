import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *


def launch_in_toplevel(parent: tk.Misc) -> None:
    window = ttk.Toplevel(parent)
    window.title("Sandbox App")
    window.geometry("300x100")

    label = ttk.Label(window, text="Hello World!", font=("Segoe UI", 16, "bold"))
    label.pack(pady=20)


def main() -> None:
    root = ttk.Window(themename="darkly")
    root.title("Sandbox App")
    root.geometry("300x100")

    label = ttk.Label(root, text="Hello World!", font=("Segoe UI", 16, "bold"))
    label.pack(pady=20)

    root.mainloop()


if __name__ == "__main__":
    main()
