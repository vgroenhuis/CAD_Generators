// Shows what the server is doing during a slow request (see web_app/progress.py):
// the request carries a random job id, and api/progress/<job> is polled until the
// response arrives.

const POLL_MS = 700;

function newJob() {
	// crypto.randomUUID needs a secure context, and the site may be served over http.
	return Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0")).join("");
}

// fetch(url), calling onStatus("Building the model... 12 s") while it waits.
export async function fetchWithProgress(url, onStatus) {
	const job = newJob();
	const start = performance.now();
	let stage = null;
	let waiting = true;
	const show = () => onStatus(`${stage || "Waiting for the server"}... ${Math.round((performance.now() - start) / 1000)} s`);

	(async () => {
		while (waiting) {
			try {
				const response = await fetch(`api/progress/${job}`, { cache: "no-store" });
				if (response.ok) {
					const p = await response.json();
					if (p.stage && !p.done) stage = p.stage;
				}
			} catch (e) {
				// keep the last known stage
			}
			if (waiting) show();
			await new Promise((resolve) => setTimeout(resolve, POLL_MS));
		}
	})();

	show();
	try {
		return await fetch(`${url}${url.includes("?") ? "&" : "?"}job=${job}`);
	} finally {
		waiting = false;
	}
}

// Like fetchWithProgress, then saves an ok response as a file (named by the server's
// Content-Disposition). Returns the response, so the caller can report errors.
export async function downloadWithProgress(url, onStatus) {
	const response = await fetchWithProgress(url, onStatus);
	if (!response.ok) return response;
	const blob = await response.blob();
	const disposition = response.headers.get("Content-Disposition") || "";
	const match = /filename="([^"]+)"/.exec(disposition);
	const filename = match ? match[1] : url.split("?")[0].split("/").pop();
	const href = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = href;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(href), 10000);
	response.filename = filename;
	return response;
}
