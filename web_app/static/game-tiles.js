import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { downloadWithProgress, fetchWithProgress } from "./progress.js";
import { showViewerError } from "./error-banner.js";

const API = "api/game-tiles";
// Input ids = query parameter names.
const NUMBER_FIELDS = ["size", "length", "thickness", "inlay_depth", "count", "seed", "wall", "clearance"];
const INTEGER_FIELDS = ["count", "seed"];
const typeSelect = document.getElementById("tile_type");
const shapeSelect = document.getElementById("shape");
const typeDescription = document.getElementById("type-description");
const sizeLabel = document.getElementById("size-label");
const lengthBox = document.getElementById("length-box");
const seedInput = document.getElementById("seed");
const baseSelect = document.getElementById("base_colour");
const generateBtn = document.getElementById("generate-btn");
const downloadBtn = document.getElementById("download-btn");
const downloadStepBtn = document.getElementById("download-step-btn");
const infoEl = document.getElementById("info");
const swatchesEl = document.getElementById("swatches");
const meshStatsEl = document.getElementById("mesh-stats");
const statusEl = document.getElementById("status");
const placeholderEl = document.getElementById("viewer-placeholder");
const canvas = document.getElementById("viewer-canvas");
const viewerContainer = document.querySelector(".viewer");

const SIZE_LABELS = {
	square: "Side (mm)", rectangle: "Width (mm)", hexagon: "Across flats (mm)", triangle: "Side (mm)", circle: "Diameter (mm)",
};

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1d21);

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
camera.position.set(0.05, 0.12, 0.09);

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

scene.add(new THREE.AmbientLight(0xffffff, 0.75));
const keyLight = new THREE.DirectionalLight(0xffffff, 0.9);
keyLight.position.set(-1, 2.5, 1.2);
scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0xffffff, 0.25);
fillLight.position.set(1.5, -1, -1);
scene.add(fillLight);

let currentModel = null;
// The camera is fitted to the first model only; re-generating keeps it, so changes are easy to compare.
let cameraFitted = false;
let tileTypes = [];

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

// Plain dot-decimal numbers only, independent of the browser locale (the
// fields are type="text", so a comma is never taken as a decimal separator).
function parseNumber(text) {
	const trimmed = text.trim();
	return /^\d*\.?\d+$|^\d+\.$/.test(trimmed) ? parseFloat(trimmed) : NaN;
}

function readParams() {
	const params = { tile_type: typeSelect.value, shape: shapeSelect.value, base_colour: baseSelect.value };
	for (const id of NUMBER_FIELDS) {
		if (id === "length" && shapeSelect.value !== "rectangle") continue;
		const value = parseNumber(document.getElementById(id).value);
		const label = document.querySelector(`label[for="${id}"]`).textContent;
		if (!Number.isFinite(value)) throw new Error(`${label} must be a number (use a dot as decimal separator).`);
		if (INTEGER_FIELDS.includes(id) && !Number.isInteger(value)) throw new Error(`${label} must be a whole number.`);
		params[id] = value;
	}
	return params;
}

function buildQuery(params) {
	return new URLSearchParams(Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])));
}

// Looking down at the tiles from the front, at about 50 degrees.
function fitCameraToObject(object) {
	const box = new THREE.Box3().setFromObject(object);
	const size = box.getSize(new THREE.Vector3());
	const center = box.getCenter(new THREE.Vector3());
	const maxDim = Math.max(size.x, size.y, size.z) || 1;
	const distance = maxDim * 1.5;
	controls.target.copy(center);
	camera.position.set(center.x, center.y + distance * 0.9, center.z + distance * 0.75);
	camera.near = maxDim / 100;
	camera.far = maxDim * 100;
	camera.updateProjectionMatrix();
	controls.update();
}

const gltfLoader = new GLTFLoader();

canvas.title = "Drag to rotate, scroll to zoom, double-click to fit the model in view.";
canvas.addEventListener("dblclick", () => currentModel && fitCameraToObject(currentModel));

function showColors(colors) {
	swatchesEl.replaceChildren(...colors.map((c, i) => {
		const item = document.createElement("span");
		item.className = "swatch";
		const box = document.createElement("i");
		box.style.background = c.hex;
		item.append(box, `${c.name}${i === 0 ? " (base)" : ""}`);
		return item;
	}));
}

let generation = 0;

// Size of the print mesh (the 3MF file): asked for after the preview, as making the 3MF file
// can take a few seconds (it is then ready for the download).
async function showMeshStats(query, mine) {
	meshStatsEl.textContent = "Print mesh (3MF): counting...";
	try {
		const response = await fetch(`${API}/mesh-stats?${query}`);
		if (mine !== generation) return;
		if (!response.ok) {
			meshStatsEl.textContent = "";
			return;
		}
		const stats = await response.json();
		const n = (x) => x.toLocaleString("en-US");
		meshStatsEl.textContent = `Print mesh (3MF): ${n(stats.triangles)} faces (triangles), ${n(stats.vertices)} vertices`;
		meshStatsEl.title = stats.colours.map((c) => `${c.name}: ${n(c.triangles)} faces, ${n(c.vertices)} vertices`).join("\n");
	} catch (exc) {
		if (mine === generation) meshStatsEl.textContent = "";
	}
}

