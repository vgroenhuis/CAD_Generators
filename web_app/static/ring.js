import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const odInput = document.getElementById("od");
const idInput = document.getElementById("id");
const thicknessInput = document.getElementById("thickness");
const generateBtn = document.getElementById("generate-btn");
const downloadBtn = document.getElementById("download-btn");
const statusEl = document.getElementById("status");
const placeholderEl = document.getElementById("viewer-placeholder");
const canvas = document.getElementById("viewer-canvas");
const viewerContainer = document.querySelector(".viewer");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1d21);

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
camera.position.set(60, 60, 60);

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
	const od = parseFloat(odInput.value);
	const id = parseFloat(idInput.value);
	const thickness = parseFloat(thicknessInput.value);
	if (!Number.isFinite(od) || !Number.isFinite(id) || !Number.isFinite(thickness)) {
		throw new Error("OD, ID, and thickness must be numeric values.");
	}
	if (od <= 0 || id <= 0 || thickness <= 0) {
		throw new Error("OD, ID, and thickness must be greater than 0.");
	}
	if (od <= id) {
		throw new Error("OD must be greater than ID.");
	}
	return { od, id, thickness };
}

function fitCameraToObject(object) {
	const box = new THREE.Box3().setFromObject(object);
	const size = box.getSize(new THREE.Vector3());
	const center = box.getCenter(new THREE.Vector3());
	const maxDim = Math.max(size.x, size.y, size.z) || 1;
	const distance = maxDim * 1.8;

	controls.target.copy(center);
	camera.position.set(center.x + distance, center.y + distance, center.z + distance);
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
	setStatus("Generating...");

	const query = new URLSearchParams({ od: params.od, id: params.id, thickness: params.thickness });
	try {
		const response = await fetch(`/api/ring/preview.glb?${query}`);
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
				child.material = new THREE.MeshStandardMaterial({ color: 0x5a8cd2, metalness: 0.1, roughness: 0.5 });
			}
		});
		scene.add(currentModel);
		fitCameraToObject(currentModel);
		placeholderEl.style.display = "none";

		downloadBtn.disabled = false;
		setStatus(`Generated ring: OD=${params.od} mm, ID=${params.id} mm, thickness=${params.thickness} mm`);
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
	const query = new URLSearchParams({ od: params.od, id: params.id, thickness: params.thickness });
	window.location.href = `/api/ring/export.step?${query}`;
}

generateBtn.addEventListener("click", onGenerate);
downloadBtn.addEventListener("click", onDownload);
[odInput, idInput, thicknessInput].forEach((el) => {
	el.addEventListener("keydown", (e) => {
		if (e.key === "Enter") onGenerate();
	});
});

onGenerate();
