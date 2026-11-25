// Pneumatic Flow Simulator page: inputs -> PneuFlow model -> tiles, speed bars,
// formula explanation, curves and a numbers table. All in the browser.
(function () {
	"use strict";
	const F = window.PneuFlow;
	const $ = id => document.getElementById(id);
	const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

	const FIELDS = ["p_a", "p_b", "p_amb", "temp", "d", "cd", "tube_d", "tube_l", "rough", "k_extra"];
	const SELECTS = ["cd_preset", "tube_preset", "model"];

	// ------------------------------------------------------------ formatting
	function fmt(x, digits) {
		if (!isFinite(x)) return "–";
		const a = Math.abs(x);
		const d = digits != null ? digits : a >= 1000 ? 0 : a >= 100 ? 1 : a >= 10 ? 2 : a >= 1 ? 3 : 4;
		return x.toFixed(d).replace("-", "−");
	}
	function sig(x, n) {
		if (!isFinite(x)) return "–";
		if (x === 0) return "0";
		const d = Math.max(0, n - 1 - Math.floor(Math.log10(Math.abs(x))));
		return x.toFixed(Math.min(d, 8)).replace("-", "−");
	}
	function sci(x) { // 6.283·10⁻⁷
		const e = Math.floor(Math.log10(Math.abs(x)));
		return `${(x / Math.pow(10, e)).toFixed(3)}·10${sup(String(e).replace("-", "−"))}`;
	}
	const lmin = mdot => mdot / F.RHO_ANR * 60000;          // l/min ANR
	const nlmin = mdot => mdot / F.RHO_NORMAL * 60000;      // Nl/min
	let pAmb = 101325;
	const barg = p => (p - pAmb) / 1e5;
	const bara = p => p / 1e5;
	const pStr = p => `${fmt(barg(p), 3)} bar(g) = ${fmt(bara(p), 3)} bar(abs)`;
	const sub = s => `<sub>${s}</sub>`;
	const sup = s => `<sup>${s}</sup>`;
	const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);

	// ----------------------------------------------------------------- input
	function num(id) {
		const el = $(id);
		const v = parseFloat(el.value.replace(",", "."));
		el.classList.toggle("bad", !isFinite(v));
		return v;
	}
	function component() { return document.querySelector('input[name="component"]:checked').value; }

	function readInputs() {
		const comp = component();
		const inp = {
			comp, pa: num("p_a"), pb: num("p_b"), amb: num("p_amb"), temp: num("temp"),
			d: num("d"), cd: num("cd"), tubeD: num("tube_d"), tubeL: num("tube_l"),
			rough: num("rough"), kx: num("k_extra"), model: $("model").value,
		};
		const errs = [];
		const need = comp === "orifice" ? ["pa", "pb", "amb", "temp", "d", "cd"]
			: ["pa", "pb", "amb", "temp", "tubeD", "tubeL", "rough", "kx"];
		if (need.some(k => !isFinite(inp[k]))) errs.push("Enter a number in every field.");
		if (inp.amb <= 0) errs.push("Ambient pressure must be above 0 bar(abs).");
		if (inp.pa + inp.amb <= 0 || inp.pb + inp.amb <= 0) errs.push("Pressures must be above full vacuum (−ambient).");
		if (inp.temp <= -273) errs.push("Temperature must be above absolute zero.");
		if (comp === "orifice") {
			if (inp.d <= 0) errs.push("Orifice diameter must be above 0.");
			if (!(inp.cd > 0 && inp.cd <= 1)) errs.push("Cd must be between 0 and 1.");
		} else {
			if (inp.tubeD <= 0) errs.push("Tube diameter must be above 0.");
			if (inp.tubeL < 0) errs.push("Tube length cannot be negative.");
			if (inp.rough < 0) errs.push("Roughness cannot be negative.");
			if (inp.kx < 0) errs.push("Loss coefficient cannot be negative.");
		}
		inp.errs = errs;
		return inp;
	}

	// ---------------------------------------------------------------- solve
	function solveAll(inp) {
		pAmb = inp.amb * 1e5;
		const pA = inp.pa * 1e5 + pAmb, pB = inp.pb * 1e5 + pAmb;
		const forward = pA >= pB;
		const p0 = Math.max(pA, pB), pb = Math.min(pA, pB);
		const T0 = inp.temp + 273.15;
		let solve;
		if (inp.comp === "orifice") solve = pbx => F.orifice(p0, T0, pbx, inp.d * 1e-3, inp.cd);
		else solve = pbx => F.tube(p0, T0, pbx, inp.tubeD * 1e-3, inp.tubeL * 1e-3, inp.rough * 1e-6, inp.model, inp.kx);
		return { p0, pb, T0, forward, equal: pA === pB, res: pA === pB ? null : solve(pb), solve };
	}

	// ---------------------------------------------------------------- tiles
	function tiles(s) {
		const r = s.res;
		const dir = s.forward ? "A → B" : "B → A";
		const chokeAt = r.kind === "orifice" ? F.CRIT_RATIO * s.p0 : r.pChoke;
		const state = r.choked
			? `<div class="badge choked"><span class="dot"></span>Choked</div>
			   <div class="s">downstream ≤ ${fmt(barg(chokeAt), 2)} bar(g); lowering it adds no flow</div>`
			: `<div class="badge free"><span class="dot"></span>Not choked</div>
			   <div class="s">${chokeAt > 0 ? `chokes below ${fmt(barg(chokeAt), 2)} bar(g) downstream` : "cannot choke at this upstream pressure"}</div>`;
		const sp = r.kind === "orifice" ? r.throat : r.exit;
		$("tiles").innerHTML = `
			<div class="tile"><div class="k">Volume flow (ANR: 20 °C, 1 bar)</div><div class="v">${fmt(lmin(r.mdot), lmin(r.mdot) >= 100 ? 1 : 2)} l/min</div>
				<div class="s">${fmt(nlmin(r.mdot), 2)} Nl/min (0 °C, 1.013 bar)</div></div>
			<div class="tile"><div class="k">Mass flow</div><div class="v">${sig(r.mdot * 1000, 4)} g/s</div>
				<div class="s">direction ${dir}</div></div>
			<div class="tile"><div class="k">Flow state</div>${state}</div>
			<div class="tile"><div class="k">${r.kind === "orifice" ? "Speed in the orifice (vena contracta)" : "Speed at the tube exit"}</div>
				<div class="v">${fmt(sp.v, 0)} m/s</div>
				<div class="s">Mach ${fmt(sp.M, 3)} · local speed of sound ${fmt(sp.a, 0)} m/s</div></div>`;
	}

	// ----------------------------------------------------------- speed bars
	function speedBars(s) {
		const r = s.res;
		const rows = [];
		let ref;
		if (r.kind === "orifice") {
			rows.push({ name: "Air in the vena contracta", v: r.throat.v, color: "--series-1", note: `Mach ${fmt(r.throat.M, 3)}` });
			rows.push({ name: "Local speed of sound there", v: r.throat.a, color: "--ref", note: `at ${fmt(r.throat.T - 273.15, 1)} °C` });
			rows.push({ name: "Speed of sound upstream", v: r.a0, color: "--ref", note: `at ${fmt(r.T0 - 273.15, 1)} °C` });
			if (r.Cd < 1) rows.push({ name: "Mean over the full hole (ṁ / ρA)", v: r.vBore, color: "--series-3", note: `= Cd × speed` });
			rows.push({ name: r.choked ? "Ideal jet after full expansion" : "Jet just after the orifice", v: r.jet.v, color: "--series-2",
				note: `Mach ${fmt(r.jet.M, 2)}${r.choked ? " (supersonic, outside)" : ""}` });
			ref = r.throat.a;
			$("speed-title").textContent = "Air speed at the orifice vs. the speed of sound";
		} else {
			rows.push({ name: "Air at the tube inlet", v: r.inlet.v, color: "--series-1", note: `Mach ${fmt(r.inlet.M, 3)}` });
			rows.push({ name: "Air at the tube exit", v: r.exit.v, color: "--series-1", note: `Mach ${fmt(r.exit.M, 3)}` });
			rows.push({ name: "Local speed of sound at exit", v: r.exit.a, color: "--ref", note: `at ${fmt(r.exit.T - 273.15, 1)} °C` });
			if (r.model === "isothermal") rows.push({ name: "Isothermal choking speed", v: r.exit.vChoke, color: "--series-2", note: "Mach 1/√γ = 0.845" });
			rows.push({ name: "Speed of sound upstream", v: r.a0, color: "--ref", note: `at ${fmt(r.T0 - 273.15, 1)} °C` });
			ref = r.exit.a;
			$("speed-title").textContent = "Air speed in the tube vs. the speed of sound";
		}
		const W = Math.max(260, $("speed").clientWidth - 32);
		const narrow = W < 560; // phone: label on its own line above each bar
		const labelW = narrow ? 0 : Math.min(230, W * 0.36), valW = narrow ? Math.min(170, W * 0.5) : Math.min(230, W * 0.34);
		const rowH = narrow ? 42 : 30, barY = narrow ? 17 : 5, top = 18;
		const plotW = W - labelW - valW - (narrow ? 0 : 0);
		const vmax = Math.max(...rows.map(r => r.v), ref) * 1.08;
		const X = v => labelW + v / vmax * plotW;
		const H = top + rows.length * rowH + 8;
		let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Air speeds compared with the speed of sound">`;
		svg += `<line x1="${X(0)}" x2="${X(0)}" y1="${top - 4}" y2="${H - 4}" stroke="${css("--line")}"/>`;
		svg += `<line x1="${X(ref)}" x2="${X(ref)}" y1="${top - 6}" y2="${H - 4}" stroke="${css("--text-2")}" stroke-dasharray="4 3"/>`;
		svg += `<text x="${X(ref)}" y="${top - 8}" text-anchor="middle" font-size="11" fill="${css("--text-2")}">Mach 1 (local)</text>`;
		rows.forEach((row, i) => {
			const y = top + i * rowH;
			svg += narrow
				? `<text x="0" y="${y + 12}" font-size="12" fill="${css("--text-2")}">${esc(row.name)}</text>`
				: `<text x="${labelW - 10}" y="${y + 15}" text-anchor="end" font-size="12" fill="${css("--text-2")}">${esc(row.name)}</text>`;
			svg += `<rect x="${X(0)}" y="${y + barY}" width="${Math.max(2, X(row.v) - X(0))}" height="14" rx="3" fill="${css(row.color)}"${row.color === "--ref" ? ' fill-opacity=".55"' : ""}><title>${esc(row.name)}: ${fmt(row.v, 1)} m/s</title></rect>`;
			svg += `<text x="${X(row.v) + 6}" y="${y + barY + 11}" font-size="12" fill="${css("--text")}">${fmt(row.v, 0)} m/s <tspan fill="${css("--muted")}">${esc(row.note)}</tspan></text>`;
		});
		svg += `</svg>`;
		$("speed").innerHTML = svg;
	}

	// --------------------------------------------------------- explanation
	function explain(s) {
		const r = s.res, g = F.GAMMA;
		const ratio = r.pb / r.p0;
		let h = "";
		if (r.kind === "orifice") {
			h += `<p>The orifice is modelled as an <strong>isentropic nozzle</strong>: the air accelerates without losses from the upstream volume
				(p${sub(0)} = ${fmt(bara(r.p0), 3)} bar abs, T${sub(0)} = ${fmt(r.T0, 1)} K) into the narrowest part of the jet, the
				<em>vena contracta</em>, whose area is C${sub("d")}·A = ${fmt(r.Cd, 2)} × ${sig(r.A * 1e6, 4)} mm² = ${sig(r.Ae * 1e6, 4)} mm².
				The decisive number is the pressure ratio downstream/upstream, compared with the
				<strong>critical ratio</strong> (2/(γ+1))${sup("γ/(γ−1)")} = ${fmt(F.CRIT_RATIO, 4)} for air (γ = ${g}).</p>`;
			h += `<div class="formula">p${sub("b")} / p${sub(0)} = ${fmt(bara(r.pb), 3)} / ${fmt(bara(r.p0), 3)} = ${fmt(ratio, 4)}
				${ratio <= F.CRIT_RATIO ? "≤" : ">"} ${fmt(F.CRIT_RATIO, 4)} &nbsp;⇒&nbsp; <strong>${r.choked ? "choked" : "not choked (subsonic)"}</strong></div>`;
			if (r.choked) {
				h += `<p><strong>Choked flow.</strong> The air reaches the speed of sound in the vena contracta; pressure signals from
					downstream can no longer travel upstream, so the flow depends only on the upstream state:</p>`;
				h += `<div class="formula">ṁ = C${sub("d")} A p${sub(0)} √(γ / (R T${sub(0)})) · (2/(γ+1))${sup("(γ+1)/(2(γ−1))")}
					= C${sub("d")} A p${sub(0)} √(γ / (R T${sub(0)})) · ${fmt(F.CHOKE_FLUX, 4)}
					<br><span class="num">= ${sci(r.Ae)} m² × ${sig(r.p0, 5)} Pa × ${sig(Math.sqrt(g / (F.R * r.T0)), 4)} s/m × ${fmt(F.CHOKE_FLUX, 4)} = ${sig(r.mdot * 1000, 4)} g/s</span></div>`;
				h += `<p>The speed in the vena contracta is exactly the local speed of sound, which is lower than upstream because the air
					has cooled by expanding (T* = 2T${sub(0)}/(γ+1) = ${fmt(r.throat.T - 273.15, 1)} °C):</p>`;
				h += `<div class="formula">v* = a* = √(2γ R T${sub(0)} / (γ+1)) = ${fmt(r.throat.v, 1)} m/s
					&nbsp;&nbsp;<span class="num">(upstream speed of sound √(γRT${sub(0)}) = ${fmt(r.a0, 1)} m/s)</span></div>`;
				h += `<p>The pressure in the vena contracta stays at ${fmt(F.CRIT_RATIO, 3)} × p${sub(0)} = ${fmt(bara(r.throat.p), 3)} bar abs.
					Beyond the orifice the jet keeps expanding to the downstream pressure and becomes supersonic (ideally Mach
					${fmt(r.jet.M, 2)}, ${fmt(r.jet.v, 0)} m/s), with shock cells that dissipate that energy. Flow only grows with the
					upstream pressure (linearly with p${sub(0)}), never with a lower downstream pressure.</p>`;
			} else {
				h += `<p><strong>Subsonic flow.</strong> The vena contracta is at the downstream pressure, and the mass flow follows from
					the isentropic nozzle equation (Saint-Venant–Wantzel):</p>`;
				h += `<div class="formula">ṁ = C${sub("d")} A p${sub(0)} √( 2γ / ((γ−1) R T${sub(0)}) · [ (p${sub("b")}/p${sub(0)})${sup("2/γ")} − (p${sub("b")}/p${sub(0)})${sup("(γ+1)/γ")} ] )
					<br><span class="num">= ${sci(r.Ae)} m² × ${sig(r.p0, 5)} Pa × √(${sci(2 * g / ((g - 1) * F.R * r.T0), 4)} × [${fmt(Math.pow(ratio, 2 / g), 4)} − ${fmt(Math.pow(ratio, (g + 1) / g), 4)}]) = ${sig(r.mdot * 1000, 4)} g/s</span></div>`;
				h += `<p>The speed in the vena contracta comes from the energy equation (enthalpy turned into kinetic energy):</p>`;
				h += `<div class="formula">v = √( 2 c${sub("p")} T${sub(0)} [ 1 − (p${sub("b")}/p${sub(0)})${sup("(γ−1)/γ")} ] ) = ${fmt(r.throat.v, 1)} m/s
					&nbsp;=&nbsp; Mach ${fmt(r.throat.M, 3)} &nbsp;<span class="num">(local speed of sound ${fmt(r.throat.a, 1)} m/s)</span></div>`;
				h += `<p>Lowering the downstream pressure increases the flow until p${sub("b")} = ${fmt(F.CRIT_RATIO, 3)} p${sub(0)}
					= ${fmt(barg(F.CRIT_RATIO * r.p0), 3)} bar(g); below that the flow is choked.</p>`;
			}
			h += `<p>In ISO 6358 terms this orifice has a sonic conductance C = ${sig(r.C * 1e8, 3)} dm³/(s·bar) and critical pressure ratio
				b = ${fmt(F.CRIT_RATIO, 3)} (an ideal nozzle; real components usually have a lower b).</p>`;
		} else {
			const fanno = r.model === "adiabatic";
			h += `<p>The tube is modelled in three steps. <strong>1. Entrance:</strong> the air accelerates isentropically from the upstream
				volume (p${sub(0)} = ${fmt(bara(r.p0), 3)} bar abs) to the inlet Mach number M${sub(1)}:</p>`;
			h += `<div class="formula">p${sub(1)} = p${sub(0)} (1 + (γ−1)/2 · M${sub(1)}${sup(2)})${sup("−γ/(γ−1)")} = ${fmt(bara(r.inlet.p), 4)} bar abs
				&nbsp;<span class="num">(M${sub(1)} = ${fmt(r.inlet.M, 4)}, v${sub(1)} = ${fmt(r.inlet.v, 1)} m/s)</span></div>`;
			h += `<p><strong>2. Wall friction:</strong> the Reynolds number is the same all along the tube (ṁ and D are constant), and the
				Darcy friction factor follows from Churchill's equation, which covers laminar (64/Re), transitional and turbulent flow
				(roughness ε/D = ${sig(r.roughness / r.D, 3)}):</p>`;
			h += `<div class="formula">Re = 4ṁ / (π D μ) = ${fmt(r.Re, 0)} (${r.regime}) &nbsp;⇒&nbsp; f = ${fmt(r.f, 4)},
				&nbsp; K = f L/D${r.Kextra ? " + K" + sub("extra") : ""} = ${fmt(r.f, 4)} × ${fmt(r.L / r.D, 1)}${r.Kextra ? " + " + fmt(r.Kextra, 2) : ""} = ${fmt(r.K, 3)}</div>`;
			if (fanno) {
				h += `<p><strong>3. Compressible flow with friction (Fanno flow, adiabatic):</strong> friction makes the subsonic air
					<em>accelerate</em> along the tube while pressure and density drop. The friction length still available before
					the flow reaches Mach 1 is F(M), so</p>`;
				h += `<div class="formula">K = F(M${sub(1)}) − F(M${sub(2)}), &nbsp; F(M) = (1 − M${sup(2)}) / (γM${sup(2)}) + (γ+1)/(2γ) · ln[ (γ+1)M${sup(2)} / (2 + (γ−1)M${sup(2)}) ]
					<br>p${sub(2)}/p${sub(1)} = (M${sub(1)}/M${sub(2)}) · √[ (1 + (γ−1)/2·M${sub(1)}${sup(2)}) / (1 + (γ−1)/2·M${sub(2)}${sup(2)}) ]
					<br><span class="num">F(M${sub(1)}) = ${fmt(F.TUBE_MODELS.adiabatic.F(r.inlet.M), 3)} → M${sub(2)} = ${fmt(r.exit.M, 4)}, exit pressure ${fmt(bara(r.exit.p), 4)} bar abs</span></div>`;
			} else {
				h += `<p><strong>3. Compressible flow with friction (isothermal):</strong> heat exchange with the wall keeps the
					temperature constant; the air still accelerates as the pressure drops. Integrating the momentum equation gives</p>`;
				h += `<div class="formula">p${sub(1)}${sup(2)} − p${sub(2)}${sup(2)} = (ṁ/A)${sup(2)} R T · [ f L/D + 2 ln(p${sub(1)}/p${sub(2)}) ],
					&nbsp; v ∝ 1/p
					<br><span class="num">exit Mach ${fmt(r.exit.M, 4)}, exit pressure ${fmt(bara(r.exit.p), 4)} bar abs</span></div>`;
			}
			h += `<p>M${sub(1)} is solved so that the exit pressure equals the downstream pressure. ${r.choked
				? `<strong>Here that is impossible:</strong> even at the largest possible inlet Mach the air already reaches the
					choking limit (${fanno ? "Mach 1" : "Mach 1/√γ = 0.845"}) at the tube end, with an exit pressure of
					${pStr(r.pChoke)}. The flow is <strong>choked</strong>: the downstream pressure (${pStr(r.pb)}) is lower than the
					exit pressure, the remaining expansion happens in the jet outside the tube, and a lower downstream pressure
					gives no more flow.`
				: `The exit speed stays below the choking limit (${fanno ? "Mach 1" : "Mach 1/√γ = 0.845"}), so the flow is
					<strong>not choked</strong>; it would choke for a downstream pressure below ${pStr(r.pChoke)}.`}</p>`;
			h += `<p>Cross-check: slow laminar isothermal flow (compressible Hagen–Poiseuille) would give
				ṁ = π D${sup(4)} (p${sub(0)}${sup(2)} − p${sub("b")}${sup(2)}) / (256 μ L R T) = ${sig(lmin(r.mdotHP), 3)} l/min ANR —
				${r.Re < 2000 && r.exit.M < 0.3 ? "close to the full result, as expected in this laminar, low-speed case." :
					"not valid here (" + (r.Re >= 2000 ? "turbulent" : "") + (r.Re >= 2000 && r.exit.M >= 0.3 ? ", " : "") + (r.exit.M >= 0.3 ? "fast, compressible" : "") + " flow)."}</p>`;
		}
		$("explain").innerHTML = h;
	}

	// --------------------------------------------------------------- charts
	function niceTicks(min, max, n) {
		const span = max - min || 1;
		const step0 = span / (n || 5);
		const mag = Math.pow(10, Math.floor(Math.log10(step0)));
		const e = step0 / mag;
		const step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
		const ticks = [];
		for (let v = Math.ceil(min / step - 1e-9) * step; v <= max + step * 1e-9; v += step) ticks.push(+v.toFixed(10));
		return { ticks, step };
	}

	// opts: {title, xLabel, yLabel, xs, series:[{name, color, dash, ys, unit}], xFmt, yFmt,
	//        shade:{x0, x1, label}, marker:{x, y}, hline:{y, label}}
	function lineChart(opts) {
		const box = document.createElement("div");
		box.className = "card chart";
		box.innerHTML = `<div class="chart-title">${opts.title}</div>`;
		if (opts.series.length > 1) {
			box.innerHTML += `<div class="legend">${opts.series.map(sr =>
				`<span><svg width="22" height="8"><line x1="1" x2="21" y1="4" y2="4" stroke="${css(sr.color)}" stroke-width="2.5" ${sr.dash ? 'stroke-dasharray="4 3"' : ""} stroke-linecap="round"/></svg>${esc(sr.name)}</span>`).join("")}</div>`;
		}
		const plot = document.createElement("div");
		plot.style.position = "relative";
		box.appendChild(plot);
		$("charts").appendChild(box);
		pendingCharts.push(() => drawChart(opts, plot));
	}
	let pendingCharts = [];

	function drawChart(opts, plot) {
		const W = Math.max(280, plot.clientWidth), H = 230;
		const m = { l: 52, r: 14, t: 10, b: 40 };
		const xs = opts.xs;
		const xMin = Math.min(...xs), xMax = Math.max(...xs);
		const all = opts.series.flatMap(sr => sr.ys.filter(isFinite));
		let yMin = Math.min(0, ...all), yMax = Math.max(...all);
		if (opts.hline) { yMin = Math.min(yMin, opts.hline.y); yMax = Math.max(yMax, opts.hline.y); }
		const yt = niceTicks(yMin, yMax * 1.04 + 1e-12, 5);
		yMin = Math.min(yMin, yt.ticks[0]);
		yMax = Math.max(yt.ticks[yt.ticks.length - 1], yMax * 1.08);
		const xt = niceTicks(xMin, xMax, 6);
		const X = x => m.l + (x - xMin) / (xMax - xMin || 1) * (W - m.l - m.r);
		const Y = y => m.t + (1 - (y - yMin) / (yMax - yMin || 1)) * (H - m.t - m.b);
		const grid = css("--line"), mut = css("--muted");
		let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(opts.title)}">`;
		if (opts.shade && opts.shade.x1 > opts.shade.x0) {
			const x0 = X(Math.max(xMin, opts.shade.x0)), x1 = X(Math.min(xMax, opts.shade.x1));
			svg += `<rect x="${x0}" y="${m.t}" width="${x1 - x0}" height="${H - m.t - m.b}" fill="${css("--choked")}" fill-opacity=".10"/>`;
			svg += `<text x="${x0 + 6}" y="${m.t + 14}" font-size="11" fill="${css("--text-2")}">${esc(opts.shade.label)}</text>`;
		}
		yt.ticks.forEach(t => {
			svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="${grid}" stroke-width="${t === 0 ? 1 : 0.6}"/>`;
			svg += `<text x="${m.l - 6}" y="${Y(t) + 4}" text-anchor="end" font-size="11" fill="${mut}">${opts.yFmt(t)}</text>`;
		});
		xt.ticks.forEach(t => {
			if (t < xMin - 1e-9 || t > xMax + 1e-9) return;
			svg += `<line x1="${X(t)}" x2="${X(t)}" y1="${H - m.b}" y2="${H - m.b + 4}" stroke="${mut}"/>`;
			svg += `<text x="${X(t)}" y="${H - m.b + 16}" text-anchor="middle" font-size="11" fill="${mut}">${opts.xFmt(t)}</text>`;
		});
		svg += `<text x="${(m.l + W - m.r) / 2}" y="${H - 6}" text-anchor="middle" font-size="12" fill="${css("--text-2")}">${esc(opts.xLabel)}</text>`;
		svg += `<text x="12" y="${(m.t + H - m.b) / 2}" text-anchor="middle" font-size="12" fill="${css("--text-2")}" transform="rotate(-90 12 ${(m.t + H - m.b) / 2})">${esc(opts.yLabel)}</text>`;
		if (opts.hline) {
			svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(opts.hline.y)}" y2="${Y(opts.hline.y)}" stroke="${css("--text-2")}" stroke-dasharray="2 3"/>`;
			svg += `<text x="${W - m.r - 4}" y="${Y(opts.hline.y) - 5}" text-anchor="end" font-size="11" fill="${css("--text-2")}">${esc(opts.hline.label)}</text>`;
		}
		opts.series.slice().reverse().forEach(sr => { // first series on top
			const d = xs.map((x, i) => isFinite(sr.ys[i]) ? `${X(x).toFixed(1)},${Y(sr.ys[i]).toFixed(1)}` : null).filter(Boolean);
			svg += `<polyline points="${d.join(" ")}" fill="none" stroke="${css(sr.color)}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" ${sr.dash ? 'stroke-dasharray="5 4"' : ""}/>`;
		});
		if (opts.marker) {
			svg += `<circle cx="${X(opts.marker.x)}" cy="${Y(opts.marker.y)}" r="5" fill="${css(opts.series[0].color)}" stroke="${css("--panel")}" stroke-width="2"/>`;
		}
		svg += `<g class="hover" visibility="hidden"><line class="cross" y1="${m.t}" y2="${H - m.b}" stroke="${css("--text-2")}" stroke-width="1"/>
			${opts.series.map(sr => `<circle r="4" fill="${css(sr.color)}" stroke="${css("--panel")}" stroke-width="2"/>`).join("")}</g>`;
		svg += `<rect class="hit" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/></svg>`;
		plot.innerHTML = svg;
		const tip = document.createElement("div");
		tip.className = "tip";
		tip.hidden = true;
		plot.appendChild(tip);

		const svgEl = plot.querySelector("svg"), hover = svgEl.querySelector(".hover");
		const cross = hover.querySelector(".cross"), dots = hover.querySelectorAll("circle");
		function move(ev) {
			const rect = svgEl.getBoundingClientRect();
			const px = (ev.clientX - rect.left) * W / rect.width;
			let best = 0;
			xs.forEach((x, i) => { if (Math.abs(X(x) - px) < Math.abs(X(xs[best]) - px)) best = i; });
			const cx = X(xs[best]);
			cross.setAttribute("x1", cx); cross.setAttribute("x2", cx);
			opts.series.forEach((sr, k) => {
				const y = sr.ys[best];
				dots[k].setAttribute("cx", cx); dots[k].setAttribute("cy", isFinite(y) ? Y(y) : -99);
			});
			hover.setAttribute("visibility", "visible");
			tip.innerHTML = `<div style="color:${css("--muted")}">${esc(opts.xLabel)}: ${opts.xFmt(xs[best], true)}</div>` +
				opts.series.map(sr => `<div><span class="sw" style="background:${css(sr.color)}"></span>${esc(sr.name)}: <b>${isFinite(sr.ys[best]) ? opts.yFmt(sr.ys[best], true) : "–"}</b></div>`).join("") +
				(opts.extra ? opts.extra(best) : "");
			tip.hidden = false;
			const sx = cx * rect.width / W;
			const tw = tip.offsetWidth;
			tip.style.left = Math.max(0, sx + 14 + tw > rect.width ? sx - 14 - tw : sx + 14) + "px";
			tip.style.top = "8px";
		}
		const hit = svgEl.querySelector(".hit");
		hit.addEventListener("pointermove", move);
		hit.addEventListener("pointerdown", move);
		hit.addEventListener("pointerleave", () => { hover.setAttribute("visibility", "hidden"); tip.hidden = true; });
	}

	function charts(s) {
		$("charts").innerHTML = "";
		pendingCharts = [];
		const r = s.res;
		const curve = F.flowCurve(s.solve, s.p0, r.kind === "orifice" ? 120 : 48);
		const xs = curve.map(c => barg(c.pb));
		const flows = curve.map(c => c.res ? lmin(c.res.mdot) : 0);
		const chokeAt = r.kind === "orifice" ? F.CRIT_RATIO * s.p0 : r.pChoke;
		const shade = chokeAt > 0 ? { x0: barg(0), x1: barg(chokeAt), label: "choked" } : null;
		const pFmt = (v, long) => long ? `${fmt(v, 3)} bar(g)` : fmt(v, Math.abs(v) >= 10 ? 0 : 1);
		const fFmt = (v, long) => long ? `${fmt(v, v >= 100 ? 1 : 2)} l/min` : sig(v, 3);
		const vFmt = (v, long) => long ? `${fmt(v, 0)} m/s` : fmt(v, 0);
		lineChart({
			title: "Flow vs. downstream pressure (upstream fixed)", xLabel: "Downstream pressure (bar g)", yLabel: "Flow (l/min ANR)",
			xs, series: [{ name: "Flow", color: "--series-1", ys: flows }], xFmt: pFmt, yFmt: fFmt, shade,
			marker: { x: barg(s.pb), y: lmin(r.mdot) },
		});
		if (r.kind === "orifice") {
			lineChart({
				title: "Speeds vs. downstream pressure", xLabel: "Downstream pressure (bar g)", yLabel: "Speed (m/s)", xs,
				series: [
					{ name: "Vena contracta", color: "--series-1", ys: curve.map(c => c.res ? c.res.throat.v : 0) },
					{ name: "Local speed of sound", color: "--ref", dash: true, ys: curve.map(c => c.res ? c.res.throat.a : F.soundSpeed(s.T0)) },
					{ name: "Ideal expanded jet", color: "--series-2", ys: curve.map(c => c.res ? c.res.jet.v : 0) },
				],
				xFmt: pFmt, yFmt: vFmt, shade,
			});
		} else {
			const prof = r.profile;
			const useM = r.L >= 2;
			const px = prof.map(p => useM ? p.x : p.x * 1000);
			const xLab = `Position along the tube (${useM ? "m" : "mm"})`;
			const xF = (v, long) => long ? `${fmt(v, useM ? 2 : 0)} ${useM ? "m" : "mm"}` : sig(v, 3);
			const ser = [
				{ name: "Air speed", color: "--series-1", ys: prof.map(p => p.v) },
				{ name: "Local speed of sound", color: "--ref", dash: true, ys: prof.map(p => p.a) },
			];
			if (r.model === "isothermal") ser.push({ name: "Choking speed (Mach 0.845)", color: "--series-2", dash: true, ys: prof.map(p => p.vChoke) });
			lineChart({
				title: "Speed along the tube", xLabel: xLab, yLabel: "Speed (m/s)", xs: px, series: ser, xFmt: xF, yFmt: vFmt,
				extra: i => `<div style="color:${css("--muted")}">Mach ${fmt(prof[i].M, 3)}, ${fmt(prof[i].T - 273.15, 1)} °C</div>`,
			});
			lineChart({
				title: "Pressure along the tube", xLabel: xLab, yLabel: "Pressure (bar g)", xs: px,
				series: [{ name: "Static pressure", color: "--series-1", ys: prof.map(p => barg(p.p)) }],
				xFmt: xF, yFmt: pFmt, hline: { y: barg(s.pb), label: "downstream" },
			});
		}
		pendingCharts.forEach(draw => draw());
	}

	// -------------------------------------------------------------- details
	function details(s) {
		const r = s.res;
		const rows = [];
		rows.push(["Upstream (stagnation) pressure", pStr(r.p0)], ["Downstream pressure", pStr(r.pb)],
			["Pressure ratio downstream/upstream", fmt(r.pb / r.p0, 4)], ["Upstream temperature", `${fmt(r.T0 - 273.15, 1)} °C`]);
		if (r.kind === "orifice") {
			rows.push(["Hole area A / effective area Cd·A", `${sig(r.A * 1e6, 4)} / ${sig(r.Ae * 1e6, 4)} mm²`],
				["Vena contracta pressure", pStr(r.throat.p)],
				["Vena contracta temperature", `${fmt(r.throat.T - 273.15, 1)} °C`],
				["Vena contracta density", `${fmt(r.throat.rho, 3)} kg/m³`],
				["Vena contracta speed / Mach", `${fmt(r.throat.v, 1)} m/s / ${fmt(r.throat.M, 4)}`],
				["Reynolds number (vena contracta)", fmt(r.Re, 0)],
				["Sonic conductance C (ISO 6358)", `${sig(r.C * 1e8, 4)} dm³/(s·bar)`]);
		} else {
			rows.push(["Model", r.modelLabel], ["Cross-section", `${sig(r.A * 1e6, 4)} mm²`],
				["Reynolds number / regime", `${fmt(r.Re, 0)} / ${r.regime}`], ["Darcy friction factor f", fmt(r.f, 5)],
				["Total loss K = f·L/D (+ extra)", fmt(r.K, 3)],
				["Inlet pressure / speed / Mach", `${fmt(bara(r.inlet.p), 4)} bar abs / ${fmt(r.inlet.v, 1)} m/s / ${fmt(r.inlet.M, 4)}`],
				["Exit pressure / speed / Mach", `${fmt(bara(r.exit.p), 4)} bar abs / ${fmt(r.exit.v, 1)} m/s / ${fmt(r.exit.M, 4)}`],
				["Exit temperature", `${fmt(r.exit.T - 273.15, 1)} °C`],
				["Exit pressure at the onset of choking", pStr(r.pChoke)],
				["Pressure drop inside the tube", `${fmt((r.p0 - r.exit.p) / 1e5, 4)} bar`],
				["Hagen–Poiseuille estimate", `${sig(lmin(r.mdotHP), 4)} l/min ANR`]);
		}
		rows.push(["Mass flow", `${sig(r.mdot * 1000, 5)} g/s`], ["Volume flow ANR / normal", `${fmt(lmin(r.mdot), 2)} l/min / ${fmt(nlmin(r.mdot), 2)} Nl/min`],
			["Actual volume flow at upstream pressure", `${fmt(r.mdot / (r.p0 / (F.R * r.T0)) * 60000, 3)} l/min`]);
		$("details").innerHTML = rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
	}

	function notes(s) {
		const common = `<li>Dry air as an ideal gas, γ = 1.4, R = 287.05 J/(kg·K); viscosity from Sutherland's law.</li>
			<li>Steady flow from an upstream volume where the air is at rest into a downstream volume; the kinetic energy of the outgoing jet is lost there.</li>
			<li>ANR flow = mass flow / density at 20 °C, 100 kPa (ISO 8778); Nl/min at 0 °C, 101.325 kPa.</li>`;
		const specific = s.res.kind === "orifice"
			? `<li>The discharge coefficient Cd is constant. Real sharp-edged orifices let somewhat more air through than the ideal choked value when the pressure ratio is far below 0.528, because their vena contracta widens; Cd then rises towards ~0.85.</li>
			   <li>The orifice is short: no friction along the bore. A long, narrow bore behaves like a tube; use the Tube model for it.</li>`
			: `<li>The friction factor is taken at the inlet temperature and kept constant along the tube (in Fanno flow the temperature drops a little towards the exit).</li>
			   <li>The tube entrance is smooth (no vena contracta); use the extra loss coefficient K for a sharp entrance, fittings and bends.</li>
			   <li>A tube of zero length gives the same flow as an ideal orifice (Cd = 1) of the same diameter in the adiabatic model.</li>`;
		$("notes").innerHTML = `<ul style="margin:0;padding-left:18px">${common}${specific}
			<li>Planned: tubes and orifices in series. The solvers already work as "inlet state + mass flow → outlet state", so a chain can be solved by searching the mass flow for which the last element meets the downstream pressure.</li></ul>`;
	}

	// ------------------------------------------------------------- update
	let lastInp = null;
	function update() {
		const inp = readInputs();
		$("orifice-controls").hidden = inp.comp !== "orifice";
		$("tube-controls").hidden = inp.comp !== "tube";
		saveUrl();
		if (inp.errs.length) {
			$("error").textContent = inp.errs.join(" ");
			$("error").hidden = false;
			$("out").style.opacity = .35;
			return;
		}
		$("error").hidden = true;
		const s = solveAll(inp);
		if (s.equal) {
			$("error").textContent = "Both sides have the same pressure: no flow.";
			$("error").hidden = false;
			$("out").style.opacity = .35;
			return;
		}
		$("out").style.opacity = 1;
		lastInp = s;
		tiles(s); speedBars(s); explain(s); charts(s); details(s); notes(s);
	}

	// Remember the inputs in the URL, so a result can be shared or bookmarked.
	function saveUrl() {
		const q = new URLSearchParams();
		q.set("c", component());
		FIELDS.forEach(f => q.set(f, $(f).value));
		SELECTS.forEach(f => q.set(f, $(f).value));
		history.replaceState(null, "", "?" + q.toString());
	}
	function loadUrl() {
		const q = new URLSearchParams(location.search);
		const c = q.get("c");
		if (c === "orifice" || c === "tube") document.querySelector(`input[name="component"][value="${c}"]`).checked = true;
		FIELDS.forEach(f => { if (q.has(f)) $(f).value = q.get(f); });
		SELECTS.forEach(f => {
			const v = q.get(f);
			if (v != null && [...$(f).options].some(o => o.value === v)) $(f).value = v;
		});
	}

	// Presets fill the number field; editing the field switches the preset to Custom.
	function linkPreset(selectId, fieldId) {
		$(selectId).addEventListener("change", () => {
			if ($(selectId).value !== "custom") $(fieldId).value = $(selectId).value;
			update();
		});
		$(fieldId).addEventListener("input", () => {
			const v = parseFloat($(fieldId).value);
			const match = [...$(selectId).options].find(o => o.value !== "custom" && parseFloat(o.value) === v);
			$(selectId).value = match ? match.value : "custom";
		});
	}

	let timer = null;
	const later = () => { clearTimeout(timer); timer = setTimeout(update, 120); };
	loadUrl();
	linkPreset("cd_preset", "cd");
	linkPreset("tube_preset", "tube_d");
	FIELDS.forEach(f => $(f).addEventListener("input", later));
	$("model").addEventListener("change", update);
	document.querySelectorAll('input[name="component"]').forEach(el => el.addEventListener("change", update));
	let lastW = 0;
	window.addEventListener("resize", () => {
		const w = document.querySelector(".results").clientWidth;
		if (w !== lastW && lastInp) { lastW = w; later(); }
	});
	update();
})();
