import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { downloadWithProgress, fetchWithProgress } from "./progress.js";
import { loadDefaults } from "./defaults.js";

const API = "api/pneumatic/connector-male";
// Input ids = query parameter names.
const NUMBER_FIELDS = ["ports", "hole", "pitch"];
const clipsInput = document.getElementById("clips");
const viewPrintInput = document.getElementById("view_print");
const viewAssembledInput = document.getElementById("view_assembled");
const openingControls = document.getElementById("opening-controls");
const openingInput = document.getElementById("opening");
const openingValue = document.getElementById("opening-value");
const animateBtn = document.getElementById("animate-btn");
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
// Assembled view (see setupHinges): clip hinges and the open/close animation.
const ANIMATION_PERIOD = 3000;
let hinges = []; // [{ node, start matrix, pivot (node's parent frame), axis }]
let animating = false;
let animationStart = 0;

function resizeRenderer() {
	const width = viewerContainer.clientWidth;
	const height = viewerContainer.clientHeight;
	renderer.setSize(width, height, false);
	camera.aspect = width / (height || 1);
	camera.updateProjectionMatrix();
}
window.addEventListener("resize", resizeRenderer);
resizeRenderer();

function animate(time) {
	requestAnimationFrame(animate);
	if (animating) {
		// Open and close smoothly, one cycle every ANIMATION_PERIOD ms.
		const phase = ((time - animationStart) % ANIMATION_PERIOD) / ANIMATION_PERIOD;
		setOpening((Number(openingInput.max) * (1 - Math.cos(2 * Math.PI * phase))) / 2);
	}
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
		const value = parseNumber(document.getElementById(id).value);
		if (!Number.isFinite(value)) {
			const label = document.querySelector(`label[for="${id}"]`).textContent;
			throw new Error(`${label} must be a number (use a dot as decimal separator).`);
		}
		if (id === "ports" && !Number.isInteger(value)) {
			const label = document.querySelector(`label[for="${id}"]`).textContent;
			throw new Error(`${label} must be a whole number.`);
		}
		params[id] = value;
	}
	params.clips = clipsInput.checked;
	return params;
}

function buildQuery(params) {
	return new URLSearchParams(Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])));
}

// view: "print" (from above at an angle) or "assembled" (from the front, where the clips turn).
function fitCameraToObject(object, view = "print") {
	const box = new THREE.Box3().setFromObject(object);
	const size = box.getSize(new THREE.Vector3());
	const center = box.getCenter(new THREE.Vector3());
	const maxDim = Math.max(size.x, size.y, size.z) || 1;
	const distance = maxDim * 1.6;
	controls.target.copy(center);
	if (view === "assembled") camera.position.set(center.x + distance * 0.25, center.y + distance * 0.35, center.z + distance);
	else camera.position.set(center.x + distance * 0.5, center.y + distance * 0.9, center.z + distance * 0.8);
	camera.near = maxDim / 100;
	camera.far = maxDim * 100;
	camera.updateProjectionMatrix();
	controls.update();
}

const gltfLoader = new GLTFLoader();

// --- Assembled view: each clip turns about its hinge line (from api/.../assembly).


function assembled() {
	return viewAssembledInput.checked;
}

// The glTF's root node turns the CAD frame (Z up, mm -> m) into three.js's Y-up frame; the clip
// nodes are its children, so the hinge lines are used in the root's (CAD) frame, in metres.
function setupHinges(model, info) {
	hinges = Object.entries(info.hinges).map(([name, hinge]) => {
		const node = model.getObjectByName(name);
		node.updateMatrix();
		node.matrixAutoUpdate = false;
		return {
			node,
			start: node.matrix.clone(),
			pivot: new THREE.Vector3(...hinge.point).multiplyScalar(0.001),
			axis: new THREE.Vector3(...hinge.axis).normalize(),
		};
	});
	openingInput.max = String(info.max_angle);
	setOpening(Math.min(Number(openingInput.value), info.max_angle));
}

