// Steady compressible air flow through pneumatic components (orifice, tube).
// Pure functions, no DOM: used by pneumatic-flow.js and testable on its own.
//
// Conventions: SI units throughout (Pa absolute, K, m, kg/s, m/s). Every
// component is fed from an upstream volume at rest (stagnation pressure p0,
// temperature T0) and discharges into a downstream volume at pressure pb
// (pb < p0). The downstream kinetic energy is lost in that volume.
//
// Series connection (future): each solver is written as "given the inlet
// state and the mass flow, what comes out"; a chain can be solved by shooting
// on the mass flow until the last outlet matches the back pressure, with
// choking = the largest mass flow that every element can still pass.
(function (root) {
	"use strict";

	const GAMMA = 1.4;            // ratio of specific heats, air
	const R = 287.05;             // specific gas constant, air, J/(kg K)
	const CP = GAMMA * R / (GAMMA - 1);
	const GM = (GAMMA - 1) / 2;   // 0.2
	const EXP = GAMMA / (GAMMA - 1); // 3.5
	const CRIT_RATIO = Math.pow(2 / (GAMMA + 1), EXP); // 0.5283
	// mdot_choked = A p0 sqrt(g/(R T0)) * CHOKE_FLUX
	const CHOKE_FLUX = Math.pow(2 / (GAMMA + 1), (GAMMA + 1) / (2 * (GAMMA - 1))); // 0.5787
	const RHO_ANR = 100000 / (R * 293.15);    // ISO 8778 ANR: 20 C, 100 kPa (dry)
	const RHO_NORMAL = 101325 / (R * 273.15); // DIN 1343 normal: 0 C, 1.01325 bar

	// Dynamic viscosity of air, Sutherland's law (Pa s).
	function viscosity(T) {
		return 1.716e-5 * Math.pow(T / 273.15, 1.5) * (273.15 + 110.4) / (T + 110.4);
	}
	function soundSpeed(T) { return Math.sqrt(GAMMA * R * T); }
	// Isentropic static/stagnation pressure ratio at Mach M.
	function isenPressureRatio(M) { return Math.pow(1 + GM * M * M, -EXP); }
	// Subsonic isentropic Mach for a static/stagnation pressure ratio r.
	function machFromPressureRatio(r) {
		return Math.sqrt(Math.max(0, (Math.pow(r, -1 / EXP) - 1) / GM));
	}

	// Darcy friction factor, Churchill (1977): one continuous formula for
	// laminar (64/Re), transitional and turbulent (Colebrook-like) flow.
	function churchill(Re, relRough) {
		Re = Math.max(Re, 1e-9);
		const A = Math.pow(2.457 * Math.log(1 / (Math.pow(7 / Re, 0.9) + 0.27 * relRough)), 16);
		const B = Math.pow(37530 / Re, 16);
		return 8 * Math.pow(Math.pow(8 / Re, 12) + Math.pow(A + B, -1.5), 1 / 12);
	}
	function flowRegime(Re) {
		return Re < 2300 ? "laminar" : Re < 4000 ? "transitional" : "turbulent";
	}

	// Root of a continuous fn with fn(lo), fn(hi) of opposite sign.
	function bisect(fn, lo, hi, geometric, iters) {
		const flo = fn(lo);
		for (let i = 0; i < (iters || 100); i++) {
			const mid = geometric ? Math.sqrt(lo * hi) : 0.5 * (lo + hi);
			const fm = fn(mid);
			if ((fm > 0) === (flo > 0)) lo = mid; else hi = mid;
		}
		return 0.5 * (lo + hi);
	}

	// ---------------------------------------------------------------- orifice
	// Isentropic nozzle flow through the vena contracta (area Cd * A).
	// Choked when pb/p0 <= (2/(g+1))^(g/(g-1)) = 0.528: the throat is then at
	// Mach 1 and the flow no longer depends on pb.
	function orifice(p0, T0, pb, d, Cd) {
		const A = Math.PI * d * d / 4;
		const Ae = Cd * A;
		const r = pb / p0;
		const choked = r <= CRIT_RATIO;
		const rt = Math.max(r, CRIT_RATIO);        // throat/upstream pressure ratio
		const Mt = machFromPressureRatio(rt);
		const Tt = T0 / (1 + GM * Mt * Mt);
		const at = soundSpeed(Tt);
		const vt = Mt * at;
		const pt = rt * p0;
		const rhot = pt / (R * Tt);
		const mdot = Ae * rhot * vt;
		// Ideal jet after expanding (isentropically) all the way to pb:
		// supersonic when choked (in reality shock cells, losses).
		const Mj = machFromPressureRatio(r);
		const Tj = T0 / (1 + GM * Mj * Mj);
		const aj = soundSpeed(Tj);
		const de = Math.sqrt(4 * Ae / Math.PI);    // vena contracta diameter
		const Re = rhot * vt * de / viscosity(Tt);
		return {
			kind: "orifice", p0, T0, pb, d, Cd, A, Ae, r, choked, critRatio: CRIT_RATIO,
			mdot, throat: { p: pt, T: Tt, rho: rhot, M: Mt, v: vt, a: at },
			a0: soundSpeed(T0), jet: { M: Mj, v: Mj * aj, T: Tj, a: aj },
			vBore: mdot / (rhot * A), Re,
			// Sonic conductance (ISO 6358), m3/(s Pa):
			// mdot_choked = C * p0 * rho_ANR * sqrt(293.15 / T0)
			C: Ae * CHOKE_FLUX / RHO_ANR * Math.sqrt(GAMMA / (R * 293.15)),
		};
	}

	// ------------------------------------------------------------------- tube
	// Isentropic entrance from the upstream volume to Mach M1, then 1D
	// compressible flow with wall friction (Darcy f, constant along the tube):
	//   adiabatic  = Fanno flow, chokes at exit Mach 1
	//   isothermal = isothermal flow with friction, chokes at exit Mach 1/sqrt(g)
	// F(M) is the friction length f L*/D still available before choking.
	const TUBE_MODELS = {
		adiabatic: {
			label: "Adiabatic (Fanno)",
			Mc: 1,
			F(M) {
				const M2 = M * M;
				return (1 - M2) / (GAMMA * M2) +
					(GAMMA + 1) / (2 * GAMMA) * Math.log((GAMMA + 1) * M2 / (2 + (GAMMA - 1) * M2));
			},
			pRatio(M1, M2) { // p2/p1
				return M1 * Math.sqrt(1 + GM * M1 * M1) / (M2 * Math.sqrt(1 + GM * M2 * M2));
			},
			T(T0, T1, M) { return T0 / (1 + GM * M * M); },
		},
		isothermal: {
			label: "Isothermal",
			Mc: 1 / Math.sqrt(GAMMA),
			F(M) { const g = GAMMA * M * M; return (1 - g) / g + Math.log(g); },
			pRatio(M1, M2) { return M1 / M2; },
			T(T0, T1) { return T1; },
		},
	};

	function tube(p0, T0, pb, D, L, roughness, modelName, Kextra) {
		const m = TUBE_MODELS[modelName] || TUBE_MODELS.adiabatic;
		const A = Math.PI * D * D / 4;
		const rr = roughness / D;
		const Kx = Kextra || 0;
		const M_MIN = 1e-9;

		function inlet(M1) {
			const T1 = T0 / (1 + GM * M1 * M1);
			const p1 = p0 * isenPressureRatio(M1);
			const G = p1 * M1 * Math.sqrt(GAMMA / (R * T1)); // mass flux kg/(m2 s)
			const Re = G * D / viscosity(T1);
			const f = churchill(Re, rr);
			return { M1, T1, p1, G, Re, f, K: f * L / D + Kx };
		}
		// Mach where the remaining friction length is Frem (Frem <= 0: choked).
		function machAt(M1, Frem) {
			if (Frem <= 0) return m.Mc;
			if (Frem >= m.F(M1)) return M1;
			return bisect(M => m.F(M) - Frem, M1, m.Mc, false, 80);
		}
		function exitPressure(M1) {
			const s = inlet(M1);
			return s.p1 * m.pRatio(M1, machAt(M1, m.F(M1) - s.K));
		}

		// Largest inlet Mach the tube can take: friction length = K exactly.
		const M1max = bisect(M1 => m.F(M1) - inlet(M1).K, M_MIN, m.Mc, true, 100);
		const pChoke = exitPressure(M1max);
		const choked = pb <= pChoke;
		const M1 = choked ? M1max : bisect(M => exitPressure(M) - pb, M_MIN, M1max, true, 100);
		const s = inlet(M1);
		const Fin = m.F(M1);
		const M2 = machAt(M1, Fin - s.K);
		const p2 = s.p1 * m.pRatio(M1, M2);
		const T2 = m.T(T0, s.T1, M2);
		const mdot = s.G * A;

		function state(x) {
			const frac = L > 0 ? x / L : 1;
			const M = machAt(M1, Fin - frac * s.K);
			const T = m.T(T0, s.T1, M);
			const a = soundSpeed(T);
			return { x, M, p: s.p1 * m.pRatio(M1, M), T, a, v: M * a, vChoke: m.Mc * a };
		}
		const profile = [];
		const N = 160;
		for (let i = 0; i <= N; i++) {
			// denser towards the exit, where a choked flow changes fastest
			const u = i / N;
			profile.push(state(L * (1 - Math.pow(1 - u, 3))));
		}

		// Cross-check: low-speed laminar, isothermal (compressible Hagen-Poiseuille)
		const mdotHP = Math.PI * Math.pow(D, 4) * (p0 * p0 - pb * pb) /
			(256 * viscosity(T0) * Math.max(L, 1e-12) * R * T0);

		const a2 = soundSpeed(T2);
		return {
			kind: "tube", model: modelName, modelLabel: m.label, Mc: m.Mc,
			p0, T0, pb, D, L, roughness, Kextra: Kx, A, choked, pChoke,
			mdot, Re: s.Re, f: s.f, K: s.K, regime: flowRegime(s.Re),
			inlet: { M: M1, p: s.p1, T: s.T1, v: M1 * soundSpeed(s.T1), a: soundSpeed(s.T1) },
			exit: { M: M2, p: p2, T: T2, v: M2 * a2, a: a2, vChoke: m.Mc * a2 },
			a0: soundSpeed(T0), mdotHP, profile,
		};
	}

	// Mass flow against back pressure (from vacuum up to p0), for flow curves.
	function flowCurve(solve, p0, n) {
		const pts = [];
		for (let i = 0; i <= n; i++) {
			const pb = p0 * (i / n);
			pts.push(pb >= p0 ? { pb, res: null } : { pb, res: solve(Math.max(pb, p0 * 1e-4)) });
		}
		return pts;
	}

	root.PneuFlow = {
		GAMMA, R, CP, CRIT_RATIO, CHOKE_FLUX, RHO_ANR, RHO_NORMAL, TUBE_MODELS,
		viscosity, soundSpeed, churchill, flowRegime, orifice, tube, flowCurve,
	};
})(typeof window !== "undefined" ? window : globalThis);
