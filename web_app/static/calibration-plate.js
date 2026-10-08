import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const NUMBER_FIELDS = ["width", "length", "thickness", "depth", "margin", "square_size", "tag_size", "tag_spacing"];
const inputs = Object.fromEntries(NUMBER_FIELDS.map((id) => [id, document.getElementById(id)]));
const firstTagIdInput = document.getElementById("first_tag_id");
const borderBitsInput = document.getElementById("border_bits");
const cornerSquaresInput = document.getElementById("corner_squares");
const generateBtn = document.getElementById("generate-btn");
const downloadBtn = document.getElementById("download-btn");
const downloadStepBtn = document.getElementById("download-step-btn");
const aprilgridYamlBtn = document.getElementById("aprilgrid-yaml-btn");
const checkerYamlBtn = document.getElementById("checker-yaml-btn");
const layoutInfoEl = document.getElementById("layout-info");
const patternWarningEl = document.getElementById("pattern-warning");
const statusEl = document.getElementById("status");
const placeholderEl = document.getElementById("viewer-placeholder");
const canvas = document.getElementById("viewer-canvas");
const viewerContainer = document.querySelector(".viewer");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1d21);

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
camera.position.set(300, 300, 300);

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const keyLight = new THREE.DirectionalLight(0xffffff, 0.8);
keyLight.position.set(1, 2, 1.5);
scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
fillLight.position.set(-1.5, -1, -1);
scene.add(fillLight);

let currentModel = null;
let currentLayout = null;

function resizeRenderer() {
	const width = viewerContainer.clientWidth;
	const height = viewerContainer.clientHeight;
	renderer.setSize(width, height, false);
	camera.aspect = width / (height || 1);
	camera.updateProjectionMatrix();
}
window.addEventListener("resize", resizeRenderer);
resizeRenderer();

function animate() {
	requestAnimationFrame(animate);
	controls.update();
	renderer.render(scene, camera);
}
animate();

function setStatus(text, isError) {
	statusEl.textContent = text;
	statusEl.classList.toggle("error", Boolean(isError));
}

async function friendlyErrorMessage(response) {
	try {
		const body = await response.json();
		if (typeof body.detail === "string") return body.detail;
		if (Array.isArray(body.detail)) {
			return body.detail.map((e) => `${(e.loc || []).slice(-1)[0] || ""}: ${e.msg || JSON.stringify(e)}`).join("; ");
		}
	} catch (e) {
		// fall through
	}
	return `Request failed (${response.status})`;
}

// Plain dot-decimal numbers only, independent of the browser locale (the
// fields are type="text", so a comma is never taken as a decimal separator).
function parseNumber(text) {
	const trimmed = text.trim();
	return /^\d*\.?\d+$|^\d+\.$/.test(trimmed) ? parseFloat(trimmed) : NaN;
}

function readParams() {
	const params = {};
	for (const id of NUMBER_FIELDS) {
		const value = parseNumber(inputs[id].value);
		if (!Number.isFinite(value)) {
			const label = document.querySelector(`label[for="${id}"]`).textContent;
			throw new Error(`${label} must be a number (use a dot as decimal separator).`);
		}
		params[id] = value;
	}
	if (!/^\d+$/.test(firstTagIdInput.value.trim())) throw new Error("First tag ID must be a whole number.");
	params.first_tag_id = Number(firstTagIdInput.value.trim());
	params.border_bits = Number(borderBitsInput.value);
	params.corner_squares = cornerSquaresInput.checked;
	if (params.depth >= params.thickness / 2) throw new Error("Black depth must be smaller than half the plate thickness.");
	return params;
}

function buildQuery(params) {
	return new URLSearchParams(Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])));
}

function fitCameraToObject(object) {
	const box = new THREE.Box3().setFromObject(object);
	const size = box.getSize(new THREE.Vector3());
	const center = box.getCenter(new THREE.Vector3());
	const maxDim = Math.max(size.x, size.y, size.z) || 1;
	const distance = maxDim * 1.1;

	controls.target.copy(center);
	camera.position.set(center.x + distance * 0.6, center.y + distance, center.z + distance * 0.8);
	camera.near = maxDim / 100;
	camera.far = maxDim * 100;
	camera.updateProjectionMatrix();
	controls.update();
}

// Same rule and wording as pattern_warning() in calibration_plate_model.py. Checked here so the
// warning appears the moment a control changes, without waiting behind a running build.
function patternWarning(borderBits, cornerSquares) {
	if (borderBits === 1 && cornerSquares) {
		return "Corner squares are a Kalibr AprilGrid feature, but Kalibr's detector expects a 2-bit tag " +
			"border and will not find 1-bit tags. Use a 2-bit border for Kalibr, or turn the corner " +
			"squares off for a standard AprilTag grid.";
	}
	if (borderBits === 2 && !cornerSquares) {
		return "A 2-bit tag border is the Kalibr AprilGrid format, but Kalibr's AprilGrid also has corner " +
			"squares (they make the tag corners symmetric for accurate sub-pixel refinement). Turn the " +
			"corner squares on for Kalibr, or use a 1-bit border for a standard AprilTag grid.";
	}
	return null;
}

