"""
Main menu for launching the different apps.
"""

import json
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import webbrowser
from pathlib import Path
import ttkbootstrap as ttk

_APP_DIR = Path(__file__).parent
_RING_UI_SCRIPT = _APP_DIR / "ring_app" / "ring_ui.py"
_CYLINDER_UI_SCRIPT = _APP_DIR / "pneumatic_cylinder_app" / "cylinder_ui.py"
_APRILTAG_CUBE_UI_SCRIPT = _APP_DIR / "apriltag_cube_app" / "apriltag_cube_ui.py"
_SANDBOX_APP_SCRIPT = _APP_DIR / "sandbox" / "sandbox_app.py"
_POWERBANK_HOLDER_UI_SCRIPT = _APP_DIR / "powerbank_holder_app" / "powerbank_holder_ui.py"

_ocp_process = None
_ocp_lock = threading.Lock()
_SETTINGS_FILE = Path(__file__).with_name("main_menu_settings.json")


def _load_settings() -> dict:
	defaults = {
		"python_interpreter": "",
		"ocp_port": "3939",
		"auto_start_ocp": True,
		"auto_open_ocp_browser": True,
	}
	try:
		loaded = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
		if not isinstance(loaded, dict):
			return defaults
		auto_start_raw = loaded.get("auto_start_ocp", defaults["auto_start_ocp"])
		auto_start = auto_start_raw if isinstance(auto_start_raw, bool) else str(auto_start_raw).lower() in ("1", "true", "yes", "on")
		auto_open_browser_raw = loaded.get("auto_open_ocp_browser", defaults["auto_open_ocp_browser"])
		auto_open_browser = auto_open_browser_raw if isinstance(auto_open_browser_raw, bool) else str(auto_open_browser_raw).lower() in ("1", "true", "yes", "on")
		return {
			"python_interpreter": str(loaded.get("python_interpreter", defaults["python_interpreter"])),
			"ocp_port": str(loaded.get("ocp_port", defaults["ocp_port"])),
			"auto_start_ocp": auto_start,
			"auto_open_ocp_browser": auto_open_browser,
		}
	except Exception:
		return defaults


def _save_settings(
	python_interpreter: str,
	ocp_port: str,
	auto_start_ocp: bool,
	auto_open_ocp_browser: bool,
) -> None:
	try:
		_SETTINGS_FILE.write_text(
			json.dumps({
				"python_interpreter": python_interpreter,
				"ocp_port": ocp_port,
				"auto_start_ocp": bool(auto_start_ocp),
				"auto_open_ocp_browser": bool(auto_open_ocp_browser),
			}),
			encoding="utf-8",
		)
	except Exception:
		pass


def _parse_port(port_text: str) -> int:
	try:
		port = int(port_text)
	except ValueError as exc:
		raise ValueError("Port must be a number.") from exc

	if port < 1 or port > 65535:
		raise ValueError("Port must be between 1 and 65535.")
	return port


def _persist_settings_from_vars(
	python_var: tk.StringVar,
	port_var: tk.StringVar,
	auto_start_var: tk.BooleanVar,
	auto_open_browser_var: tk.BooleanVar,
) -> None:
	_save_settings(
		python_var.get().strip(),
		port_var.get().strip(),
		bool(auto_start_var.get()),
		bool(auto_open_browser_var.get()),
	)


def _browse_python_interpreter(
	root: tk.Misc,
	python_var: tk.StringVar,
	port_var: tk.StringVar,
	auto_start_var: tk.BooleanVar,
	auto_open_browser_var: tk.BooleanVar,
) -> None:
	current_value = python_var.get().strip()
	initial_dir = None
	if current_value:
		candidate = Path(current_value).expanduser()
		if candidate.is_dir():
			initial_dir = str(candidate)
		elif candidate.parent.exists():
			initial_dir = str(candidate.parent)

	selected = filedialog.askopenfilename(
		parent=root,
		title="Select Python Interpreter",
		initialdir=initial_dir,
		filetypes=[
			("Python executable", "python.exe"),
			("Executable files", "*.exe"),
			("All files", "*.*"),
		],
	)
	if not selected:
		return
	python_var.set(selected)
	_persist_settings_from_vars(python_var, port_var, auto_start_var, auto_open_browser_var)


# Each child app runs standalone in its own process, so launching from the
# main menu just starts that app's script the same way a user would directly.
def launch_app_process(script_path: Path, name: str) -> None:
	try:
		subprocess.Popen([sys.executable, str(script_path)])
	except Exception as exc:
		messagebox.showerror("Launch Error", f"Failed to launch {name}:\n{exc}")


