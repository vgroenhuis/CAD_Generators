"""Create the pneumatic cylinder app icon file.

Running this module directly creates cylinder_icon.ico in the same folder.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ICON_FILE = Path(__file__).parent / "cylinder_icon.ico"


def create_cylinder_icon(output_path: Path = ICON_FILE) -> Path:
	"""Create and save the cylinder icon, returning the output path."""
	size = 1024
	img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
	draw = ImageDraw.Draw(img)

	# Draw a simple pneumatic cylinder symbol: capsule body + piston rod.
	body_left = int(size * 0.18)
	body_right = int(size * 0.70)
	body_top = int(size * 0.34)
	body_bottom = int(size * 0.66)
	cap_h = int(size * 0.18)
	highlight_inset = max(1, int(size * 0.04))
	highlight_h = max(1, int(size * 0.06))
	rod_len = int(size * 0.20)
	rod_h = int(size * 0.08)
	rod_top = int((body_top + body_bottom) / 2 - rod_h / 2)
	rod_bottom = rod_top + rod_h
	rod_left = body_right
	rod_right = body_right + rod_len
	rod_tip_d = max(2, int(size * 0.10))

	# Main body.
	draw.rectangle([body_left, body_top, body_right, body_bottom], fill=(90, 140, 210, 255))
	# Rounded end caps.
	draw.ellipse([body_left, body_top - cap_h // 2, body_right, body_top + cap_h // 2], fill=(90, 140, 210, 255))
	draw.ellipse([body_left, body_bottom - cap_h // 2, body_right, body_bottom + cap_h // 2], fill=(90, 140, 210, 255))
	# Inner highlight for visual depth.
	draw.rectangle(
		[
			body_left + highlight_inset,
			body_top + highlight_inset,
			body_right - highlight_inset,
			body_top + highlight_inset + highlight_h,
		],
		fill=(150, 190, 235, 255),
	)
	# Piston rod.
	draw.rectangle([rod_left, rod_top, rod_right, rod_bottom], fill=(220, 230, 240, 255))
	draw.ellipse(
		[
			rod_right - rod_tip_d // 2,
			rod_top - (rod_tip_d - rod_h) // 2,
			rod_right + rod_tip_d // 2,
			rod_bottom + (rod_tip_d - rod_h) // 2,
		],
		fill=(220, 230, 240, 255),
	)

	img.save(output_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
	return output_path


def ensure_icon_file(output_path: Path = ICON_FILE) -> Path:
	"""Create the icon only when it does not exist yet."""
	if not output_path.exists():
		return create_cylinder_icon(output_path)
	return output_path


if __name__ == "__main__":
	created_path = create_cylinder_icon()
	print(f"Created icon: {created_path}")
