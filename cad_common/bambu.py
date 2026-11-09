"""Bambu Studio's own 3MF additions, so a multi-colour model opens with its colours.

Bambu Studio (and OrcaSlicer) ignore the colours of the 3MF core spec (basematerials). They
read two extra files instead:

  Metadata/model_settings.config   the filament slot ("extruder") of every part. Read even from
                                    3MFs written by other programs, also when only the geometry
                                    is loaded, so the parts land on slots 1, 2, 3, ... in the
                                    order of their colours.
  Metadata/project_settings.config  the project's settings, among them the colour of every
                                    filament slot. Read only from a file whose Application
                                    metadata says Bambu Studio wrote it, opened as a project.

A project file names Bambu Studio's system presets for the chosen printer (printer with a
0.4 mm nozzle, its 0.20mm Standard process, Bambu PLA Basic) and the filament colours; Bambu
Studio fills every other setting from those presets, so they stay up to date. The preset names
and plate sizes are the ones that labels.vi-kan.net (MIT, Vegar Vikan) tested with Bambu Studio
2.8.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from xml.sax.saxutils import quoteattr

# The version of the Bambu Studio that the file says wrote it (the Application metadata).
BAMBU_APPLICATION = "BambuStudio-02.08.02.61"


@dataclass(frozen=True)
class BambuPrinter:
    name: str  # as Bambu Lab sells it, e.g. "X1 Carbon"
    code: str  # the preset suffix, e.g. "X1C" in "0.20mm Standard @BBL X1C"
    plate: tuple[float, float]  # width and depth of the print area, mm
    process_code: str | None = None  # when the process preset uses another printer's code
    filament_code: str | None = None  # when the filament preset has its own suffix
    nozzles: int = 1

    @property
    def model(self) -> str:
        return f"Bambu Lab {self.name}"

    @property
    def printer_preset(self) -> str:
        return f"Bambu Lab {self.name} 0.4 nozzle"

    @property
    def process_preset(self) -> str:
        return f"0.20mm Standard @BBL {self.process_code or self.code}"

    @property
    def filament_preset(self) -> str:
        return f"Bambu PLA Basic @BBL {self.filament_code or self.code}"


# By id, as the web pages and the cache key use it.
PRINTERS: dict[str, BambuPrinter] = {
    "a1mini": BambuPrinter("A1 mini", "A1M", (180, 180)),
    "a1": BambuPrinter("A1", "A1", (256, 256)),
    "a2l": BambuPrinter("A2L", "A2L", (330, 320), filament_code="A2L 0.4 nozzle"),
    "p1p": BambuPrinter("P1P", "P1P", (256, 256)),
    "p1s": BambuPrinter("P1S", "P1S", (256, 256), process_code="X1C", filament_code="P1S 0.4 nozzle"),
    "p2s": BambuPrinter("P2S", "P2S", (256, 256)),
    "x1c": BambuPrinter("X1 Carbon", "X1C", (256, 256)),
    "x1e": BambuPrinter("X1E", "X1C", (256, 256)),
    "x2d": BambuPrinter("X2D", "X2D", (256, 256), filament_code="X2D 0.4 nozzle", nozzles=2),
    "h2s": BambuPrinter("H2S", "H2S", (340, 320)),
    "h2c": BambuPrinter("H2C", "H2C", (330, 320), nozzles=2),
    "h2d": BambuPrinter("H2D", "H2D", (350, 320), nozzles=2),
    "h2dp": BambuPrinter("H2D Pro", "H2DP", (350, 320), nozzles=2),
}


def printer(printer_id: str | None) -> BambuPrinter | None:
    """The printer with this id; None for none ("" or None). Raises ValueError for an unknown id."""
    if not printer_id:
        return None
    if printer_id not in PRINTERS:
        raise ValueError(f"Unknown Bambu Lab printer '{printer_id}'.")
    return PRINTERS[printer_id]


def filament_slots(colours: list[str]) -> tuple[list[int], list[str]]:
    """Filament slot (1-based) of each part, given the parts' colours ("#RRGGBB"): the first
    colour gets slot 1 and every further distinct colour the next slot, so parts of one colour
    share a slot. Also returns the colour of each slot."""
    slot_colours: list[str] = []
    slots = []
    for c in colours:
        c = c.upper()
        if c not in slot_colours:
            slot_colours.append(c)
        slots.append(slot_colours.index(c) + 1)
    return slots, slot_colours


def model_settings(objects: list[tuple[int, str, list[tuple[int, str, int]]]], plate: bool) -> str:
    """Metadata/model_settings.config. objects: (assembly object id, name, parts), parts:
    (component object id, name, filament slot). With plate=True all objects go on plate 1
    (for a project file)."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
    for assembly, name, parts in objects:
        out.append(f' <object id="{assembly}">')
        out.append(f'  <metadata key="name" value={quoteattr(name)}/>')
        out.append('  <metadata key="extruder" value="1"/>')
        for part_id, part_name, slot in parts:
            out.append(f'  <part id="{part_id}" subtype="normal_part">')
            out.append(f'   <metadata key="name" value={quoteattr(part_name)}/>')
            out.append(f'   <metadata key="extruder" value="{slot}"/>')
            out.append("  </part>")
        out.append(" </object>")
    if plate:
        out += [" <plate>", '  <metadata key="plater_id" value="1"/>', '  <metadata key="plater_name" value=""/>',
                '  <metadata key="locked" value="false"/>']
        for assembly, _, _ in objects:
            out += ["  <model_instance>", f'   <metadata key="object_id" value="{assembly}"/>',
                    '   <metadata key="instance_id" value="0"/>', "  </model_instance>"]
        out.append(" </plate>")
    out.append("</config>")
    return "\n".join(out)


def project_settings(p: BambuPrinter, slot_colours: list[str]) -> str:
    """Metadata/project_settings.config (JSON): the printer's system presets and the colour of
    every filament slot."""
    settings = {
        "name": "project_settings",
        "from": "project",
        "version": BAMBU_APPLICATION.removeprefix("BambuStudio-"),
        "printer_technology": "FFF",
        "printer_model": p.model,
        "printer_settings_id": p.printer_preset,
        "printer_variant": "0.4",
        "print_settings_id": p.process_preset,
        "print_compatible_printers": [p.printer_preset],
        "filament_settings_id": [p.filament_preset] * len(slot_colours),
        "filament_colour": slot_colours,
        "filament_type": ["PLA"] * len(slot_colours),
    }
    if p.nozzles == 1:  # two-nozzle printers list every nozzle setting per nozzle: leave those to the presets
        settings["nozzle_diameter"] = ["0.4"]
    return json.dumps(settings, indent=4)
