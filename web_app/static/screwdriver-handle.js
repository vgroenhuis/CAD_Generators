import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { downloadWithProgress, fetchWithProgress } from "./progress.js";
import { loadDefaults } from "./defaults.js";
import { showViewerError } from "./error-banner.js";

const API = "api/screwdriver-handle";
const NUMBER_FIELDS = ["diameter", "length", "taper_length", "tip_diameter", "knurl_depth", "knurl_count", "socket_size", "socket_depth", "magnet_diameter",
	"magnet_height", "magnet_gap", "hole_size", "storage_gap", "thread_length", "thread_clearance",
	"cap_oversize"];
const INTEGER_FIELDS = ["knurl_count"];
const inputs = Object.fromEntries(NUMBER_FIELDS.map((id) => [id, document.getElementById(id)]));
const generateBtn = document.getElementById("generate-btn");
const downloadBtn = document.getElementById("download-btn");
const downloadStepBtn = document.getElementById("download-step-btn");
const infoEl = document.getElementById("info");
const knurlInput = document.getElementById("knurl");
const holesInput = document.getElementById("holes");
const cutInput = document.getElementById("cut_view");
const assembledInput = document.getElementById("assembled_view");
const bitsInput = document.getElementById("show_bits");
const defaultsBtn = document.getElementById("defaults-btn");
const presetSelect = document.getElementById("preset");
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

// Fields that don't matter for the current choices are greyed out.
function updateFields() {
	inputs.knurl_depth.disabled = inputs.knurl_count.disabled = !knurlInput.checked;
	inputs.hole_size.disabled = inputs.storage_gap.disabled = holesInput.value === "0";
}

function readParams() {
	const params = { knurl: knurlInput.checked, holes: Number(holesInput.value) };
	for (const id of NUMBER_FIELDS) {
		const value = parseNumber(inputs[id].value);
		if (!Number.isFinite(value) || (INTEGER_FIELDS.includes(id) && !Number.isInteger(value))) {
			if (inputs[id].disabled) continue; // not used: the server takes the default
			const label = document.querySelector(`label[for="${id}"]`).textContent;
			throw new Error(`${label} must be a${INTEGER_FIELDS.includes(id) ? " whole" : ""} number of 0 or more (use a dot as decimal separator).`);
		}
		params[id] = value;
	}
	return params;
}

function buildQuery(params) {
	return new URLSearchParams(Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])));
}

// Cut view: the half of each object nearest the viewer's start position is hidden. The inside
// faces that then show through the cut (back faces) are drawn in a flat colour, so the cut
// material looks like a solid section.
renderer.localClippingEnabled = true;
const SECTION_COLOUR = 0xf0c8a0;

// Assembled view: the cap moved under the handle, its flange against the handle's bottom and its
// plug screwed all the way in. The cap's thread starts at the same turn as the handle's (both
// from 1 mm below their mouth), so moving it straight down makes the threads mesh.
let capFlange = 3;  // mm, from the summary
let capHeight = 8.6;  // mm, flange and plug, from the summary
let capHome = null;
let lastQuery = null;  // the query of the model shown  // the cap node's own position in print orientation

function applyAssembled() {
	const handle = currentModel?.getObjectByName("handle");
	const cap = currentModel?.getObjectByName("cap");
	if (!handle || !cap) return;
	if (!capHome) capHome = cap.position.clone();
	cap.position.copy(capHome);
	currentModel.updateMatrixWorld(true);
	if (assembledInput.checked) {
		const hb = new THREE.Box3().setFromObject(handle);
		const cb = new THREE.Box3().setFromObject(cap);
		const hc = hb.getCenter(new THREE.Vector3());
		const cc = cb.getCenter(new THREE.Vector3());
		// glTF: y up, in metres (the cap's height in the scene against its height in mm gives the
		// scale). Centre the cap on the handle's axis; the flange's top at the handle's bottom.
		// (0.02 mm lower: the flange's top and the handle's bottom would share a plane and flicker.)
		const flange = (capFlange + 0.02) * (cb.max.y - cb.min.y) / capHeight;
		const delta = new THREE.Vector3(hc.x - cc.x, hb.min.y - (cb.min.y + flange), hc.z - cc.z);
		const target = cap.getWorldPosition(new THREE.Vector3()).add(delta);
		cap.position.copy(cap.parent.worldToLocal(target));
		currentModel.updateMatrixWorld(true);
	}
	applyCutView();
}

// Bits (for a look, not in the files): a separate glTF in the same coordinates as the model's,
// loaded when asked for. The storage hole's bit shows through the cut view.
let bitsModel = null;
let bitsQuery = null;  // the query the shown bits belong to

async function updateBits(query) {
	if (!bitsInput.checked || !query) {
		if (bitsModel) scene.remove(bitsModel);
		bitsModel = null;
		bitsQuery = null;
		return;
	}
	if (bitsModel && bitsQuery === query) return;
	try {
		const response = await fetch(`${API}/bits.glb?${query}`);
		if (!response.ok || !bitsInput.checked) return;
		const gltf = await new Promise(async (resolve, reject) => gltfLoader.parse(await response.arrayBuffer(), "", resolve, reject));
		if (!bitsInput.checked || query !== lastQuery) return;  // changed meanwhile
		if (bitsModel) scene.remove(bitsModel);
		bitsModel = gltf.scene;
		bitsModel.traverse((child) => {
			if (child.isMesh) child.material = new THREE.MeshStandardMaterial({ color: 0xbabcc2, metalness: 0.6, roughness: 0.35 });
		});
		bitsQuery = query;
		scene.add(bitsModel);
	} catch (exc) {
		setStatus(`Failed to load the bits: ${exc.message || exc}`, true);
	}
}

