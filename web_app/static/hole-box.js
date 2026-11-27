import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { downloadWithProgress, fetchWithProgress } from "./progress.js";
import { loadDefaults } from "./defaults.js";
import { showViewerError } from "./error-banner.js";

const API = "api/hole-box";
const NUMBER_FIELDS = ["width", "depth", "height", "wall", "corner_radius", "joint_length", "clearance", "holes", "hole_size", "hole_circle", "text_size", "text_depth"];
const inputs = Object.fromEntries(NUMBER_FIELDS.map((id) => [id, document.getElementById(id)]));
const shapeInput = document.getElementById("shape");
const closureInput = document.getElementById("closure");
const holeShapeInput = document.getElementById("hole_shape");
const textInput = document.getElementById("text");
const presetSelect = document.getElementById("preset");
const generateBtn = document.getElementById("generate-btn");
const downloadBtn = document.getElementById("download-btn");
const downloadStepBtn = document.getElementById("download-step-btn");
const assembledInput = document.getElementById("assembled_view");
const infoEl = document.getElementById("info");
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
// The camera is fitted to the first model only; re-generating keeps it, so changes are easy to compare.
let cameraFitted = false;

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
	showViewerError(isError ? text : "");
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

// Plain dot-decimal numbers only, independent of the browser locale (the fields are
// type="text", so a comma is never taken as a decimal separator); a minus sign only where allowed.
function parseNumber(text, negative = false) {
	const trimmed = text.trim();
	const re = negative ? /^-?(\d*\.?\d+|\d+\.)$/ : /^(\d*\.?\d+|\d+\.)$/;
	return re.test(trimmed) ? parseFloat(trimmed) : NaN;
}

const WIDTH_LABELS = { round: "Diameter (mm)", square: "Side (mm)", rectangle: "Width (mm)", hexagon: "Across flats (mm)" };
const HOLE_LABELS = { round: "Diameter (mm)", square: "Side (mm)", hexagon: "Across flats (mm)" };
const CLOSURE_HINTS = {
	snap: "A ring under the lid fits into the base; a bead around it clicks into a groove in the base's wall. Lever the lid off at the notch in the rim. The length is the ring's depth; the clearance the gap on each side.",
	screws: "M3 countersunk self-tapping screws through the lid into posts in the base's corners (3 in a round or hexagonal box, 4 otherwise); the summary gives their longest length.",
	thread: "The base has a threaded neck, the lid an internal thread (rounded, pitch 3 mm): it screws on. The clearance is the gap on each side between the threads.",
};

// Labels, hints and which fields apply follow the shapes and the closure.
function updateForm() {
	const shape = shapeInput.value;
	document.getElementById("width_label").textContent = WIDTH_LABELS[shape];
	document.getElementById("hole_size_label").textContent = HOLE_LABELS[holeShapeInput.value];
	inputs.depth.disabled = shape !== "rectangle";
	inputs.corner_radius.disabled = shape === "round";
	const thread = closureInput.querySelector('option[value="thread"]');
	thread.disabled = shape !== "round";
	if (thread.disabled && closureInput.value === "thread") closureInput.value = "snap";
	const closure = closureInput.value;
	document.getElementById("joint_label").textContent = closure === "thread" ? "Thread length (mm)" : "Plug depth (mm)";
	inputs.joint_length.disabled = inputs.clearance.disabled = closure === "screws";
	document.getElementById("closure_hint").textContent = CLOSURE_HINTS[closure];
	const holes = parseNumber(inputs.holes.value);
	holeShapeInput.disabled = inputs.hole_size.disabled = inputs.hole_circle.disabled = holes === 0;
	inputs.text_size.disabled = inputs.text_depth.disabled = !textInput.value.trim();
}

