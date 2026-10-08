import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { downloadWithProgress, fetchWithProgress } from "./progress.js";

const tagIdInput = document.getElementById("tag_id");
const tagIdsInput = document.getElementById("tag_ids");
const modeInputs = document.querySelectorAll('input[name="tag_mode"]');
const axesInput = document.getElementById("axes");
const sizeInput = document.getElementById("size");
const tagSizeInput = document.getElementById("tag_size");
const depthInput = document.getElementById("depth");
const generateBtn = document.getElementById("generate-btn");
const downloadBtn = document.getElementById("download-btn");
const downloadStepBtn = document.getElementById("download-step-btn");
const statusEl = document.getElementById("status");
const placeholderEl = document.getElementById("viewer-placeholder");
const canvas = document.getElementById("viewer-canvas");
const viewerContainer = document.querySelector(".viewer");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1d21);

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
camera.position.set(120, 120, 120);

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
			return body.detail.map((e) => e.msg || JSON.stringify(e)).join("; ");
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

const FACE_COUNT = 6;

function isDiceMode() {
	return document.querySelector('input[name="tag_mode"]:checked').value === "dice";
}

function updateMode() {
	const dice = isDiceMode();
	tagIdInput.disabled = dice;
	tagIdsInput.disabled = !dice;
}

const MAX_CUBES = 64;

// perFace false: one or more IDs, one cube each (same tag on all faces); true: six IDs for
// faces 1-6 of a single cube, in die order.
function parseTagIds(text, perFace) {
	const parts = text.split(/[,;]/).map((s) => s.trim()).filter((s) => s !== "");
	if (!parts.every((s) => /^\d+$/.test(s))) {
		throw new Error("Tag IDs must be integers, separated by commas.");
	}
	const ids = parts.map(Number);
	if (perFace && ids.length !== FACE_COUNT) {
		throw new Error("Enter 6 comma-separated tag IDs, in die order (faces 1 to 6).");
	}
	if (!perFace && ids.length === 0) throw new Error("Enter at least one tag ID.");
	if (!perFace && ids.length > MAX_CUBES) throw new Error(`At most ${MAX_CUBES} cubes can be generated at once.`);
	if (ids.some((id) => id > 29)) throw new Error("Tag IDs must be between 0 and 29.");
	return ids;
}

function readParams() {
	const tagIds = isDiceMode() ? parseTagIds(tagIdsInput.value, true) : parseTagIds(tagIdInput.value, false);
	const size = parseNumber(sizeInput.value);
	const depth = parseNumber(depthInput.value);
	if (!Number.isFinite(size) || !Number.isFinite(depth)) {
		throw new Error("Size and depth must be numbers (use a dot as decimal separator).");
	}
	if (size <= 0 || depth <= 0) throw new Error("Size and depth must be greater than 0.");
	if (depth >= size / 2) throw new Error("Black depth must be smaller than half the cube size.");
	return { tagIds, size, depth, axes: axesInput.checked, perFace: isDiceMode() };
}

function fitCameraToObject(object) {
	const box = new THREE.Box3().setFromObject(object);
	const size = box.getSize(new THREE.Vector3());
	const center = box.getCenter(new THREE.Vector3());
	const maxDim = Math.max(size.x, size.y, size.z) || 1;
	const distance = maxDim * 1.6;

	controls.target.copy(center);
	camera.position.set(center.x + distance, center.y + distance * 0.8, center.z + distance);
	camera.near = maxDim / 100;
	camera.far = maxDim * 100;
	camera.updateProjectionMatrix();
	controls.update();
}

// The tag is 6 cells wide inside a 1-cell white margin on an 8-cell face.
const TAG_FRACTION = 6 / 8;

function syncTagSizeFromCube() {
	const size = parseNumber(sizeInput.value);
	if (Number.isFinite(size)) tagSizeInput.value = +(size * TAG_FRACTION).toFixed(4);
}

function syncCubeSizeFromTag() {
	const tagSize = parseNumber(tagSizeInput.value);
	if (Number.isFinite(tagSize)) sizeInput.value = +(tagSize / TAG_FRACTION).toFixed(4);
}

sizeInput.addEventListener("input", syncTagSizeFromCube);
tagSizeInput.addEventListener("input", syncCubeSizeFromTag);
syncTagSizeFromCube();

const gltfLoader = new GLTFLoader();

function buildQuery(params) {
	return new URLSearchParams({
		tag_ids: params.tagIds.join(","),
		size: params.size,
		depth: params.depth,
		axes: params.axes,
		per_face: params.perFace,
	});
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

	try {
		const response = await fetchWithProgress(`api/apriltag-cube/preview.glb?${buildQuery(params)}`, setStatus);
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
				// Each body (white, black, red, green) carries its colour in the glTF material.
				const color = child.material && child.material.color ? child.material.color : new THREE.Color(0xeeeeee);
				child.material = new THREE.MeshStandardMaterial({ color, metalness: 0.0, roughness: 0.6 });
			}
		});
		scene.add(currentModel);
		fitCameraToObject(currentModel);
		placeholderEl.style.display = "none";
		downloadBtn.disabled = false;
		downloadStepBtn.disabled = false;
		const idsText = params.tagIds.join(", ");
		let what;
		if (!params.perFace && params.tagIds.length > 1) {
			const n = Math.ceil(Math.sqrt(params.tagIds.length));
			what = `${params.tagIds.length} cubes in a ${n}x${n} grid: tag16h5 ids ${idsText}`;
		} else {
			what = `cube: tag16h5 ${params.tagIds.length === 1 ? "id" : "ids"} ${idsText}`;
		}
		setStatus(`Generated ${what}, ${params.size} mm, black depth ${params.depth} mm`);
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
		const response = await downloadWithProgress(`api/apriltag-cube/export.${format}?${buildQuery(params)}`, setStatus);
		setStatus(response.ok ? `Downloaded ${response.filename}.` : await friendlyErrorMessage(response), !response.ok);
	} catch (exc) {
		setStatus(`Download failed: ${exc.message || exc}`, true);
	}
}

generateBtn.addEventListener("click", onGenerate);
downloadBtn.addEventListener("click", () => onDownload("3mf"));
downloadStepBtn.addEventListener("click", () => onDownload("step"));
modeInputs.forEach((el) => el.addEventListener("change", updateMode));
updateMode();
axesInput.addEventListener("change", onGenerate);
[tagIdInput, tagIdsInput, sizeInput, tagSizeInput, depthInput].forEach((el) => {
	el.addEventListener("keydown", (e) => {
		if (e.key === "Enter") onGenerate();
	});
});

onGenerate();