def _is_ocp_running() -> bool:
	return _ocp_process is not None and _ocp_process.poll() is None


def open_ocp_browser(port_var: tk.StringVar) -> None:
	try:
		port = _parse_port(port_var.get().strip() or "3939")
		# Best effort: ask browser to reuse an existing tab/window for this URL.
		webbrowser.open(f'http://127.0.0.1:{port}/', new=0, autoraise=True)
	except Exception as exc:
		messagebox.showerror("Browser Error", f"Failed to open browser:\n{exc}")


def open_github_documentation() -> None:
	try:
		webbrowser.open('https://github.com/vgroenhuis/CAD_Generators')
	except Exception as exc:
		messagebox.showerror("Browser Error", f"Failed to open browser:\n{exc}")


def start_ocp_server(
	root: tk.Misc,
	python_var: tk.StringVar,
	port_var: tk.StringVar,
	auto_start_var: tk.BooleanVar,
	auto_open_browser_var: tk.BooleanVar,
	start_btn: ttk.Button,
	stop_btn: ttk.Button,
) -> None:
	global _ocp_process
	python_interpreter = python_var.get().strip() or "python"

	try:
		port = _parse_port(port_var.get().strip() or "3939")
	except ValueError as exc:
		messagebox.showerror("OCP Server", str(exc))
		return

	_persist_settings_from_vars(python_var, port_var, auto_start_var, auto_open_browser_var)

	with _ocp_lock:
		if _is_ocp_running():
			return
		try:
			_ocp_process = subprocess.Popen(
				[python_interpreter, '-m', 'ocp_vscode', '--port', str(port)]
			)
		except Exception as exc:
			messagebox.showerror("OCP Server", f"Failed to start OCP server:\n{exc}")
			return

	start_btn.configure(state=tk.DISABLED, text="OCP Server running...")
	stop_btn.configure(state=tk.NORMAL)
	if auto_open_browser_var.get():
		root.after(700, lambda: open_ocp_browser(port_var))


def stop_ocp_server(start_btn: ttk.Button, stop_btn: ttk.Button) -> None:
	global _ocp_process
	with _ocp_lock:
		if not _is_ocp_running():
			messagebox.showinfo("OCP Server", "OCP server is not running.")
			start_btn.configure(state=tk.NORMAL, text="Start OCP CAD Server")
			stop_btn.configure(state=tk.DISABLED)
			return

		assert _ocp_process is not None
		try:
			_ocp_process.terminate()
			_ocp_process.wait(timeout=5)
		except Exception:
			_ocp_process.kill()
			_ocp_process.wait(timeout=5)
		finally:
			_ocp_process = None

	start_btn.configure(state=tk.NORMAL, text="Start OCP CAD Server")
	stop_btn.configure(state=tk.DISABLED)


def _stop_ocp_server_on_exit() -> None:
	global _ocp_process
	with _ocp_lock:
		if not _is_ocp_running():
			return

		assert _ocp_process is not None
		try:
			_ocp_process.terminate()
			_ocp_process.wait(timeout=5)
		except Exception:
			_ocp_process.kill()
			_ocp_process.wait(timeout=5)
		finally:
			_ocp_process = None


def _on_main_window_close(
	root: tk.Misc,
	python_var: tk.StringVar,
	port_var: tk.StringVar,
	auto_start_var: tk.BooleanVar,
	auto_open_browser_var: tk.BooleanVar,
) -> None:
	_persist_settings_from_vars(python_var, port_var, auto_start_var, auto_open_browser_var)
	_stop_ocp_server_on_exit()
	root.destroy()


