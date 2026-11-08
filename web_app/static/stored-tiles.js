// The list of game tiles stored on the server (api/game-tiles/stored), as a table.

const API = "api/game-tiles";
const statusEl = document.getElementById("status");
const table = document.getElementById("table");
const rows = document.getElementById("rows");

// Query parameters of a tile, in the order the generator's endpoints take them.
const PARAM_KEYS = ["tile_type", "shape", "size", "length", "thickness", "inlay_depth", "count", "seed"];

function el(tag, attrs = {}, ...children) {
	const e = document.createElement(tag);
	for (const [k, v] of Object.entries(attrs)) {
		if (k === "class") e.className = v;
		else e.setAttribute(k, v);
	}
	e.append(...children);
	return e;
}

function query(params) {
	const q = new URLSearchParams();
	for (const k of PARAM_KEYS) {
		if (k === "length" && params.shape !== "rectangle") continue;
		q.set(k, String(params[k]));
	}
	return q.toString();
}

function when(seconds) {
	if (!seconds) return "";
	return new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function size(bytes) {
	return bytes > 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} kB`;
}

function sizeText(p) {
	if (p.shape === "rectangle") return `${p.size} x ${p.length}`;
	if (p.shape === "hexagon") return `${p.size} across flats`;
	if (p.shape === "circle") return `${p.size} diameter`;
	return `${p.size}`;
}

function fileLink(label, href, bytes) {
	const a = el("a", { href }, label + " ");
	a.append(bytes ? el("span", { class: "ready" }, `ready, ${size(bytes)}`) : el("span", { class: "later" }, "to be made"));
	return a;
}

function row(tile, palette) {
	const p = tile.params;
	const q = query(p);
	const open = `game-tiles.html?${q}`;
	const thumb = tile.files.png
		? el("a", { href: open, title: "Open in the generator" }, el("img", { src: `${API}/thumbnail.png?${q}`, alt: tile.title, loading: "lazy" }))
		: el("div", { class: "none" }, "no picture yet");
	const colours = el("div", { class: "colours" });
	for (const name of tile.colours || []) {
		const sw = el("span", { class: "swatch" });
		if (palette[name]) sw.style.background = palette[name];
		colours.append(el("div", {}, sw, name.replace(/_/g, " ")));
	}
	const links = el("div", { class: "links" },
		el("a", { href: open }, "Open in the generator"),
		fileLink("3MF", `${API}/export.3mf?${q}`, tile.files["3mf"]),
		fileLink("STEP", `${API}/export.step?${q}`, tile.files.step));
	return el("tr", {},
		el("td", { class: "thumb" }, thumb),
		el("td", {}, tile.title),
		el("td", {}, p.shape),
		el("td", { class: "num" }, sizeText(p)),
		el("td", { class: "num" }, `${p.thickness}`),
		el("td", { class: "num" }, `${p.inlay_depth}`),
		el("td", { class: "num" }, `${p.count}`),
		el("td", { class: "num" }, `${p.seed}`),
		el("td", {}, colours),
		el("td", { class: "when" }, when(tile.created)),
		el("td", { class: "when" }, when(tile.used)),
		el("td", {}, links));
}

async function load() {
	try {
		const [storedRes, paletteRes] = await Promise.all([fetch(`${API}/stored`, { cache: "no-store" }), fetch(`${API}/palette`)]);
		if (!storedRes.ok) throw new Error(`Could not load the list (${storedRes.status}).`);
		const stored = await storedRes.json();
		const palette = paletteRes.ok ? await paletteRes.json() : {};
		if (!stored.enabled) {
			statusEl.textContent = "Tiles are not stored on this server (its disk cache is turned off).";
			return;
		}
		if (!stored.tiles.length) {
			statusEl.textContent = "No stored tiles yet. Tiles you generate are added here.";
			return;
		}
		statusEl.textContent = `${stored.tiles.length} stored tile${stored.tiles.length === 1 ? "" : "s"}.`;
		rows.replaceChildren(...stored.tiles.map((t) => row(t, palette)));
		table.hidden = false;
	} catch (exc) {
		statusEl.textContent = exc.message || String(exc);
		statusEl.classList.add("error");
	}
}

load();
