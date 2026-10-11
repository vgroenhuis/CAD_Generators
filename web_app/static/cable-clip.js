import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { downloadWithProgress, fetchWithProgress } from "./progress.js";
import { loadDefaults } from "./defaults.js";

const NUMBER_FIELDS = [
	"diameter", "flat_width", "flat_height", "squeeze", "clip_width", "strap", "tab_thickness", "foot",
	"screw_diameter", "screw_head", "hole_clearance", "countersink_angle", "count",
];
const inputs = Object.fromEntries(NUMBER_FIELDS.map((id) => [id, document.getElementById(id)]));
const roundInput = document.getElementById("cable_round");
const flatInput = document.getElementById("cable_flat");
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

function updateCableFields() {
	const flat = flatInput.checked;
	document.getElementById("round-fields").style.display = flat ? "none" : "";
	document.getElementById("flat-fields").style.display = flat ? "" : "none";
	inputs.diameter.disabled = flat;
	inputs.flat_width.disabled = !flat;
	inputs.flat_height.disabled = !flat;
}

function readParams() {
	const params = {};
	for (const id of NUMBER_FIELDS) {
		if (inputs[id].disabled) continue; // the other cable type's size
		const value = parseNumber(inputs[id].value);
		if (!Number.isFinite(value)) {
			const label = document.querySelector(`label[for="${id}"]`).textContent;
			throw new Error(`${label} must be a number (use a dot as decimal separator).`);
		}
		params[id] = value;
	}
	if (!Number.isInteger(params.count)) throw new Error("The number of clips must be a whole number.");
	params.flat = flatInput.checked;
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
		// The summary is cheap and validates the parameters before the build.
		const infoResponse = await fetch(`api/cable-clip/info?${query}`);
		if (!infoResponse.ok) {
			infoEl.textContent = "";
			setStatus(await friendlyErrorMessage(infoResponse), true);
			return;
		}
		infoEl.textContent = (await infoResponse.json()).summary;

		const response = await fetchWithProgress(`api/cable-clip/preview.glb?${query}`, setStatus);
		if (!response.ok) {
			setStatus(await friendlyErrorMessage(response), true);
			return;
		}
		const buffer = await response.arrayBuffer();
		const gltf = await new Promise((resolve, reject) => gltfLoader.parse(buffer, "", resolve, reject));
		if (currentModel) scene.remove(currentModel);
		currentModel = gltf.scene;
		currentModel.traverse((child) => {
			if (child.isMesh) {
				const color = child.material && child.material.color ? child.material.color : new THREE.Color(0xdddddd);
				child.material = new THREE.MeshStandardMaterial({ color, metalness: 0.0, roughness: 0.6 });
			}
		});
		scene.add(currentModel);
		fitCameraToObject(currentModel);
		placeholderEl.style.display = "none";
		downloadBtn.disabled = false;
		downloadStepBtn.disabled = false;
		setStatus("Generated, in print orientation (on its side). Drag to rotate.");
	} catch (exc) {
		setStatus(`Failed to load preview: ${exc.message || exc}`, true);
	} finally {
		generateBtn.disabled = false;
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
		const response = await downloadWithProgress(`api/cable-clip/export.${format}?${buildQuery(params)}`, setStatus);
		setStatus(response.ok ? `Downloaded ${response.filename}.` : await friendlyErrorMessage(response), !response.ok);
	} catch (exc) {
		setStatus(`Download failed: ${exc.message || exc}`, true);
	}
}

generateBtn.addEventListener("click", onGenerate);
downloadBtn.addEventListener("click", () => onDownload("3mf"));
downloadStepBtn.addEventListener("click", () => onDownload("step"));
[roundInput, flatInput].forEach((el) =>
	el.addEventListener("change", () => {
		updateCableFields();
		onGenerate();
	}),
);
Object.values(inputs).forEach((el) => {
	el.addEventListener("input", () => {
		downloadBtn.disabled = true;
		downloadStepBtn.disabled = true;
	});
	el.addEventListener("keydown", (e) => {
		if (e.key === "Enter") onGenerate();
	});
});

// Start from the server's defaults (the model's), then show the default clip.
loadDefaults("api/cable-clip")
	.then(() => {
		updateCableFields();
		onGenerate();
	})
	.catch((exc) => setStatus(exc.message, true));