function applyCutView() {
	if (!currentModel) return;
	// The glTF has a node per object ("handle", "cap") with a mesh per face below it: one plane
	// per object, through its own axis (glTF: y up), facing +z.
	for (const name of ["handle", "cap"]) {
		const object = currentModel.getObjectByName(name);
		if (!object) continue;
		const center = new THREE.Box3().setFromObject(object).getCenter(new THREE.Vector3());
		const plane = new THREE.Plane(new THREE.Vector3(0, 0, -1), center.z);  // keeps z < center
		const meshes = [];
		object.traverse((child) => child.isMesh && !child.userData.section && meshes.push(child));
		for (const mesh of meshes) {
			mesh.children.filter((c) => c.userData.section).forEach((c) => mesh.remove(c));
			mesh.material.clippingPlanes = cutInput.checked ? [plane] : [];
			mesh.material.side = THREE.FrontSide;
			mesh.material.needsUpdate = true;
			if (!cutInput.checked) continue;
			const inside = new THREE.Mesh(mesh.geometry, new THREE.MeshBasicMaterial({
				color: SECTION_COLOUR, side: THREE.BackSide, clippingPlanes: [plane],
			}));
			inside.userData.section = true;
			mesh.add(inside);
		}
	}
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
		// The summary validates the parameters and reports the warnings.
		const infoResponse = await fetchWithProgress(`${API}/info?${query}`, (t) => mine === generation && setStatus(t));
		if (mine !== generation) return;
		if (!infoResponse.ok) {
			infoEl.textContent = "";
			setStatus(await friendlyErrorMessage(infoResponse), true);
			return;
		}
		const info = await infoResponse.json();
		infoEl.textContent = info.summary;
		capFlange = info.cap_flange ?? capFlange;
		capHeight = info.cap_height ?? capHeight;

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
		capHome = null;
		currentModel.traverse((child) => {
			if (child.isMesh) {
				const color = child.material && child.material.color ? child.material.color : new THREE.Color(0xdddddd);
				child.material = new THREE.MeshStandardMaterial({ color, metalness: 0.0, roughness: 0.6 });
			}
		});
		scene.add(currentModel);
		applyAssembled();
		lastQuery = String(query);
		updateBits(lastQuery);
		if (!cameraFitted) {
			fitCameraToObject(currentModel);
			cameraFitted = true;
		}
		placeholderEl.style.display = "none";
		downloadBtn.disabled = false;
		downloadStepBtn.disabled = false;
		setStatus(`Generated${assembledInput.checked ? ", shown assembled (saved in print orientation)" : ", in print orientation"}. Drag to rotate.`);
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
cutInput.addEventListener("change", applyCutView);
assembledInput.addEventListener("change", applyAssembled);
bitsInput.addEventListener("change", () => updateBits(lastQuery));
for (const el of [knurlInput, holesInput]) {
	el.addEventListener("change", () => {
		updateFields();
		onGenerate();
	});
}
Object.values(inputs).forEach((el) => {
	el.addEventListener("input", () => {
		downloadBtn.disabled = true;
		downloadStepBtn.disabled = true;
	});
	el.addEventListener("keydown", (e) => {
		if (e.key === "Enter") onGenerate();
	});
});

// Presets: picking one fills the fields; editing a field selects the matching preset, or "Custom".
const CUSTOM = "custom";
let presets = {};

function fieldValue(id) {
	const el = document.getElementById(id);
	return el.type === "checkbox" ? el.checked : el.value;
}

function sameValue(id, value) {
	const current = fieldValue(id);
	if (typeof value === "boolean") return current === value;
	return typeof value === "number" ? parseNumber(String(current)) === value : String(current) === String(value);
}

function matchingPreset() {
	for (const [name, values] of Object.entries(presets)) {
		if (Object.entries(values).every(([id, value]) => !document.getElementById(id) || sameValue(id, value))) return name;
	}
	return CUSTOM;
}

function setupPresets(serverPresets) {
	presets = serverPresets || {};
	presetSelect.replaceChildren(...Object.keys(presets).map((name) => new Option(name, name)), new Option("Custom", CUSTOM));
	presetSelect.value = matchingPreset();
}

presetSelect.addEventListener("change", () => {
	if (presetSelect.value === CUSTOM) return;
	for (const [id, value] of Object.entries(presets[presetSelect.value])) {
		const el = document.getElementById(id);
		if (!el) continue;
		if (el.type === "checkbox") el.checked = Boolean(value);
		else el.value = String(value);
	}
	updateFields();
	onGenerate();
});
[...Object.values(inputs), knurlInput, holesInput].forEach((el) =>
	el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", () => {
		presetSelect.value = matchingPreset();
	}));

function start() {
	return loadDefaults(API)
		.then((defaults) => {
			setupPresets(defaults.presets);
			updateFields();
			onGenerate();
		})
		.catch((exc) => setStatus(exc.message, true));
}
defaultsBtn.addEventListener("click", start);

// Start from the server's defaults (the model's), then show the default handle.
start();