function readParams() {
	const params = { shape: shapeInput.value, closure: closureInput.value, hole_shape: holeShapeInput.value, text: textInput.value.trim() };
	for (const id of NUMBER_FIELDS) {
		const value = parseNumber(inputs[id].value);
		if (!Number.isFinite(value)) {
			if (inputs[id].disabled) {  // doesn't apply: the server takes its default
				params[id] = defaults[id];
				continue;
			}
			const label = document.querySelector(`label[for="${id}"]`).textContent;
			throw new Error(`${label} must be a number of 0 or more (use a dot as decimal separator).`);
		}
		params[id] = value;
	}
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
	const distance = maxDim * 1.6;
	controls.target.copy(center);
	camera.position.set(center.x + distance * 0.5, center.y + distance * 0.9, center.z + distance * 0.8);
	camera.near = maxDim / 100;
	camera.far = maxDim * 100;
	camera.updateProjectionMatrix();
	controls.update();
}

const gltfLoader = new GLTFLoader();

// Assembled view: the lid turned back over (180 degrees about X, around half the box's height)
// and moved onto the base, as it was modelled in its closed place before being laid out to print.
let boxSize = { outer_x: 50, height: 40 };  // mm, from the summary
let lidHome = null;  // the lid node's own matrix in print orientation

function applyAssembled() {
	const base = currentModel?.getObjectByName("base");
	const lid = currentModel?.getObjectByName("lid");
	if (!base || !lid) return;
	if (!lidHome) lidHome = lid.matrix.clone();
	lidHome.decompose(lid.position, lid.quaternion, lid.scale);
	currentModel.updateMatrixWorld(true);
	if (assembledInput.checked) {
		// glTF: y up, z = -(CAD y); the scale from the base's width in the scene against its width in mm.
		const bb = new THREE.Box3().setFromObject(base);
		const lb = new THREE.Box3().setFromObject(lid);
		const s = (bb.max.x - bb.min.x) / boxSize.outer_x;
		const pivot = new THREE.Vector3(0, bb.min.y + boxSize.height * s / 2, (bb.min.z + bb.max.z) / 2);
		const dx = (bb.min.x + bb.max.x) / 2 - (lb.min.x + lb.max.x) / 2;
		const move = new THREE.Matrix4().makeTranslation(dx + pivot.x, pivot.y, pivot.z)
			.multiply(new THREE.Matrix4().makeRotationX(Math.PI))
			.multiply(new THREE.Matrix4().makeTranslation(-pivot.x, -pivot.y, -pivot.z));
		const world = move.multiply(lid.matrixWorld);
		const local = lid.parent.matrixWorld.clone().invert().multiply(world);
		local.decompose(lid.position, lid.quaternion, lid.scale);
		currentModel.updateMatrixWorld(true);
	}
}

function generatedStatus() {
	setStatus(`Generated${assembledInput.checked ? ", shown assembled (saved in print orientation)" : ", in print orientation"}. Drag to rotate.`);
}

canvas.title = "Drag to rotate, scroll to zoom, double-click to fit the model in view.";
canvas.addEventListener("dblclick", () => currentModel && fitCameraToObject(currentModel));

let generation = 0;

