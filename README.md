# build123d Sandbox

A collection of Tkinter GUI applications for generating 3D models using [build123d](https://github.com/gumyr/build123d). Each app runs as an independent, standalone script and can also be launched from a central main menu.

## Features

- **Ring Generator App** – Parametric ring designer (OD, ID, thickness)
- **Pneumatic Cylinder App** – Parametric pneumatic cylinder with an X-ring seal
- **Powerbank Holder App** – Generates the two mounting walls for a LynXP robot powerbank holder, with wall thickness, hole spacing, and hole count all auto-derived to land on a 10 mm baseplate grid
- **AprilTag Cube App** – Cube with AprilTag tag16h5 codes (ID 0-29) on five faces and a label on the bottom face, which the camera never sees: either the same tag on all five faces (give several IDs to get one cube per ID, in the smallest square grid with 2 mm spacing, still as just one "white" and one "black" body so a slicer assigns each filament once for all cubes), five different tags given as a comma-separated list (the four sides counterclockwise as seen from above, +X, +Y, -X, -Y, then the top), or the world-frame cube (tag 29 on all five faces with the side tags turned, label "World frame", with the axes). With the same tag on all faces, the side tags are turned a quarter turn each by default (top edge up on +X, left on +Y, down on -X, right on -Y, seen from outside): a detector reports which way a tag is turned, so for an upright cube it can tell which side it sees, and the cube's heading, while each cube needs just one ID. Alternatively the bottom face carries a tag as well (then six different tags, the sixth on the bottom). The label is inlaid flush in black; by default it is the tag ID, "World frame" on the world-frame cube, or with five different tags each side's ID along the matching bottom edge and the top ID in the centre, so you can see which face has which ID; a typed label is centred, and long labels are split over two lines (`|` forces a break) as long as the strokes stay printable. By default the bottom edge of the +X face is red and that of the +Y face green (strips inlaid flush in the white margin below the tag, so the cube keeps its size, with their ends cut at 45 degrees; height and depth can be set, 1 mm each by default). Optionally adds red (+X) and green (+Y) arrows on the floor beside the cube to show the world frame. Exported as a STEP file with one body per colour ("white" and "black", plus "red" and "green" with the red/green edges and/or the axes, so two or four bodies) for multimaterial printing. Also usable headless: `python apriltag_cube_app/apriltag_cube_model.py --id 3 --size 40 --depth 0.7 --out cube.step` (`--id 0,1,2,3,4` for five tags on one cube, `--bottom-tag` for a tag on the bottom too (`--id 0,1,2,3,4,5`), `--world-frame` for the world-frame cube, `--label "My|cube"` for another label, `--cubes 0,1,2,3` for a grid of cubes, `--rotate-sides` to turn the side tags, `--edge-colours` for the red/green bottom edges (`--edge-height`, `--edge-depth` in mm), `--axes` for the arrows)
- **Calibration Plate App** – Two-colour camera calibration plate (default 300 x 320 x 10 mm): a checkerboard on the top face and a Kalibr-style AprilGrid (tag36h11) on the bottom face. Square/tag counts are derived from the plate size; exports a STEP file with "white" and "black" bodies plus Kalibr target YAML files. Also usable headless: `python calibration_plate_app/calibration_plate_model.py --out plate.step`
- **Sanding Disc Rack App** – Wall rack for round sanding discs (default 150 mm) that hangs on Multiboard via Multiconnect slots. Discs stand on edge in trays; each grit gets a compartment between movable dividers that drop into grooves every 5 mm, so compartments can be resized as stacks shrink or grow. Enter grits with their disc counts (e.g. `P120:50`): the planner sizes the compartments, places the dividers and works out how many trays are needed. Exports the tray, divider, one sliding label clip per grit (clip and raised text as separate bodies, for two-colour printing), an assembly and an optional Multiconnect slot test piece as STEP files. Also usable headless: `python sanding_rack_app/sanding_rack_model.py --out-dir rack --slot-test`
- **Orifice App** – Pneumatic tube connector with an orifice (flow restriction) between two tube sockets. Each socket has its own inner diameter, wall thickness and depth; the orifice has a diameter and length; both conical shoulders between the sockets and the orifice have the same angle to the axis (default 30°, 90° is a flat step). The sockets can taper towards the orifice (default 2° per side, 0 = straight; the given inner diameter is at the opening, and the page shows the diameter at the opening and at the bottom of each socket). Optionally a series of orifice diameters (min to max in steps) is made at once: one connection per diameter, joined into a single part by a thin wall on the build plate. Also usable headless: `python orifice_app/orifice_model.py --series --d-min 0.4 --d-max 1.2 --step 0.2 --taper 2 --out orifices.step`
- **Pneumatic Components** (web overview page `pneumatic.html`, linking to the Orifice, Blind Plug and, later, Pneumatic Cylinder generators) – Blind plug (`blind-plug.html`): a solid pin with the tube's outer diameter, chamfered tip, 45° collar and cylindrical head (presets for 4 and 6 mm tube, matching the lab's Blind1_4mm/Blind1_6mm parts), built in print orientation standing on its head, optionally several in a grid. Also usable headless: `python pneumatic_app/blind_plug_model.py --preset 6 --count 4 --out plugs.step`
  Connector (`connector.html`): the [printable pneumatic connectors](https://www.printables.com/model/148215-pneumatic-connectors) for 3 mm tube, 1-8 ports. Male part (hole diameter adjustable) with the clip set, and female part (3 mm tube from the male part, O-ring grooves for 3x1 mm O-rings that go in during a print pause at Z = 2 mm, back socket for a 4 mm tube); with the defaults both match the lab's October 2026 assembly. Any combination of male part, female part and clip set can be printed on one bed (each a separate body in the 3MF/STEP). An assembled view shows all parts with tubes and O-rings; a slider and an animation move the male part in and close the clips (they open up to where they touch the plate). Headless: `python pneumatic_app/connector_model.py --parts male,female,clips --ports 4 --out connector_4x.step`
- **Cable Clip App** – Clip for a round cable (diameter) or a flat cable (width x height), fastened with one countersunk wood screw: a strap arches over the cable, with a countersunk screw tab on one side and a foot on the other. The channel is slightly lower than the cable so the screw clamps it; the tab and hole follow from the screw head. Clips are saved on their side (strap along the layer lines, no supports), as many as you like in one file. Also usable headless: `python cable_clip_app/cable_clip_model.py --diameter 6 --count 4 --out clips.step` (`--flat --width 10 --height 3` for a flat cable)
- **Game Tiles** (web page `game-tiles.html`) – Multicolour tiles with a relief pattern for board games and game prototypes, one body per colour (named after it) for multimaterial printing. 34 types: terrain (earth, sand, a dune across the tile with a rippled windward slope and a steep slip face, grass, asphalt, cobblestone, wooden floor, bricks, a rocky mountain with a snowy top), elements (water, a sea of big 3D waves with foam on the highest crests, rain, a thunderstorm with a standing lightning bolt, ice, fire, lava) and objects (a horizontal red laser from a steel emitter with a black lens, across the tile to a target; an upright steel mirror along the diagonal, with the red beam reflected off it; sharp spikes, button, pit, arrow, start/finish, a light bulb on its screw socket, a gold key, a cartoon 100t weight on cracked earth, a fir tree standing on the grass (three tiers of foliage with flat undersides, 70 degrees from upright, on a thick trunk with roots joined to it; the trunk stops where the foliage begins, so those layers print in one colour), a sailing ship on the waves (hull sides flaring out at 27 degrees, mainsail and jib as upright plates on the deck; it sails along +X, or +Y on a tile longer in y), and a door, portal and star each lying flat or standing upright; the upright door's frame is as wide as the tile, and the upright portal is open down to the floor, so a game piece can walk through it). Shapes: square (default 40 mm), rectangle, hexagon (size across the flats), equilateral triangle and circle; thickness, colour depth, number of tiles and a variation number for the random details. Each type has small details (pebbles and dry cracks in earth, shells, crab holes and bird tracks in sand, clover in grass, edge lines on the road, moss between domed cobbles, knots in the wood, chipped bricks, lily pads and ripple rings on water, puddles in the rain, snow drifts and air bubbles in ice, charcoal round the fire, glowing cracks in about one lava rock in five (0.5 mm wide, jagged and branching, most opening onto the lava at the rock's edge), tread plate under the spikes, iron straps on the doors, screws round the button, rubble and a pair of eyes in the pit, a conveyor belt under the arrow, runes round the portal, gems in the upright portal, roots, pine cones and moss under the tree, a cabin and a wake for the ship). Natural surfaces (earth, sand, grass, cobbles, bricks, water, rain, ice, fire, lava, the pit, the portals, the tree, the ground under the weight, the cushion under the key, the floor under the light bulb and the sea under the ship, the sea, the dune, the mountain (in all directions) and the thunderstorm's ground, while the key, bulb, ship and lightning bolt themselves stay smooth) are rough in the 3MF file and preview: the mesh is subdivided and its vertices moved by smooth noise (cad_common/mesh_fuzz.py), heights only for terrain so tiles stay flat underneath and fit side by side, in all directions for the worn upright portal and the tree's trunk and foliage; the STEP file keeps the exact smooth shape. The roughness depth, bump size and hill height can be set per tile (empty: the type's own; any type can be made rough or hilly). The terrain (earth, sand, grass, cobbles, the tree's grass, the mountain's grassland) is also gently hilly in the 3MF file and preview, up to about 0.6 mm, fading out towards the edges so tiles still meet level. The bottom of every tile is a body of its own in a bottom colour of your choice (white by default, or the tile's own colour), up to a 0.2 mm layer just below the lowest visible point of the top (3.2 mm of a 4 mm tile with 0.6 mm colour depth), so scarce filaments are only used where they show. Each colour is set into the top face and most stand out in relief (raised stones, waves, drops, rocks, upright grass blades and flames, a standing door; sunk mortar, seams, cracks and pit); asphalt stays flat. No upper limit on the thickness (a tile as thick as it is wide is a cube). A special type, the connector, is a sleeve of the tile's shape that joins a tile rigidly on top of a part of the same shape (5.4 mm high, wall thickness and clearance editable, by default 1.2 and 0.1 mm): each goes in 2.4 mm and stops on a flat triangle in every inside corner (5 mm along each wall, 0.6 mm high, its open edge printed as a bridge; four flat stops in a round one). Bulges 0.5 mm deep on the inside of the walls, sloping at 45 degrees, clamp the tiles: in the lower half on two opposite edges, in the upper half on two others (a hexagon's third pair of edges has none, a triangle has one in both halves on every edge, a circle four a quarter turn apart). Old links to the earlier connector with a ledge open this one. Printed pattern up without supports. The 3MF puts every colour on its own filament slot; with a Bambu Lab printer chosen it is also a Bambu Studio project for it, which opens with the filament colours. Two more pages: `stored-tiles.html` lists the tiles kept in the server's disk cache (thumbnail, parameters, colours, the version (git commit) that made it, the date, download links, open in the generator; sortable by column), also those made by older versions, whose files are served as they were made, until a newer version of the same tile (all settings the same) replaces them and they are deleted; while the server is idle (no request for a minute) it makes every tile type as a 40 mm square with the default settings at the lowest CPU priority (`web_app/pregenerate.py`; `CAD_PREGENERATE=0` turns that off, `python -m web_app.pregenerate --list` shows what is missing), so that list is complete, and `colours.html` lists every filament colour the tiles use, with the types using it and tick boxes for the colours you have. Also usable headless: `python game_tiles_app/game_tile_model.py --type bricks --shape hexagon --count 4 --out tiles.step`
- **Sandbox App** – Minimal demo window used to test standalone/embedded launch behavior
- **Main Menu** – Launches any app as its own process from a central hub
- **3D Viewer** – Models are shown in the [OCP CAD Viewer](https://github.com/bernhard-42/vscode-ocp-cad-viewer) VS Code extension
- **Export Options** – Save models as STEP files, or open directly in BambuStudio/PrusaSlicer. The web app offers 3MF (for slicing: fast, small, two-colour models as coloured parts of one object) as the main download, and STEP (exact geometry, for CAD) next to it. It caches built models and their files in memory, and also keeps the files on disk (`~/.cache/cad-generators`, or `$CAD_CACHE_DIR`), so a model asked for before is served at once after a restart and shared by the worker processes; the files are tied to a fingerprint of the model code, so a code change never serves stale files, and the least recently used ones are deleted beyond `$CAD_DISK_CACHE_MB` (default 20000; `CAD_DISK_CACHE=0` turns the disk cache off). It builds the default model of every generator when it starts, in one separate process at the lowest CPU priority so the web workers stay responsive (set `CAD_WARM_CACHE=0` to skip that). The web pages load their starting values from the server (`api/<generator>/defaults`), which takes them from the model's defaults (e.g. `OrificeParams` in `orifice_app/orifice_model.py`; for the ring and powerbank holder, `DEFAULT` in their `web_app/generators/` module): change a default there and the page, the warmed cache, the desktop app and the command line all follow.
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
