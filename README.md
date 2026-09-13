# build123d Sandbox

A collection of Tkinter GUI applications for generating 3D models using [build123d](https://github.com/gumyr/build123d).

## Features

- **Ring Generator App** – Interactive 3D ring designer with real-time parameter updates
- **Sandbox App** – Simple demo application for testing
- **Main Menu** – Launch any app from a central hub
- **Export Options** – Save models as STEP files or open directly in BambuStudio/PrusaSlicer
- **Persistent Parameters** – Ring dimensions saved between sessions

## Installation

### Prerequisites

- Python 3.10 or higher
- Windows 10/11 (tested on Windows)

### Setup

1. Clone or navigate to the project directory:

2. Create and activate a virtual environment (optional but recommended):

3. Install dependencies from `pyproject.toml`:
   ```powershell
   pip install -e .
   ```

   Or install with development tools included:
   ```powershell
   pip install -e ".[dev]"
   ```

## Usage

### Launch via Main Menu

```powershell
python main_menu.py
```

### Launch Individual Apps

**Ring Generator:**
```powershell
python ring_app/ring_vincent.py
```

**Sandbox App:**
```powershell
python sandbox/sandbox_app.py
```

### Ring Generator Features

**Input Parameters:**
- **OD (Outer Diameter)** – Ring outer diameter in mm
- **ID (Inner Diameter)** – Ring inner diameter in mm
- **Thickness** – Ring thickness in mm

**Keyboard Shortcuts:**
- Press `<Enter>` or click another field to auto-generate the ring
- Mouse drag to rotate, right-click + drag to pan, scroll wheel to zoom

**Export Options:**
- **Export** – Save as STEP file (.step/.stp)
- **Open in BambuStudio** – Direct model import for 3D printing slicing
- **Open in PrusaSlicer** – Alternative slicing software
- **Reset View** – Reset 3D camera to default position

**Auto Features:**
- Parameters persist across sessions (stored in `ring_params.json`)
- Model auto-generates on startup with last-used parameters
- Auto-generates when input fields lose focus

## Configuration Files

- `ring_params.json` – Saved ring dimensions (OD, ID, thickness)
- `ring_icon.ico` – Custom app icon (auto-generated on first run)

## Available Commands (Entry Points)

After installing with `pip install -e .`:

```powershell
ring-app          # Launch Ring Generator
sandbox-app       # Launch Sandbox App
```

## Project Structure

```
sandbox/
├── main_menu.py              # Central launcher
├── ring_app/
│   ├── ring_vincent.py       # Ring Generator application
│   ├── ring_model.py         # build123d ring model builder
│   ├── ring_params.json      # Saved parameters (auto-created)
│   └── ring_icon.ico         # App icon (auto-created)
├── sandbox/
│   └── sandbox_app.py        # Simple demo app
├── pyproject.toml            # Project configuration
├── README.md                 # This file
└── launch.bat                # Batch launcher (calls venv + main_menu.py)
```

## Dependencies

### Core
- **build123d** – CAD modeling library
- **ttkbootstrap** – Modern ttk themes
- **Pillow** – Image processing
- **vtkmodules** – 3D rendering engine

### Development
- **ruff** – Fast Python linter
- **black** – Code formatter
- **mypy** – Static type checker

## Development

Format code:
```powershell
black .
```

Lint code:
```powershell
ruff check .
```

Type check:
```powershell
mypy ring_app/ring_vincent.py
```

## Notes

- BambuStudio and PrusaSlicer must be installed for the direct-open features to work
- Models are exported to temporary files when opening in external apps
- The 3D viewer uses VTK for hardware-accelerated rendering
- Temporary STEP files are created in the system temp directory

## License

MIT

## Disclaimer

AI tools were used to generate Python scripts and this documentation.

## Author

Vincent Groenhuis
