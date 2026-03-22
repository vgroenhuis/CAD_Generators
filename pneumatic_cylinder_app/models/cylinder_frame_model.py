"""
Create cylinder frame and cap
TODO TODO
"""


from build123d import * # pyright: ignore
from numpy import angle, isinf
from ocp_vscode import show, show_object
import math

def create_cylinder(diameter: float, height: float) -> Part:
    """Creates a simple cylinder part."""
    sketch = Plane.XY * Circle(diameter / 2)
    cylinder = extrude(sketch, amount=height)
    return cylinder

# creates solid curved tube from the origin up, bent in the XZ plane, towards positive X
def create_curved_tube(radius, length, section_dia) -> Part:
    # Create a path for the sweep: an arc in the XZ plane centered at the origin.
    if isinf(radius):
        path = Line((0, 0, 0), (0, 0, length))
    else:
        angle_rad = length / radius
        path = Plane.XZ * CenterArc((radius, 0, 0), radius, 180, -math.degrees(angle_rad))
    show_object(path, name="sweep_path", options={"color": (1.0, 0.5, 0.0), "alpha": 0.5})
    sketch = Plane.XY * Circle(section_dia / 2)
    tube = sweep(sketch, path=path)
    return tube




###### Test functions

def main() -> None:
    # tube = create_curved_tube(radius=math.inf, length=20, section_dia=10)
    tube = create_curved_tube(radius=50, length=20, section_dia=10)
    show_object(tube, options={"color": (0.25, 0.77, 1.0)})

if __name__ == "__main__":
    main()