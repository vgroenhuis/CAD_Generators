import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { downloadWithProgress, fetchWithProgress } from "./progress.js";
import { loadDefaults } from "./defaults.js";

const API = "api/pneumatic/connector";
// Input ids = query parameter names.
const NUMBER_FIELDS = ["ports", "pitch", "hole", "back_bore"];
const clipsInput = document.getElementById("clips");
const partMaleInput = document.getElementById("part_male");
const partFemaleInput = document.getElementById("part_female");
const viewPrintInput = document.getElementById("view_print");
const viewAssembledInput = document.getElementById("view_assembled");
const connectionControls = document.getElementById("connection-controls");
const connectionInput = document.getElementById("connection");
const connectionText = document.getElementById("connection-text");
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
// Assembled view (see setupAssembly): the male part's nodes, the clip hinges and the animation.
const ANIMATION_PERIOD = 8000;
let moving = []; // [{ node, start matrix, hinge: { pivot, axis } (clips only) }]
let assemblyInfo = null;
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
	if (animating) setConnection(animationConnection((time - animationStart) % ANIMATION_PERIOD));
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
	params.part = partFemaleInput.checked ? "female" : "male";
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

// --- Assembled view. One "connection" value from 0 to 100 drives it: from 0 (male part pulled
// out, clips open) to 50 the male part goes in, from 50 to 100 the clips close.

function assembled() {
	return viewAssembledInput.checked;
}

// The glTF's root node turns the CAD frame (Z up, mm -> m) into three.js's Y-up frame; the moving
// nodes are its children, so the hinge lines and the insertion are used in the root's (CAD)
// frame, in metres.
function setupAssembly(model, info) {
	assemblyInfo = info;
	moving = info.insert.parts.map((name) => {
		const node = model.getObjectByName(name);
		node.updateMatrix();
		node.matrixAutoUpdate = false;
		const hinge = info.hinges[name];
		return {
			node,
			start: node.matrix.clone(),
			hinge: hinge && {
				pivot: new THREE.Vector3(...hinge.point).multiplyScalar(0.001),
				axis: new THREE.Vector3(...hinge.axis).normalize(),
			},
		};
	});
	setConnection(Number(connectionInput.value));
}

function setConnection(value) {
	connectionInput.value = String(value);
	if (!assemblyInfo) return;
	const { travel, direction } = assemblyInfo.insert;
	const out = travel * Math.max(0, 1 - value / 50); // mm the male part is pulled out
	const opening = assemblyInfo.max_angle * Math.min(1, 2 - value / 50); // degrees
	connectionText.textContent = value < 50
		? `male part ${out.toFixed(1)} mm out, clips open`
		: value < 100 ? `inserted, clips ${opening.toFixed(0)}\u00b0 open` : "connected, clips closed";
	const shift = new THREE.Matrix4().makeTranslation(
		...direction.map((d) => (d * out) / 1000),
	);
	const angle = THREE.MathUtils.degToRad(opening);
	for (const m of moving) {
		const transform = shift.clone();
		if (m.hinge) {
			const { pivot, axis } = m.hinge;
			transform
				.multiply(new THREE.Matrix4().makeTranslation(pivot.x, pivot.y, pivot.z))
				.multiply(new THREE.Matrix4().makeRotationAxis(axis, angle))
				.multiply(new THREE.Matrix4().makeTranslation(-pivot.x, -pivot.y, -pivot.z));
		}
		m.node.matrix.multiplyMatrices(transform, m.start);
		m.node.matrixWorldNeedsUpdate = true;
	}
}

// One animation cycle: connect (40%), hold, disconnect (40%), hold; eased in and out.
function animationConnection(t) {
	const phase = t / ANIMATION_PERIOD;
	const ease = (x) => x * x * (3 - 2 * x);
	if (phase < 0.4) return 100 * ease(phase / 0.4);
	if (phase < 0.5) return 100;
	if (phase < 0.9) return 100 * (1 - ease((phase - 0.5) / 0.4));
	return 0;
}

function setAnimating(on) {
	animating = on;
	animateBtn.textContent = on ? "Stop" : "Animate";
	// Start disconnecting from where the slider is (connected) or connecting (otherwise).
	if (on) animationStart = performance.now() - (Number(connectionInput.value) >= 100 ? 0.5 : 0) * ANIMATION_PERIOD;
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
		let info = null;
		if (asm) {
			setStatus("Finding how far the clips open...");
			const infoResp = await fetch(`${API}/assembly?${query}`);
			if (!infoResp.ok) {
				setStatus(await friendlyErrorMessage(infoResp), true);
				return;
			}
			info = await infoResp.json();
		}
		if (currentModel) scene.remove(currentModel);
		moving = [];
		assemblyInfo = null;
		currentModel = gltf.scene;
		currentModel.traverse((child) => {
			if (child.isMesh) {
				const color = child.material && child.material.color ? child.material.color : new THREE.Color(0xdddddd);
				child.material = new THREE.MeshStandardMaterial({ color, metalness: 0.0, roughness: 0.6 });
			}
		});
		scene.add(currentModel);
		fitCameraToObject(currentModel, asm ? "assembled" : "print");
		if (info) setupAssembly(currentModel, info);
		placeholderEl.style.display = "none";
		downloadBtn.disabled = false;
		downloadStepBtn.disabled = false;
		setStatus(asm
			? `Assembled; the clips open up to ${info.max_angle}\u00b0. Drag to rotate.`
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
// Fields of the part that is not selected are greyed out; the assembled view shows both parts.
function updateFields() {
	const female = partFemaleInput.checked;
	document.getElementById("hole").disabled = female;
	clipsInput.disabled = female || assembled();
	document.getElementById("back_bore").disabled = !female;
	connectionControls.hidden = !assembled();
	document.getElementById("pause-note").hidden = !female;
}
function updateView() {
	updateFields();
	if (!assembled()) setAnimating(false);
	onGenerate();
}
viewPrintInput.addEventListener("change", updateView);
viewAssembledInput.addEventListener("change", updateView);
partMaleInput.addEventListener("change", updateView);
partFemaleInput.addEventListener("change", updateView);
connectionInput.addEventListener("input", () => {
	setAnimating(false);
	setConnection(Number(connectionInput.value));
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
	.then(() => {
		updateFields();
		onGenerate();
	})
	.catch((exc) => setStatus(exc.message, true));
