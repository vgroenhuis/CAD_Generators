"""
Geometry construction helpers for ring creation.
"""

from build123d import *
from ocp_vscode import show, show_object

from pneumatic_cylinder_app.models.x_ring_model import create_x_ring
#from x_ring_model import create_x_ring


def build_cylinder(od: float, inner_d: float, thickness: float):
    # Build and return a cylinder
    sketch = Plane.XY * Circle(od / 2.0) - Plane.XY * Circle(inner_d / 2.0)
    cylinder = extrude(sketch, amount=thickness)
    x_ring = Pos(Z=20) * create_x_ring(inner_dia=inner_d, thickness=thickness)
    return cylinder + x_ring


def build_cylinder_struct(params):
    # Build and return a cylinder from a params dict
    return build_cylinder(params["od"], params["id"], params["thickness"])




######## Test functions when running this file directly. These can be run by uncommenting the desired test in main().

def test_manual_params() -> None:
    # Example usage of build_cylinder function
    params = {"od": 100, "id": 60, "thickness": 20}
    cylinder_part = build_cylinder_struct(params)
    show(cylinder_part)


def test_params_from_yaml() -> None:
    import yaml
    from pathlib import Path

    # Load parameters from YAML file
    config_file = Path(__file__).parent.parent / "predefined_cylinders" / "cylinder1.yaml"
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")
    
    with open(config_file, "r") as f:
        params = yaml.safe_load(f)
    
    # Build cylinder from loaded parameters
    cylinder_part = build_cylinder_struct(params)
    show(cylinder_part)


def main() -> None:
    # test_manual_params()
    test_params_from_yaml()
    pass

if __name__ == "__main__":
	main()
