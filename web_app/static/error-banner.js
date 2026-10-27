// Error banner at the top of the viewer. The status line sits below the buttons at the bottom of
// the controls pane, which on long pages is scrolled out of sight; the viewer is always in view.

let banner = null;

function create() {
	banner = document.createElement("div");
	banner.setAttribute("role", "alert");
	banner.title = "Click to dismiss";
	Object.assign(banner.style, {
		position: "absolute", top: "12px", left: "12px", right: "12px", zIndex: "10",
		padding: "8px 12px", borderRadius: "6px", border: "1px solid #e08a8a",
		background: "rgba(58, 34, 36, 0.95)", color: "#f2c4c4",
		font: '13px "Segoe UI", sans-serif', whiteSpace: "pre-wrap", cursor: "pointer",
	});
	banner.hidden = true;
	banner.addEventListener("click", () => {
		banner.hidden = true;
	});
	document.querySelector(".viewer").appendChild(banner);
}

// Show `text` as an error over the viewer, or hide the banner when it is empty.
export function showViewerError(text) {
	if (!banner) create();
	banner.textContent = text || "";
	banner.hidden = !text;
}