async function onGenerate() {
	let params;
	try {
		params = readParams();
	} catch (exc) {
		setStatus(exc.message, true);
		return;
	}
	const mine = ++generation;  // a newer request (e.g. quick changes of type) wins
	generateBtn.disabled = true;
	downloadBtn.disabled = true;
	downloadStepBtn.disabled = true;
	const query = buildQuery(params);
	try {
		// The summary is cheap and validates the parameters before the build.
		meshStatsEl.textContent = "";
		const infoResponse = await fetch(`${API}/info?${query}`);
		if (mine !== generation) return;
		if (!infoResponse.ok) {
			infoEl.textContent = "";
			swatchesEl.replaceChildren();
			setStatus(await friendlyErrorMessage(infoResponse), true);
			return;
		}
		const info = await infoResponse.json();
		infoEl.textContent = info.summary;
		showColors(info.colors);

		const response = await fetchWithProgress(`${API}/preview.glb?${query}`, setStatus);
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
				// Rough (fuzzy) tiles come without normals: shade their triangles flat.
				const flatShading = !child.geometry.attributes.normal;
				child.material = new THREE.MeshStandardMaterial({ color, metalness: 0.0, roughness: 0.7, flatShading });
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
		setStatus(`Generated, ${info.colors.length} colours. Drag to rotate.`);
		showMeshStats(query, mine);
	} catch (exc) {
		setStatus(`Failed to load preview: ${exc.message || exc}`, true);
	} finally {
		if (mine === generation) generateBtn.disabled = false;
	}
}

// format: "3mf" (for slicing) or "step" (for CAD)
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

function updateShape() {
	const shape = shapeSelect.value;
	sizeLabel.textContent = SIZE_LABELS[shape] || "Size (mm)";
	lengthBox.style.visibility = shape === "rectangle" ? "visible" : "hidden";
}

function updateDescription() {
	const t = tileTypes.find((x) => x.id === typeSelect.value);
	typeDescription.textContent = t ? `${t.description[0].toUpperCase()}${t.description.slice(1)}.` : "";
}

// The type and shape lists come from the server, with the starting values.
async function setup() {
	const response = await fetch(`${API}/defaults`, { cache: "no-store" });
	if (!response.ok) throw new Error(`Could not load the default settings (${response.status}).`);
	const defaults = await response.json();
	tileTypes = defaults.types;
	const groups = new Map();
	for (const t of tileTypes) {
		if (!groups.has(t.group)) {
			const og = document.createElement("optgroup");
			og.label = t.group;
			groups.set(t.group, og);
			typeSelect.append(og);
		}
		groups.get(t.group).append(new Option(t.title, t.id));
	}
	for (const shape of defaults.shapes) shapeSelect.add(new Option(shape[0].toUpperCase() + shape.slice(1), shape));
	baseSelect.add(new Option("Same as the tile", ""));
	for (const name of defaults.colours) baseSelect.add(new Option(name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()), name));
	baseSelect.value = defaults.base_colour;
	typeSelect.value = defaults.tile_type;
	shapeSelect.value = defaults.shape;
	for (const id of NUMBER_FIELDS) document.getElementById(id).value = String(defaults[id]);
	// Settings in the address (e.g. from the list of stored tiles) override the defaults.
	const fromUrl = new URLSearchParams(window.location.search);
	const urlType = fromUrl.get("tile_type") === "connector" ? "connector_corners" : fromUrl.get("tile_type");  // the ledge connector is gone
	if (urlType && tileTypes.some((t) => t.id === urlType)) typeSelect.value = urlType;
	if (fromUrl.has("shape") && defaults.shapes.includes(fromUrl.get("shape"))) shapeSelect.value = fromUrl.get("shape");
	if (fromUrl.has("base_colour") && (fromUrl.get("base_colour") === "" || defaults.colours.includes(fromUrl.get("base_colour")))) {
		baseSelect.value = fromUrl.get("base_colour");
	}
	for (const id of NUMBER_FIELDS) {
		if (fromUrl.has(id) && Number.isFinite(parseNumber(fromUrl.get(id)))) document.getElementById(id).value = fromUrl.get(id);
	}
	updateShape();
	updateTypeFields();
	updateDescription();
	onGenerate();
}

generateBtn.addEventListener("click", onGenerate);
downloadBtn.addEventListener("click", () => onDownload("3mf"));
downloadStepBtn.addEventListener("click", () => onDownload("step"));
// A connector (a sleeve) has a fixed height and no colours: instead of thickness and colour
// depth it has a wall thickness and a clearance.
function updateTypeFields() {
	const connector = typeSelect.value.startsWith("connector");
	document.getElementById("tile-row").hidden = connector;
	document.getElementById("connector-row").hidden = !connector;
	document.getElementById("base-box").hidden = connector;
}

typeSelect.addEventListener("change", () => {
	updateTypeFields();
	updateDescription();
	onGenerate();
});
baseSelect.addEventListener("change", onGenerate);
shapeSelect.addEventListener("change", () => {
	updateShape();
	onGenerate();
});
document.getElementById("next-seed").addEventListener("click", () => {
	const seed = parseNumber(seedInput.value);
	seedInput.value = String(Number.isInteger(seed) ? seed + 1 : 1);
	onGenerate();
});
NUMBER_FIELDS.forEach((id) => {
	const el = document.getElementById(id);
	el.addEventListener("input", () => {
		downloadBtn.disabled = true;
		downloadStepBtn.disabled = true;
	});
	el.addEventListener("keydown", (e) => {
		if (e.key === "Enter") onGenerate();
	});
});

setup().catch((exc) => setStatus(exc.message, true));
