// The list of game tiles stored on the server (api/game-tiles/stored), as a table.

const API = "api/game-tiles";
const statusEl = document.getElementById("status");
const table = document.getElementById("table");
const rows = document.getElementById("rows");

// Query parameters of a tile, in the order the generator's endpoints take them.
const PARAM_KEYS = ["tile_type", "shape", "size", "length", "thickness", "inlay_depth", "count", "seed", "wall", "clearance", "base_colour", "rough_depth", "rough_size", "hill_height"];

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
		if (params[k] === undefined) continue;  // stored before this setting existed
		q.set(k, String(params[k]));
	}
	return q.toString();
}

function when(seconds) {
	if (!seconds) return "";
	return new Date(seconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function size(bytes) {
	if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(bytes >= 1e10 ? 0 : 1)} GB`;
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

// A file as stored (made by older code): there or not, it is not made again.
function storedLink(label, tile, kind) {
	const bytes = tile.files[kind];
	if (!bytes) return el("span", { class: "later" }, `${label}: not stored`);
	return el("a", { href: `${API}/stored/${tile.id}/${kind}` }, `${label} `, el("span", { class: "ready" }, size(bytes)));
}

function day(seconds) {
	return new Date(seconds * 1000).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function versionCell(tile) {
	const td = el("td", { class: "when" });
	td.append(tile.commit ? el("span", { class: "commit", title: `code version ${tile.version}` }, tile.commit)
		: el("span", { class: "commit", title: "code that was not committed to git" }, tile.version.slice(0, 7)));
	if (tile.commit_date) td.append(el("div", { class: "sub" }, day(tile.commit_date)));
	td.append(el("div", {}, tile.current ? el("span", { class: "current" }, "current") : el("span", { class: "older" }, "older")));
	return td;
}

function row(tile, palette) {
	const p = tile.params;
	const q = query(p);
	const open = `game-tiles.html?${q}`;
	const thumbSrc = tile.current ? `${API}/thumbnail.png?${q}` : `${API}/stored/${tile.id}/png`;
	const thumb = tile.files.png
		? el("a", { href: tile.current ? open : thumbSrc, title: tile.current ? "Open in the generator" : "The stored picture" },
			el("img", { src: thumbSrc, alt: tile.title, loading: "lazy" }))
		: el("div", { class: "none" }, "no picture yet");
	const colours = el("div", { class: "colours" });
	for (const name of tile.colours || []) {
		const sw = el("span", { class: "swatch" });
		if (palette[name]) sw.style.background = palette[name];
		colours.append(el("div", {}, sw, name.replace(/_/g, " ")));
	}
	const links = tile.current
		? el("div", { class: "links" },
			el("a", { href: open }, "Open in the generator"),
			fileLink("3MF", `${API}/export.3mf?${q}`, tile.files["3mf"]),
			fileLink("STEP", `${API}/export.step?${q}`, tile.files.step))
		: el("div", { class: "links" },
			storedLink("3MF", tile, "3mf"),
			storedLink("STEP", tile, "step"),
			el("a", { href: open, title: "Made with the current code: it can differ from this one" }, "Open in the generator (current version)"));
	const tr = el("tr", { class: tile.current ? "" : "old" },
		el("td", { class: "thumb" }, thumb),
		el("td", {}, tile.title),
		el("td", {}, p.shape),
		el("td", { class: "num" }, sizeText(p)),
		// Connectors have a wall and a clearance instead of a thickness and a colour depth.
		el("td", { class: "num" }, p.tile_type.startsWith("connector") ? `wall ${p.wall}` : `${p.thickness}`),
		el("td", { class: "num" }, p.tile_type.startsWith("connector") ? `clearance ${p.clearance}` : `${p.inlay_depth}`),
		el("td", { class: "num" }, `${p.count}`),
		el("td", { class: "num" }, `${p.seed}`),
		el("td", {}, colours),
		versionCell(tile),
		el("td", { class: "when" }, when(tile.created)),
		el("td", { class: "when" }, when(tile.used)),
		el("td", {}, links));
	return tr;
}

const olderBox = document.getElementById("older");
let allTiles = [], thePalette = {};

function show() {
	const tiles = olderBox.checked ? allTiles : allTiles.filter((t) => t.current);
	rows.replaceChildren(...tiles.map((t) => row(t, thePalette)));
	table.hidden = !tiles.length;
}

try {
	olderBox.checked = localStorage.getItem("stored-tiles-older") !== "0";
} catch { /* no storage: show them */ }
olderBox.addEventListener("change", () => {
	try { localStorage.setItem("stored-tiles-older", olderBox.checked ? "1" : "0"); } catch { /* fine */ }
	show();
});

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
		const b = stored.bytes;
		const current = stored.tiles.filter((t) => t.current).length;
		const older = stored.tiles.length - current;
		let text = stored.tiles.length
			? `${current} tile${current === 1 ? "" : "s"} made by the current version` + (current ? ` (${size(b.listed)})` : "") +
				(older ? `, and ${older} made by older versions.` : ".")
			: "No stored tiles yet. Tiles you generate are added here.";
		text += ` All game tile files: ${size(b.game_tiles)}; the whole store (all generators): ${size(b.store)} of ${size(b.limit)}.`;
		statusEl.textContent = text;
		allTiles = stored.tiles;
		thePalette = palette;
		document.getElementById("filter").hidden = !older;
		show();
	} catch (exc) {
		statusEl.textContent = exc.message || String(exc);
		statusEl.classList.add("error");
	}
}

load();
