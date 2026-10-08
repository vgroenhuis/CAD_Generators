import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { downloadWithProgress, fetchWithProgress } from "./progress.js";

const NUMBER_FIELDS = ["disc_diameter", "disc_thickness", "tray_units", "back_height", "lip_height", "groove_pitch", "slot_scale"];
const inputs = Object.fromEntries(NUMBER_FIELDS.map((id) => [id, document.getElementById(id)]));
const gritsInput = document.getElementById("grits");
const generateBtn = document.getElementById("generate-btn");
const downloadBtn = document.getElementById("download-btn");
const downloadStepBtn = document.getElementById("download-step-btn");
const slotTestBtn = document.getElementById("slot-test-btn");
const slotTestStepBtn = document.getElementById("slot-test-step-btn");
const showDiscsInput = document.getElementById("show_discs");
const layoutEl = document.getElementById("layout");
const statusEl = document.getElementById("status");
const placeholderEl = document.getElementById("viewer-placeholder");
const canvas = document.getElementById("viewer-canvas");
const viewerContainer = document.querySelector(".viewer");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1d21);

const camera = new THREE.PerspectiveCamera(40, 1, 1, 20000);
camera.position.set(400, 400, 900);

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

function readParams() {
	const params = { grits: gritsInput.value.split("\n").map((s) => s.trim()).filter((s) => s).join(", ") };
	if (!params.grits) throw new Error("Enter at least one grit, e.g. P120:50.");
	for (const id of NUMBER_FIELDS) {
		const value = parseNumber(inputs[id].value);
		if (!Number.isFinite(value)) {
			const label = document.querySelector(`label[for="${id}"]`).textContent;
			throw new Error(`${label} must be a number (use a dot as decimal separator).`);
		}
		params[id] = value;
	}
	if (!Number.isInteger(params.tray_units)) throw new Error("Tray width must be a whole number of 25 mm units.");
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
	// Far enough that the whole (wide, shallow) rack fits the view.
	const distance = maxDim / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * Math.min(camera.aspect, 1.6)) * 1.25;

	// glTF is y-up and the rack's front faces -z: look from the front, a little from above.
	controls.target.copy(center);
	camera.position.set(center.x + distance * 0.25, center.y + distance * 0.45, center.z - distance);
	camera.near = maxDim / 100;
	camera.far = maxDim * 100;
	camera.updateProjectionMatrix();
	controls.update();
}

function escapeHtml(text) {
	return text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function showLayout(layout) {
	const trays = layout.trays.map((t, i) => {
		const grits = t.compartments.map((c) => `${escapeHtml(c.grit)} <span class="muted">(${c.count})</span>`).join(", ");
		const dividers = t.divider_grooves.length ? `dividers in grooves ${t.divider_grooves.join(", ")}` : "no dividers";
		return `<div class="tray"><b>Tray ${i + 1}</b>: ${grits}<br><span class="muted">${dividers}; ${t.spare} mm spare</span></div>`;
	});
	layoutEl.innerHTML =
		`<b>${layout.tray_count} tray(s)</b> of ${layout.tray_width} mm, <b>${layout.divider_count} dividers</b>. ` +
		`<span class="muted">Grooves are numbered from the left, seen from the front.</span>` +
		trays.join("");
}

function applyDiscVisibility() {
	if (!currentModel) return;
	currentModel.traverse((child) => {
		if (child.name && child.name.startsWith("discs")) child.visible = showDiscsInput.checked;
	});
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
		// The layout is cheap and validates the input before the slow build.
		const layoutResponse = await fetch(`api/sanding-rack/layout?${query}`);
		if (!layoutResponse.ok) {
			layoutEl.innerHTML = "";
			setStatus(await friendlyErrorMessage(layoutResponse), true);
			return;
		}
		showLayout(await layoutResponse.json());

		const response = await fetchWithProgress(`api/sanding-rack/preview.glb?${query}`, (text) => setStatus(`${text} (about 10-20 seconds)`));
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
				// Each part carries its colour (and the discs their transparency) in the glTF material.
				const source = child.material || {};
				const color = source.color ? source.color : new THREE.Color(0xeeeeee);
				const opacity = source.opacity ?? 1;
				child.material = new THREE.MeshStandardMaterial({
					color, metalness: 0.0, roughness: 0.6, transparent: opacity < 1, opacity, depthWrite: opacity >= 1,
				});
			}
		});
		scene.add(currentModel);
		applyDiscVisibility();
		fitCameraToObject(currentModel);
		placeholderEl.style.display = "none";
		downloadBtn.disabled = false;
		downloadStepBtn.disabled = false;
		setStatus("Generated. Drag to rotate; the discs are shown see-through.");
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
	const file = format === "3mf" ? "export-3mf.zip" : "export.zip";
	try {
		const response = await downloadWithProgress(`api/sanding-rack/${file}?${buildQuery(params)}`, setStatus);
		setStatus(response.ok ? `Downloaded ${response.filename}.` : await friendlyErrorMessage(response), !response.ok);
	} catch (exc) {
		setStatus(`Download failed: ${exc.message || exc}`, true);
	}
}

async function onSlotTest(format) {
	const scale = parseNumber(inputs.slot_scale.value);
	if (!Number.isFinite(scale)) {
		setStatus("Multiconnect slot scale must be a number.", true);
		return;
	}
	try {
		const response = await downloadWithProgress(`api/sanding-rack/slot-test.${format}?slot_scale=${scale}`, setStatus);
		setStatus(response.ok ? `Downloaded ${response.filename}.` : await friendlyErrorMessage(response), !response.ok);
	} catch (exc) {
		setStatus(`Download failed: ${exc.message || exc}`, true);
	}
}

generateBtn.addEventListener("click", onGenerate);
downloadBtn.addEventListener("click", () => onDownload("3mf"));
downloadStepBtn.addEventListener("click", () => onDownload("step"));
slotTestBtn.addEventListener("click", () => onSlotTest("3mf"));
slotTestStepBtn.addEventListener("click", () => onSlotTest("step"));
showDiscsInput.addEventListener("change", applyDiscVisibility);
// Any change invalidates the download until the next Generate.
[gritsInput, ...Object.values(inputs)].forEach((el) => {
	el.addEventListener("input", () => {
		downloadBtn.disabled = true;
		downloadStepBtn.disabled = true;
	});
});
Object.values(inputs).forEach((el) => {
	el.addEventListener("keydown", (e) => {
		if (e.key === "Enter") onGenerate();
	});
});

onGenerate();
