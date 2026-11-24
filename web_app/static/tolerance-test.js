import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { downloadWithProgress, fetchWithProgress } from "./progress.js";
import { loadDefaults } from "./defaults.js";
import { showViewerError } from "./error-banner.js";

const API = "api/tolerance-test";
const NUMBER_FIELDS = ["start", "step", "count", "per_row", "thickness", "height", "gap", "font_size", "label_depth"];
const inputs = Object.fromEntries(NUMBER_FIELDS.map((id) => [id, document.getElementById(id)]));
const kindInput = document.getElementById("kind");
const shapeInput = document.getElementById("shape");
const generateBtn = document.getElementById("generate-btn");
const downloadBtn = document.getElementById("download-btn");
const downloadStepBtn = document.getElementById("download-step-btn");
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

const SIZE_NAMES = { round: "diameter", hexagon: "across flats", square: "side" };

// Labels and hints follow the kind and shape.
function updateForm() {
	const name = SIZE_NAMES[shapeInput.value];
	document.getElementById("start_label").textContent = shapeInput.value === "round" ? "First diameter (mm)" : `First size, ${name} (mm)`;
	document.getElementById("size_hint").textContent = `Each next ${kindInput.value === "holes" ? "hole" : "peg"} is the step larger (a negative step: smaller).` +
		(shapeInput.value === "hexagon" ? " The size is across the flats." : "");
	inputs.height.disabled = kindInput.value !== "pegs";
}

function readParams() {
	const params = { kind: kindInput.value, shape: shapeInput.value };
	for (const id of NUMBER_FIELDS) {
		if (inputs[id].disabled) continue; // the peg height, for holes
		const value = parseNumber(inputs[id].value, id === "step");
		if (!Number.isFinite(value)) {
			const label = document.querySelector(`label[for="${id}"]`).textContent;
			throw new Error(`${label} must be a number${id === "step" ? "" : " of 0 or more"} (use a dot as decimal separator).`);
		}
		params[id] = value;
	}
	if (!("height" in params)) params.height = 10;
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
		currentModel.traverse((child) => {
			if (child.isMesh) {
				const color = child.material && child.material.color ? child.material.color : new THREE.Color(0xdddddd);
				child.material = new THREE.MeshStandardMaterial({ color, metalness: 0.0, roughness: 0.6 });
			}
		});
		scene.add(currentModel);
		if (!cameraFitted) {
			fitCameraToObject(currentModel);
			cameraFitted = true;
		}
		placeholderEl.style.display = "none";
		downloadBtn.disabled = false;
		downloadStepBtn.disabled = false;
		setStatus("Generated, in print orientation. Drag to rotate.");
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
downloadBtn.addEventListener("click", () => onDownload("3mf"));
downloadStepBtn.addEventListener("click", () => onDownload("step"));
[kindInput, shapeInput].forEach((el) => el.addEventListener("change", () => {
	updateForm();
	onGenerate();
}));
Object.values(inputs).forEach((el) => {
	el.addEventListener("input", () => {
		downloadBtn.disabled = true;
		downloadStepBtn.disabled = true;
	});
	el.addEventListener("keydown", (e) => {
		if (e.key === "Enter") onGenerate();
	});
});

// Start from the server's defaults (the model's), then show the default test piece.
loadDefaults(API)
	.then(() => {
		updateForm();
		onGenerate();
	})
	.catch((exc) => setStatus(exc.message, true));
