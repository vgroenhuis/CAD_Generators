from build123d import BuildPart, Cylinder, export_step
try:
    from ocp_vscode import show
except ImportError:
    show = None


def main():
    # Parameters for the cylinder
    radius = 10.0  # mm
    height = 30.0  # mm

    # Generate cylinder using build123d BuildPart context
    with BuildPart() as cylinder_builder:
        Cylinder(radius=radius, height=height)

    cylinder = cylinder_builder.part

    # Export model to STEP file
    export_step(cylinder, "cylinder.step")
    print(f"Cylinder (radius={radius}mm, height={height}mm) created successfully!")

    # Display model if ocp_vscode viewer is available
    if show is not None:
        show(cylinder)


if __name__ == "__main__":
    main()
