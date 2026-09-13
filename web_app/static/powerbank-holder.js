import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const widthInput = document.getElementById("width");
const heightInput = document.getElementById("height");
const lengthInput = document.getElementById("length");
const holeDiameterInput = document.getElementById("hole_diameter");
const outerMarginInput = document.getElementById("outer_margin");
const generateBtn = document.getElementById("generate-btn");
const downloadBtn = document.getElementById("download-btn");
const statusEl = document.getElementById("status");
const derivedEl = document.getElementById("derived");
const derivedThicknessEl = document.getElementById("derived-thickness");
const derivedSpacingEl = document.getElementById("derived-spacing");
const derivedCountEl = document.getElementById("derived-count");
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

function readParams() {
	const width = parseFloat(widthInput.value);
	const height = parseFloat(heightInput.value);
	const length = parseFloat(lengthInput.value);
	const holeDiameter = parseFloat(holeDiameterInput.value);
	const outerMargin = parseFloat(outerMarginInput.value);
	if (
		![width, height, length, holeDiameter, outerMargin].every(Number.isFinite)
	) {
		throw new Error("Width, height, length, hole diameter, and outer wall thickness must be numeric values.");
	}
	if (width <= 0 || height <= 0 || length <= 0 || holeDiameter <= 0 || outerMargin <= 0) {
		throw new Error("Width, height, length, hole diameter, and outer wall thickness must be greater than 0.");
	}
	return { width, height, length, holeDiameter, outerMargin };
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

const gltfLoader = new GLTFLoader();

function buildQuery(params) {
	return new URLSearchParams({
		width: params.width,
		height: params.height,
		length: params.length,
		hole_diameter: params.holeDiameter,
		outer_margin: params.outerMargin,
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
	setStatus("Generating...");

	const query = buildQuery(params);
	try {
		const response = await fetch(`/api/powerbank-holder/preview.glb?${query}`);
		if (!response.ok) {
			setStatus(await friendlyErrorMessage(response), true);
			return;
		}
		const thickness = response.headers.get("X-Wall-Thickness");
		const spacing = response.headers.get("X-Hole-Spacing");
		const count = response.headers.get("X-Hole-Count");

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
				child.material = new THREE.MeshStandardMaterial({ color: 0x5a8cd2, metalness: 0.1, roughness: 0.5 });
			}
		});
		scene.add(currentModel);
		fitCameraToObject(currentModel);
		placeholderEl.style.display = "none";

		downloadBtn.disabled = false;

		if (thickness !== null) {
			derivedThicknessEl.textContent = `${thickness} mm`;
			derivedSpacingEl.textContent = `${spacing} mm`;
			derivedCountEl.textContent = count;
			derivedEl.hidden = false;
		}

		setStatus(
			`Generated powerbank holder: width=${params.width} mm, height=${params.height} mm, length=${params.length} mm`
		);
	} catch (exc) {
		setStatus(`Failed to load preview: ${exc.message || exc}`, true);
	} finally {
		generateBtn.disabled = false;
	}
}

function onDownload() {
	let params;
	try {
		params = readParams();
	} catch (exc) {
		setStatus(exc.message, true);
		return;
	}
	const query = buildQuery(params);
	window.location.href = `/api/powerbank-holder/export.step?${query}`;
}

generateBtn.addEventListener("click", onGenerate);
downloadBtn.addEventListener("click", onDownload);
[widthInput, heightInput, lengthInput, holeDiameterInput, outerMarginInput].forEach((el) => {
	el.addEventListener("keydown", (e) => {
		if (e.key === "Enter") onGenerate();
	});
});

onGenerate();
