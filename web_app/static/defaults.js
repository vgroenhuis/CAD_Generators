// Loads a page's starting values from the server (api/<generator>/defaults), which
// takes them from the model's own defaults: they are defined in one place only, and
// always match the default model the server prepares at startup.

// Fill the inputs whose id matches a key; keys without an input are ignored.
export async function loadDefaults(api) {
	const response = await fetch(`${api}/defaults`, { cache: "no-store" });
	if (!response.ok) throw new Error(`Could not load the default settings (${response.status}).`);
	const defaults = await response.json();
	for (const [id, value] of Object.entries(defaults)) {
		const el = document.getElementById(id);
		if (!el) continue;
		if (el.type === "checkbox" || el.type === "radio") el.checked = Boolean(value);
		else el.value = String(value);
	}
	return defaults;
}