async function onGenerate() {
	let params;
	try {
		params = readParams();
	} catch (exc) {
		setStatus(exc.message, true);
		return;
	}
	const mine = ++generation;  // a newer request wins
	generateBtn.disabled = true;
	downloadBtn.disabled = true;
	downloadStepBtn.disabled = true;
	setStatus("Starting...");
	const query = buildQuery(params);
	try {
		// The summary validates the parameters.
		const infoResponse = await fetchWithProgress(`${API}/info?${query}`, (t) => mine === generation && setStatus(t));
		if (mine !== generation) return;
		if (!infoResponse.ok) {
			infoEl.textContent = "";
			setStatus(await friendlyErrorMessage(infoResponse), true);
			return;
		}
		const info = await infoResponse.json();
		infoEl.textContent = info.summary;
		boxSize = { outer_x: info.outer_x, height: info.height };

		const response = await fetchWithProgress(`${API}/preview.glb?${query}`, (t) => mine === generation && setStatus(t));
		if (mine !== generation) return;
		if (!response.ok) {
			setStatus(await friendlyErrorMessage(response), true);
			return;
		}
		const buffer = await response.arrayBuffer();
		const gltf = await new Promise((resolve, reject) => gltfLoader.parse(buffer, "", resolve, reject));
		if (mine !== generation) return;
		if (currentModel) scene.remove(currentModel);
		currentModel = gltf.scene;
		lidHome = null;
		currentModel.traverse((child) => {
			if (child.isMesh) {
				const color = child.material && child.material.color ? child.material.color : new THREE.Color(0xdddddd);
				child.material = new THREE.MeshStandardMaterial({ color, metalness: 0.0, roughness: 0.6 });
			}
		});
		scene.add(currentModel);
		applyAssembled();
		if (!cameraFitted) {
			fitCameraToObject(currentModel);
			cameraFitted = true;
		}
		placeholderEl.style.display = "none";
		downloadBtn.disabled = false;
		downloadStepBtn.disabled = false;
		generatedStatus();
	} catch (exc) {
		if (mine === generation) setStatus(`Failed to load preview: ${exc.message || exc}`, true);
	} finally {
		if (mine === generation) generateBtn.disabled = false;
	}
}

// format: "3mf" or "step"
async function onDownload(format) {
	let params;
	try {
		params = readParams();
	} catch (exc) {
		setStatus(exc.message, true);
		return;
	}
	try {
		const response = await downloadWithProgress(`${API}/export.${format}?${buildQuery(params)}`, setStatus);
		setStatus(response.ok ? `Downloaded ${response.filename}.` : await friendlyErrorMessage(response), !response.ok);
	} catch (exc) {
		setStatus(`Download failed: ${exc.message || exc}`, true);
	}
}

generateBtn.addEventListener("click", onGenerate);
assembledInput.addEventListener("change", () => {
	applyAssembled();
	if (currentModel && !generateBtn.disabled) generatedStatus();
});
downloadBtn.addEventListener("click", () => onDownload("3mf"));
downloadStepBtn.addEventListener("click", () => onDownload("step"));
[shapeInput, closureInput, holeShapeInput].forEach((el) => el.addEventListener("change", () => {
	updateForm();
	presetSelect.value = matchingPreset();
	onGenerate();
}));
[...Object.values(inputs), textInput].forEach((el) => {
	el.addEventListener("input", () => {
		downloadBtn.disabled = true;
		downloadStepBtn.disabled = true;
		if (el === inputs.holes || el === textInput) updateForm();
		presetSelect.value = matchingPreset();
	});
	el.addEventListener("keydown", (e) => {
		if (e.key === "Enter") onGenerate();
	});
});

// Presets: picking one fills the fields; editing a field selects the matching preset, or "Custom".
const CUSTOM = "custom";
let presets = {};
let defaults = {};

function sameValue(id, value) {
	const el = document.getElementById(id);
	return typeof value === "number" ? parseNumber(el.value) === value : el.value === String(value);
}

function matchingPreset() {
	for (const [name, values] of Object.entries(presets)) {
		if (Object.entries(values).every(([id, value]) => !document.getElementById(id) || sameValue(id, value))) return name;
	}
	return CUSTOM;
}

function applyValues(values) {
	for (const [id, value] of Object.entries(values)) {
		const el = document.getElementById(id);
		if (el && el !== presetSelect) el.value = String(value);
	}
}

presetSelect.addEventListener("change", () => {
	if (presetSelect.value === CUSTOM) return;
	applyValues(presets[presetSelect.value]);
	updateForm();
	onGenerate();
});

// Start from the server's defaults (the model's), then show that box.
loadDefaults(API)
	.then((loaded) => {
		defaults = loaded;
		presets = loaded.presets || {};
		presetSelect.replaceChildren(...Object.keys(presets).map((name) => new Option(name, name)), new Option("Custom", CUSTOM));
		updateForm();
		presetSelect.value = matchingPreset();
		onGenerate();
	})
	.catch((exc) => setStatus(exc.message, true));
