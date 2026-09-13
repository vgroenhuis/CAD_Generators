# build123d Sandbox

A collection of Tkinter GUI applications for generating 3D models using [build123d](https://github.com/gumyr/build123d). Each app runs as an independent, standalone script and can also be launched from a central main menu.

## Features

- **Ring Generator App** – Parametric ring designer (OD, ID, thickness)
- **Pneumatic Cylinder App** – Parametric pneumatic cylinder with an X-ring seal
- **Powerbank Holder App** – Generates the two mounting walls for a LynXP robot powerbank holder, with wall thickness, hole spacing, and hole count all auto-derived to land on a 10 mm baseplate grid
- **Sandbox App** – Minimal demo window used to test standalone/embedded launch behavior
- **Main Menu** – Launches any app as its own process from a central hub
- **3D Viewer** – Models are shown in the [OCP CAD Viewer](https://github.com/bernhard-42/vscode-ocp-cad-viewer) VS Code extension
- **Export Options** – Save models as STEP files, or open directly in BambuStudio/PrusaSlicer
- **Persistent Parameters** – Each app remembers its last-used values between sessions

## Installation

### Prerequisites

- Python 3.10 or higher
- Windows 10/11 (tested on Windows)
- [Visual Studio Code](https://code.visualstudio.com/) with the **[OCP CAD Viewer](https://marketplace.visualstudio.com/items?itemName=bernhard-42.ocp-cad-viewer)** extension installed — this is what actually displays generated models. Open this project folder in VS Code and start the OCP CAD Viewer panel (its status bar item, or the "OCP CAD Viewer: Open Viewer" command) before generating a model; otherwise Generate/Show in Viewer will run without any visible 3D output.
- (Optional) [BambuStudio](https://bambulab.com/en/download/studio) and/or [PrusaSlicer](https://www.prusa3d.com/page/prusaslicer_424/) installed, for the "Open in ..." export buttons

### Setup

1. Clone or navigate to the project directory.

2. Create and activate a virtual environment (recommended):
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Install dependencies from `pyproject.toml`:
   ```powershell
   pip install -e .
   ```

   Or install with development tools included:
   ```powershell
   pip install -e ".[dev]"
   ```

4. Install the **OCP CAD Viewer** extension in VS Code (search the Extensions marketplace for `bernhard-42.ocp-cad-viewer`), open this project folder, and start its viewer panel. This is a one-time setup step — all four apps use it as their 3D viewer.

## Usage

### Launch via Main Menu

```powershell
python main_menu.py
```

This opens a small launcher window with a button per app. Each button starts that app as its own independent process (`subprocess.Popen`) — closing the Main Menu does not close any app you've launched from it.

### Launch Individual Apps

Every app can also be run directly, without the Main Menu:

**Ring Generator:**
```powershell
python ring_app/ring_ui.py
```

**Pneumatic Cylinder:**
```powershell
python pneumatic_cylinder_app/cylinder_ui.py
```

**Powerbank Holder:**
```powershell
python powerbank_holder_app/powerbank_holder_ui.py
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

### Pneumatic Cylinder Features

**Input Parameters:**
- **OD (Outer Diameter)** – Cylinder outer diameter in mm
- **ID (Inner Diameter)** – Cylinder bore diameter in mm
- **Thickness** – Cylinder wall thickness in mm

### Powerbank Holder Features

Generates the two side walls that run along a powerbank's long edges and mount onto a baseplate with a 10 mm rectangular hole grid.

**Input Parameters:**
- **Width** – Gap between the two walls (inner face to inner face); an exact fit against the powerbank, never loosened
- **Height** – Wall height
- **Length** – Wall length, along which the row of mounting holes runs
- **Hole Diameter** – Vertical mounting hole diameter (default 2.9 mm, sized for self-tapping screws)
- **Outer Wall Thickness** – Minimum material beyond each hole, towards the outer face

**Auto-derived (not user-editable):**
- **Wall thickness** – The smallest thickness that lands the mounting hole row exactly on the baseplate's 10 mm grid, for whatever width is entered
- **Hole spacing** – Center-to-center distance between the two walls' hole rows; always an exact multiple of 10 mm
- **Hole count** – How many holes fit along the given length; can be even or odd

### Shared Controls (Ring, Cylinder, Powerbank Holder)

**Keyboard/Focus Behavior:**
- Press `<Enter>` in a field, or click "Generate", to regenerate and show any validation errors
- Clicking away from a field (or switching windows) also auto-regenerates, but fails silently to the status bar instead of popping up an error — so switching windows or clicking Generate right after typing an invalid value never shows duplicate error dialogs

**Buttons:**
- **Generate** – Validates inputs, builds the model, and shows it in the OCP CAD Viewer
- **Export** – Save as a STEP file (.step/.stp)
- **Open in BambuStudio** – Direct model import for 3D printing slicing
- **Open in PrusaSlicer** – Alternative slicing software
- **Show in Viewer** – Re-send the current model to the OCP CAD Viewer (useful if you closed the viewer tab)

**Auto Features:**
- Parameters persist across sessions (stored per-app as `*_params.json`)
- Model auto-generates on startup with last-used parameters

## Configuration Files

Auto-created on first run, one set per app:
- `ring_app/ring_params.json`, `ring_app/ring_icon.ico`
- `pneumatic_cylinder_app/cylinder_params.json`, `pneumatic_cylinder_app/cylinder_icon.ico`
- `powerbank_holder_app/powerbank_holder_params.json`, `powerbank_holder_app/powerbank_holder_icon.ico`

## Available Commands (Entry Points)

After installing with `pip install -e .`:

```powershell
ring-app                # Launch Ring Generator
cylinder-app             # Launch Pneumatic Cylinder App
powerbank-holder-app     # Launch Powerbank Holder App
sandbox-app              # Launch Sandbox App
```

## Project Structure

```
CAD_Generators/
├── main_menu.py                        # Central launcher (spawns each app as its own process)
├── ring_app/
│   ├── ring_ui.py                      # Ring Generator application (standalone-runnable)
│   ├── ring_model.py                   # build123d ring model builder
│   ├── predefined_rings/               # Example YAML parameter files
│   ├── ring_params.json                # Saved parameters (auto-created)
│   └── ring_icon.ico                   # App icon (auto-created)
├── pneumatic_cylinder_app/
│   ├── cylinder_ui.py                  # Pneumatic Cylinder application (standalone-runnable)
│   ├── models/
│   │   ├── cylinder_model.py           # Cylinder + X-ring model builder
│   │   ├── cylinder_frame_model.py
│   │   ├── piston_model.py
│   │   └── x_ring_model.py
│   ├── predefined_cylinders/           # Example YAML parameter files
│   ├── cylinder_params.json            # Saved parameters (auto-created)
│   └── cylinder_icon.ico               # App icon (auto-created)
├── powerbank_holder_app/
│   ├── powerbank_holder_ui.py          # Powerbank Holder application (standalone-runnable)
│   ├── powerbank_holder_model.py       # Wall geometry builder (grid-aligned hole derivation)
│   ├── powerbank_holder_params.json    # Saved parameters (auto-created)
│   └── powerbank_holder_icon.ico       # App icon (auto-created)
├── sandbox/
│   ├── sandbox_app.py                  # Minimal demo app (standalone + embedded launch modes)
│   └── SPECIFICATION.md
├── pyproject.toml                      # Project configuration
└── README.md                           # This file
```

## Dependencies

### Core
- **build123d** – CAD modeling library
- **ttkbootstrap** – Modern ttk themes
- **Pillow** – Image processing (app icon generation)
- **ocp-vscode** – Sends models to the OCP CAD Viewer VS Code extension
- **pyyaml** – Reads example parameter files under `predefined_*/`

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
mypy ring_app/ring_ui.py
```

## Notes

- BambuStudio and PrusaSlicer must be installed for the direct-open features to work
- Models are exported to temporary files when opening in external apps
- 3D viewing is handled entirely by the OCP CAD Viewer VS Code extension — there is no embedded 3D viewport in these apps
- Each app is a fully independent process; the Main Menu is just a convenience launcher

## License

MIT

## Disclaimer

AI tools were used to generate Python scripts and this documentation.

## Author

Vincent Groenhuis
