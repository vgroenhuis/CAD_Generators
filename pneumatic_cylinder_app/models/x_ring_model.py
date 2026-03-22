""" Geometry construction helpers for X-ring creation.
Running this file directly shows a test X-ring in the OCP_vscode viewer (if available).
"""


from build123d import * # pyright: ignore
from ocp_vscode import show, show_object

def create_x_ring(inner_dia, thickness):
    lobe_offset = thickness * 0.22
    lobe_radius = thickness * 0.28
    locs = [(lobe_offset, lobe_offset), (lobe_offset, -lobe_offset), (-lobe_offset, lobe_offset), (-lobe_offset, -lobe_offset)]
    lobes = [Pos(x,y) * Circle(radius=lobe_radius) for x, y in locs]
    core = Rectangle(width=lobe_offset * 2, height=lobe_offset * 2)
    x_ring_section = Plane.XZ * Pos(inner_dia/2+thickness/2,0) * sum(lobes, core)
    # For debugging purposes, the section drawing can be shown
    # show_object(x_ring_section, "X-ring section", options={"color": (1.0, 0.0, 0.0), "alpha": 0.9})
    x_ring = revolve(x_ring_section, axis=Axis.Z) # type: ignore
    return x_ring



########## Test functions

def main() -> None:
    ring1 = create_x_ring(inner_dia=10, thickness=2)
    show_object(ring1, name="X-ring", options={"color": (0.6, 0.7, 0.8), "alpha": 0.7})

if __name__ == "__main__":
	main()