def main() -> None:
	root = ttk.Window(themename="darkly")
	root.title("Main Menu")
	root.resizable(True, True)
	settings = _load_settings()
	python_var = tk.StringVar(value=settings["python_interpreter"])
	port_var = tk.StringVar(value=settings["ocp_port"])
	auto_start_var = tk.BooleanVar(value=bool(settings["auto_start_ocp"]))
	auto_open_browser_var = tk.BooleanVar(value=bool(settings["auto_open_ocp_browser"]))

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

	powerbank_holder_btn = ttk.Button(
		frame,
		text="Powerbank Holder App",
		width=24,
		command=lambda: launch_app_process(_POWERBANK_HOLDER_UI_SCRIPT, "Powerbank Holder App"),
	)
	powerbank_holder_btn.pack(pady=6)

	apriltag_cube_btn = ttk.Button(
		frame,
		text="AprilTag Cube App",
		width=24,
		command=lambda: launch_app_process(_APRILTAG_CUBE_UI_SCRIPT, "AprilTag Cube App"),
	)
	apriltag_cube_btn.pack(pady=6)

	sandbox_btn = ttk.Button(
		frame,
		text="Sandbox App",
		width=24,
		command=lambda: launch_app_process(_SANDBOX_APP_SCRIPT, "Sandbox App"),
	)
	sandbox_btn.pack(pady=6)

	ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(10, 4))

	settings_frame = ttk.Frame(frame)
	settings_frame.pack(fill=tk.X, pady=(4, 6))

	ttk.Label(
		settings_frame,
		text="To view generated CAD models, an OCP CAD server needs to be running and the viewer opened in a browser.",
		wraplength=620,
		justify=tk.LEFT,
	).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 6))

	ttk.Label(settings_frame, text="Python interpreter:").grid(row=1, column=0, sticky=tk.W)
	python_entry = ttk.Entry(settings_frame, textvariable=python_var)
	python_entry.grid(row=1, column=1, sticky=tk.EW, padx=(8, 0))
	python_entry.bind("<FocusOut>", lambda _e: _persist_settings_from_vars(python_var, port_var, auto_start_var, auto_open_browser_var))
	browse_python_btn = ttk.Button(
		settings_frame,
		text="Browse...",
		command=lambda: _browse_python_interpreter(root, python_var, port_var, auto_start_var, auto_open_browser_var),
	)
	browse_python_btn.grid(row=1, column=2, sticky=tk.W, padx=(8, 0))

	ttk.Label(settings_frame, text="OCP CAD viewer port:").grid(row=2, column=0, sticky=tk.W, pady=(6, 0))
	port_entry = ttk.Entry(settings_frame, textvariable=port_var, width=10)
	port_entry.grid(row=2, column=1, sticky=tk.W, padx=(8, 0), pady=(6, 0))
	port_entry.bind("<FocusOut>", lambda _e: _persist_settings_from_vars(python_var, port_var, auto_start_var, auto_open_browser_var))

	auto_start_check = ttk.Checkbutton(
		settings_frame,
		text="Auto-start OCP CAD server",
		variable=auto_start_var,
		command=lambda: _persist_settings_from_vars(python_var, port_var, auto_start_var, auto_open_browser_var),
	)
	auto_start_check.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))

	auto_open_browser_check = ttk.Checkbutton(
		settings_frame,
		text="Auto-open OCP CAD viewer",
		variable=auto_open_browser_var,
		command=lambda: _persist_settings_from_vars(python_var, port_var, auto_start_var, auto_open_browser_var),
	)
	auto_open_browser_check.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))

	settings_frame.columnconfigure(1, weight=1)

	ocp_start_btn = ttk.Button(frame, text="Start OCP CAD Server", width=24, bootstyle="secondary")
	ocp_start_btn.pack(pady=4)

	ocp_stop_btn = ttk.Button(
		frame,
		text="Stop OCP CAD Server",
		width=24,
		bootstyle="primary",
		state=tk.DISABLED,
	)
	ocp_stop_btn.pack(pady=(2, 4))

	ocp_browser_btn = ttk.Button(
		frame,
		text="Open OCP CAD viewer",
		width=24,
		bootstyle="info",
		command=lambda: open_ocp_browser(port_var),
	)
	ocp_browser_btn.pack(pady=(10, 4))

	github_docs_btn = ttk.Button(
		frame,
		text="Documentation on GitHub",
		width=24,
		bootstyle="primary",
		command=open_github_documentation,
	)
	github_docs_btn.pack(pady=(2, 4))

	ocp_start_btn.configure(
		command=lambda: start_ocp_server(root, python_var, port_var, auto_start_var, auto_open_browser_var, ocp_start_btn, ocp_stop_btn)
	)
	ocp_stop_btn.configure(command=lambda: stop_ocp_server(ocp_start_btn, ocp_stop_btn))
	root.protocol("WM_DELETE_WINDOW", lambda: _on_main_window_close(root, python_var, port_var, auto_start_var, auto_open_browser_var))

	if auto_start_var.get():
		root.after(0, lambda: start_ocp_server(root, python_var, port_var, auto_start_var, auto_open_browser_var, ocp_start_btn, ocp_stop_btn))

	# Size the window to fit its actual content instead of a hard-coded
	# guess, so adding/removing a button can't leave one cut off again.
	root.update_idletasks()
	width = max(root.winfo_reqwidth(), 360)
	height = root.winfo_reqheight()
	root.geometry(f"{width}x{height}")
	root.minsize(width, height)

	root.mainloop()

if __name__ == "__main__":
	main()
