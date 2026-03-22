"""
    Geometry construction helpers for ring creation.
    It can also be run standalone, with input from a JOSN or YAML file, or hard-coded parameters.
    The ring is then rendered in the OCP_vscode viewer (if available).
"""

from build123d import BuildPart, Cylinder, Mode, Part
from ocp_vscode import show

def build_ring(od: float, inner_d: float, thickness: float) -> Part:
    """Build and return a ring part from outer/inner diameter and thickness."""
    with BuildPart() as ring:
        Cylinder(radius=od / 2.0, height=thickness)
        Cylinder(radius=inner_d / 2.0, height=thickness, mode=Mode.SUBTRACT)
    part = ring.part
    if part is None:
        raise RuntimeError("Ring construction failed: no part was generated")
    return part

def build_ring_struct(params) -> Part:
    """Build and return a ring part from a params dict."""
    return build_ring(params["od"], params["id"], params["thickness"])





######## Test functions when running this file directly. These can be run by uncommenting the desired test in main().

def test_manual_params() -> None:
    # Example usage of build_ring function
    params = {"od": 100, "id": 60, "thickness": 20}
    ring_part = build_ring_struct(params)
    show(ring_part)


def test_params_from_yaml() -> None:
    import yaml
    from pathlib import Path

    # Load parameters from YAML file
    config_file = Path(__file__).parent / "predefined_rings" / "ring1.yaml"
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")
    
    with open(config_file, "r") as f:
        params = yaml.safe_load(f)
    
    # Build ring from loaded parameters
    ring_part = build_ring_struct(params)
    show(ring_part)


def test_params_from_json() -> None:
    import json
    from pathlib import Path

    # Load parameters from JSON file
    config_file = Path(__file__).parent / "ring_params.json"
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")
    
    with open(config_file, "r") as f:
        params = json.load(f)
    
    # Build ring from loaded parameters
    ring_part = build_ring_struct(params)
    show(ring_part)

def main() -> None:
    # test_manual_params()
    # test_params_from_json()
    test_params_from_yaml()
    pass

if __name__ == "__main__":
	main()