function setOpening(degrees) {
	openingInput.value = String(degrees);
	openingValue.textContent = Number(degrees).toFixed(0);
	const angle = THREE.MathUtils.degToRad(degrees);
	for (const h of hinges) {
		const turn = new THREE.Matrix4()
			.makeTranslation(h.pivot.x, h.pivot.y, h.pivot.z)
			.multiply(new THREE.Matrix4().makeRotationAxis(h.axis, angle))
			.multiply(new THREE.Matrix4().makeTranslation(-h.pivot.x, -h.pivot.y, -h.pivot.z));
		h.node.matrix.multiplyMatrices(turn, h.start);
		h.node.matrixWorldNeedsUpdate = true;
	}
}

function setAnimating(on) {
	animating = on;
	animateBtn.textContent = on ? "Stop" : "Animate";
	if (on) {
		// Continue from the current opening rather than jumping to closed.
		const max = Number(openingInput.max) || 1;
		const phase = Math.acos(1 - (2 * Number(openingInput.value)) / max) / (2 * Math.PI);
		animationStart = performance.now() - phase * ANIMATION_PERIOD;
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
	generateBtn.disabled = true;
	downloadBtn.disabled = true;
	downloadStepBtn.disabled = true;
	const query = buildQuery(params);
	try {
		// The summary is cheap and validates the parameters before the build.
		const infoResponse = await fetch(`${API}/info?${query}`);
		if (!infoResponse.ok) {
			infoEl.textContent = "";
			setStatus(await friendlyErrorMessage(infoResponse), true);
			return;
		}
		infoEl.textContent = (await infoResponse.json()).summary;

		const asm = assembled();
		const response = await fetchWithProgress(`${API}/${asm ? "assembly.glb" : "preview.glb"}?${query}`, setStatus);
		if (!response.ok) {
			setStatus(await friendlyErrorMessage(response), true);
			return;
		}
		const buffer = await response.arrayBuffer();
		const gltf = await new Promise((resolve, reject) => gltfLoader.parse(buffer, "", resolve, reject));
		let assemblyInfo = null;
		if (asm) {
			setStatus("Finding how far the clips open...");
			const infoResp = await fetch(`${API}/assembly?${query}`);
			if (!infoResp.ok) {
				setStatus(await friendlyErrorMessage(infoResp), true);
				return;
			}
			assemblyInfo = await infoResp.json();
		}
		if (currentModel) scene.remove(currentModel);
		hinges = [];
		currentModel = gltf.scene;
		currentModel.traverse((child) => {
			if (child.isMesh) {
				const color = child.material && child.material.color ? child.material.color : new THREE.Color(0xdddddd);
				child.material = new THREE.MeshStandardMaterial({ color, metalness: 0.0, roughness: 0.6 });
			}
		});
		scene.add(currentModel);
		fitCameraToObject(currentModel, asm ? "assembled" : "print");
		if (assemblyInfo) setupHinges(currentModel, assemblyInfo);
		placeholderEl.style.display = "none";
		downloadBtn.disabled = false;
		downloadStepBtn.disabled = false;
		setStatus(asm
			? `Assembled, clips open up to ${assemblyInfo.max_angle}\u00b0. Drag to rotate.`
			: "Generated, in print orientation. Drag to rotate.");
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
		const response = await downloadWithProgress(`${API}/export.${format}?${buildQuery(params)}`, setStatus);
		setStatus(response.ok ? `Downloaded ${response.filename}.` : await friendlyErrorMessage(response), !response.ok);
	} catch (exc) {
		setStatus(`Download failed: ${exc.message || exc}`, true);
	}
}

generateBtn.addEventListener("click", onGenerate);
downloadBtn.addEventListener("click", () => onDownload("3mf"));
downloadStepBtn.addEventListener("click", () => onDownload("step"));
clipsInput.addEventListener("change", onGenerate);
function updateView() {
	openingControls.hidden = !assembled();
	clipsInput.disabled = assembled(); // the assembled view always shows both clips
	if (!assembled()) setAnimating(false);
	onGenerate();
}
viewPrintInput.addEventListener("change", updateView);
viewAssembledInput.addEventListener("change", updateView);
openingInput.addEventListener("input", () => {
	setAnimating(false);
	setOpening(Number(openingInput.value));
});
animateBtn.addEventListener("click", () => setAnimating(!animating));
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

// Start from the server's defaults (the model's), then show the default connector.
loadDefaults(API)
	.then(() => onGenerate())
	.catch((exc) => setStatus(exc.message, true));
