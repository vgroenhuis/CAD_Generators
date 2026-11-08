// All filament colours of the game tiles (api/game-tiles/colours), with tick boxes for the
// ones you have (kept in this browser's localStorage).

const STORE = "game-tiles-colours-owned";
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const table = document.getElementById("table");
const rows = document.getElementById("rows");

function owned() {
	try {
		return new Set(JSON.parse(localStorage.getItem(STORE) || "[]"));
	} catch (e) {
		return new Set();
	}
}

function save(set) {
	try {
		localStorage.setItem(STORE, JSON.stringify([...set]));
	} catch (e) {
		// not stored (private window): the ticks only last until the page is closed
	}
}

function updateSummary(colours, have) {
	const missing = colours.filter((c) => !have.has(c.id)).map((c) => c.name);
	summaryEl.className = missing.length ? "missing" : "";
	summaryEl.textContent = missing.length
		? `${colours.length} colours, you have ${colours.length - missing.length}. Missing: ${missing.join(", ")}.`
		: `${colours.length} colours: you have them all.`;
}

async function load() {
	try {
		const response = await fetch("api/game-tiles/colours");
		if (!response.ok) throw new Error(`Could not load the colours (${response.status}).`);
		const { colours } = await response.json();
		const have = owned();
		rows.replaceChildren(...colours.map((c) => {
			const tr = document.createElement("tr");
			tr.classList.toggle("have", have.has(c.id));
			const box = document.createElement("input");
			box.type = "checkbox";
			box.checked = have.has(c.id);
			box.addEventListener("change", () => {
				if (box.checked) have.add(c.id);
				else have.delete(c.id);
				save(have);
				tr.classList.toggle("have", box.checked);
				updateSummary(colours, have);
			});
			const label = document.createElement("label");
			label.append(box);
			const sw = document.createElement("span");
			sw.className = "swatch";
			sw.style.background = c.hex;
			const types = document.createElement("td");
			types.className = "types";
			c.types.forEach((t, i) => {
				if (i) types.append(", ");
				if (c.base_of.includes(t)) {
					const b = document.createElement("b");
					b.className = "base";
					b.textContent = t;
					types.append(b);
				} else {
					types.append(t);
				}
			});
			const cell = (cls, ...content) => {
				const td = document.createElement("td");
				if (cls) td.className = cls;
				td.append(...content);
				return td;
			};
			tr.append(cell("", label), cell("", sw), cell("name", c.name), cell("hex", c.hex), types);
			return tr;
		}));
		statusEl.textContent = "";
		table.hidden = false;
		updateSummary(colours, have);
	} catch (exc) {
		statusEl.textContent = exc.message || String(exc);
		statusEl.classList.add("error");
	}
}

load();