function updatePatternWarning() {
	const text = patternWarning(Number(borderBitsInput.value), cornerSquaresInput.checked);
	patternWarningEl.textContent = text ? `Warning: ${text}` : "";
	patternWarningEl.hidden = !text;
}

function showLayout(layout) {
	currentLayout = layout;
	layoutInfoEl.textContent =
		`Top: ${layout.checker_cols} x ${layout.checker_rows} squares ` +
		`(${layout.checker_cols - 1} x ${layout.checker_rows - 1} inner corners)\n` +
		`Bottom: ${layout.tag_cols} x ${layout.tag_rows} tags, ids ${layout.first_tag_id}-${layout.last_tag_id}`;
	aprilgridYamlBtn.disabled = false;
	checkerYamlBtn.disabled = false;
}

function clearLayout() {
	currentLayout = null;
	layoutInfoEl.textContent = "";
	aprilgridYamlBtn.disabled = true;
	checkerYamlBtn.disabled = true;
}

const gltfLoader = new GLTFLoader();

async function onGenerate() {
	let params;
	try {
		params = readParams();
	} catch (exc) {
		setStatus(exc.message, true);
		return;
	}

	generateBtn.disabled = true;
	downloadBtn.disabled = true;
	downloadStepBtn.disabled = true;
	const query = buildQuery(params);

	try {
		// The layout is cheap and validates the parameters before the slow build.
		const layoutResponse = await fetch(`api/calibration-plate/layout?${query}`);
		if (!layoutResponse.ok) {
			clearLayout();
			setStatus(await friendlyErrorMessage(layoutResponse), true);
			return;
		}
		showLayout(await layoutResponse.json());

		setStatus("Generating... (a full-size plate takes about 20-30 seconds)");
		const response = await fetch(`api/calibration-plate/preview.glb?${query}`);
		if (!response.ok) {
			setStatus(await friendlyErrorMessage(response), true);
			return;
		}
		const buffer = await response.arrayBuffer();
		const gltf = await new Promise((resolve, reject) => {
			gltfLoader.parse(buffer, "", resolve, reject);
		});

		if (currentModel) {
			scene.remove(currentModel);
		}
		currentModel = gltf.scene;
		currentModel.traverse((child) => {
			if (child.isMesh) {
				// Each body (white, black) carries its colour in the glTF material.
				const color = child.material && child.material.color ? child.material.color : new THREE.Color(0xeeeeee);
				child.material = new THREE.MeshStandardMaterial({ color, metalness: 0.0, roughness: 0.6 });
			}
		});
		scene.add(currentModel);
		fitCameraToObject(currentModel);
		placeholderEl.style.display = "none";
		downloadBtn.disabled = false;
		downloadStepBtn.disabled = false;
		setStatus(`Generated plate ${params.width} x ${params.length} x ${params.thickness} mm. Drag to rotate and see the AprilGrid underneath.`);
	} catch (exc) {
		setStatus(`Failed to load preview: ${exc.message || exc}`, true);
	} finally {
		generateBtn.disabled = false;
	}
}

// format: "3mf" (for slicing) or "step" (for CAD)
function onDownload(format) {
	let params;
	try {
		params = readParams();
	} catch (exc) {
		setStatus(exc.message, true);
		return;
	}
	window.location.href = `api/calibration-plate/export.${format}?${buildQuery(params)}`;
}

function downloadText(filename, text) {
	const url = URL.createObjectURL(new Blob([text], { type: "text/yaml" }));
	const a = document.createElement("a");
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	a.remove();
	URL.revokeObjectURL(url);
}

generateBtn.addEventListener("click", onGenerate);
downloadBtn.addEventListener("click", () => onDownload("3mf"));
downloadStepBtn.addEventListener("click", () => onDownload("step"));
aprilgridYamlBtn.addEventListener("click", () => currentLayout && downloadText("aprilgrid.yaml", currentLayout.aprilgrid_yaml));
checkerYamlBtn.addEventListener("click", () => currentLayout && downloadText("checkerboard.yaml", currentLayout.checkerboard_yaml));
// Any parameter change invalidates the shown model, layout and download.
[...Object.values(inputs), firstTagIdInput].forEach((el) => {
	el.addEventListener("input", () => {
		downloadBtn.disabled = true;
		downloadStepBtn.disabled = true;
		clearLayout();
	});
	el.addEventListener("keydown", (e) => {
		if (e.key === "Enter") onGenerate();
	});
});
[borderBitsInput, cornerSquaresInput].forEach((el) =>
	el.addEventListener("change", () => {
		updatePatternWarning();
		onGenerate();
	}),
);
updatePatternWarning();

onGenerate();
