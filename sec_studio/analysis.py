"""Analysis helpers for SEC runs.

* signal maths      : Savitzky-Golay smoothing + 1st/2nd derivatives
* peak integration  : prominence based peak picking, valley-to-valley areas
* protein sequence  : MW (avg/mono), pI, epsilon280 / A280(0.1%), GRAVY
* SEC molar mass    : Kav vs log10(MW) calibration from standards
* cofactor ratio    : stoichiometry from A280 + cofactor peak areas (e.g. FMN)

Everything is pure numpy so the app keeps only its existing dependencies.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

_trapz = getattr(np, "trapezoid", None) or np.trapz  # numpy>=2 renamed trapz

__all__ = [
    "savgol", "savgol_coeffs", "derivative",
    "find_peaks", "integrate_peaks",
    "analyze_sequence", "calibrate_sec", "cofactor_ratio",
    "DEFAULT_SCREEN", "screen_run", "screen_runs",
]

# --------------------------------------------------------------------------- #
# Fixed-rule "design screen" metric (monomer-peak FMN loading)
# --------------------------------------------------------------------------- #
# Rules used for the de-novo FMN design ranking; all thresholds are exposed so
# the same code can be re-pointed at other columns / other wavelengths.
DEFAULT_SCREEN = {
    "protein_channel": "UV 1_280",     # curve name holding the protein signal
    "cofactor_channel": "UV 3_455",    # curve name holding the cofactor signal
    "baseline_win": [4.5, 8.5],        # mL, pre-elution plateau -> constant baseline
    "valley_left": [13.0, 14.3],       # mL, search window of the inter-peak valley
    "valley_right": [16.0, 18.6],      # mL, search window of the return-to-baseline valley
    "rise_lo": 8.0,                    # mL, start searching for the rise into the peaks
    "rise_frac": 0.02,                 # threshold = max(rise_frac*max, rise_abs)
    "rise_abs": 2.0,                   # mAU
    "eps_protein": 20000.0,            # M-1 cm-1, protein at 280 nm (from sequence if known)
    "eps_cofactor": 12500.0,           # M-1 cm-1, cofactor at its own wavelength
    "eps_cofactor_at_protein": 20000.0,  # M-1 cm-1, cofactor at 280 nm (correction)
    "v0": 7.6,                         # mL, void volume (for the MW estimate)
    "cal_a": 2.256, "cal_b": -2.72,    # log10(MW/kDa) = a + b*Kav  (generic Superdex 75)
}


def _median_baseline(x: np.ndarray, y: np.ndarray, lo: float, hi: float) -> float:
    m = (x >= lo) & (x <= hi)
    return float(np.median(y[m])) if m.any() else 0.0


def _argmin_volume(x: np.ndarray, y: np.ndarray, lo: float, hi: float, default: float) -> float:
    m = (x >= lo) & (x <= hi)
    if not m.any():
        return float(default)
    return float(x[m][int(np.argmin(y[m]))])


def _argmax_volume(x: np.ndarray, y: np.ndarray, lo: float, hi: float, default: float) -> float:
    m = (x >= lo) & (x <= hi)
    if not m.any():
        return float(default)
    return float(x[m][int(np.argmax(y[m]))])


def _area_above(x: np.ndarray, yb: np.ndarray, a: float, b: float) -> float:
    """Trapezoid of ``max(yb, 0)`` between two volumes [mAU*mL]."""
    m = (x >= a) & (x <= b)
    if m.sum() < 2:
        return 0.0
    return float(_trapz(np.clip(yb[m], 0, None), x[m]))


def _peak_window(x: np.ndarray, yb: np.ndarray, p: dict):
    """Return (early_window, monomer_window) in mL using the fixed valley rules."""
    vl, vh = p["valley_left"]
    rl, rh = p["valley_right"]
    valley = _argmin_volume(x, yb, vl, vh, 0.5 * (vl + vh))
    end = _argmin_volume(x, yb, rl, rh, rh)
    m = (x >= p["rise_lo"]) & (x < valley)
    xs, ys = x[m], yb[m]
    start = float(xs[0]) if xs.size else float(p["rise_lo"])
    if ys.size:
        thr = max(p["rise_frac"] * float(ys.max()), p["rise_abs"])
        above = ys > thr
        for i in range(1, len(above)):
            if above[i] and not above[i - 1]:
                start = float(xs[i - 1])
                break
    return (start, valley), (valley, end)


def screen_run(run, params: Optional[dict] = None) -> Optional[dict]:
    """Monomer-peak FMN-loading metric for one run (see DEFAULT_SCREEN)."""
    p = dict(DEFAULT_SCREEN)
    p.update(params or {})
    cp = run.curves.get(p["protein_channel"])
    cc = run.curves.get(p["cofactor_channel"])
    if cp is None or cc is None:
        return None

    xa = np.asarray(cp.volume, float)
    xb = np.asarray(cc.volume, float)
    b_p = _median_baseline(xa, np.asarray(cp.y, float), *p["baseline_win"])
    b_c = _median_baseline(xb, np.asarray(cc.y, float), *p["baseline_win"])
    ya = np.asarray(cp.y, float) - b_p
    yb = np.asarray(cc.y, float) - b_c

    early_a, mono_a = _peak_window(xa, ya, p)
    early_c, mono_c = _peak_window(xb, yb, p)
    # one common window for both channels (protein channel defines it)
    mono = mono_a if (mono_a[1] - mono_a[0]) >= 1.0 else mono_c
    early = early_a if (early_a[1] - early_a[0]) >= 1.0 else early_c

    a280 = _area_above(xa, ya, *mono)
    a455 = _area_above(xb, yb, *mono)
    e280 = _area_above(xa, ya, *early)
    e455 = _area_above(xb, yb, *early)

    vt = float(run.meta.get("column_volume") or 0) or 23.56
    apex = _argmax_volume(xa, ya, mono[0], mono[1], mono[0])
    kav = (apex - float(p["v0"])) / (vt - float(p["v0"]))
    mw_kda = float(10 ** (p["cal_a"] + p["cal_b"] * kav))

    corr = p["eps_cofactor_at_protein"] / p["eps_cofactor"]
    a280c = a280 - corr * a455
    mp = (xa >= mono[0]) & (xa <= mono[1])
    mc = (xb >= mono[0]) & (xb <= mono[1])
    cell = {
        "run": run.id, "name": run.name,
        "baseline_protein": b_p, "baseline_cofactor": b_c,
        "window": [round(mono[0], 3), round(mono[1], 3)],
        "early_window": [round(early[0], 3), round(early[1], 3)],
        "A280_monomer": a280, "A455_monomer": a455,
        "A280_early": e280, "A455_early": e455,
        "A280_monomer_corrected": a280c,
        "rho_monomer": (a455 / a280) if a280 > 0 else float("nan"),
        "r_monomer": ((a455 / p["eps_cofactor"]) / (a280c / p["eps_protein"])) if a280c > 0 else float("nan"),
        "rho_early": (e455 / e280) if e280 > 0 else float("nan"),
        "r_early": ((e455 / p["eps_cofactor"]) / ((e280 - corr * e455) / p["eps_protein"]))
                   if (e280 - corr * e455) > 0 else float("nan"),
        "apex_mL": apex, "kav": kav, "mw_kda": mw_kda,
        "h_A280_monomer": float(ya[mp].max()) if mp.any() else 0.0,
        "h_A455_monomer": float(yb[mc].max()) if mc.any() else 0.0,
    }
    cell["h_ratio_monomer"] = (cell["h_A455_monomer"] / cell["h_A280_monomer"]
                               if cell["h_A280_monomer"] > 0 else float("nan"))
    return cell


def screen_runs(runs: Sequence, params: Optional[dict] = None) -> List[dict]:
    out = [c for c in (screen_run(r, params) for r in runs) if c]
    out.sort(key=lambda c: (c["r_monomer"] if c["r_monomer"] == c["r_monomer"] else -1), reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Savitzky-Golay
# --------------------------------------------------------------------------- #
def savgol_coeffs(window: int, order: int, deriv: int = 0, dx: float = 1.0) -> np.ndarray:
    window = int(window)
    if window % 2 == 0:
        window += 1
    order = int(order)
    if window <= order:
        window = order + 2 + (order % 2 == 0)
    half = window // 2
    x = np.arange(-half, half + 1, dtype=float)
    A = np.vander(x, order + 1, increasing=True)
    pinv = np.linalg.pinv(A)
    c = pinv[deriv] * math.factorial(deriv) / (dx ** deriv)
    return c


def savgol(y: np.ndarray, window: int = 11, order: int = 3, deriv: int = 0, dx: float = 1.0) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    if window is None or window < 3 or window >= y.size:
        return y if deriv == 0 else np.gradient(np.gradient(y) if deriv == 2 else y, dx)
    c = savgol_coeffs(window, order, deriv, dx)
    half = window // 2
    ypad = np.pad(y, half, mode="edge")
    return np.convolve(ypad, c[::-1], mode="valid")


def derivative(y: np.ndarray, x: np.ndarray, order: int = 1,
               smooth: int = 0, poly: int = 3) -> np.ndarray:
    """1st/2nd derivative dy/dx (or d2y/dx2) on a possibly non-uniform x."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    dx = float(np.median(np.diff(x))) if x.size > 1 else 1.0
    if smooth and smooth >= 3:
        return savgol(y, int(smooth), int(poly), deriv=int(order), dx=dx)
    if order <= 1:
        return np.gradient(y, x, edge_order=1)
    return np.gradient(np.gradient(y, x, edge_order=1), x, edge_order=1)


# --------------------------------------------------------------------------- #
# Peak picking + integration
# --------------------------------------------------------------------------- #
def _local_maxima(y: np.ndarray) -> List[int]:
    if y.size < 3:
        return []
    m = (y[1:-1] >= y[:-2]) & (y[1:-1] > y[2:])
    return [i + 1 for i in np.nonzero(m)[0]]


def _prominence_extent(y: np.ndarray, i: int):
    """Return (left_idx, right_idx, left_min, right_min) for peak ``i``."""
    l = i
    while l - 1 >= 0 and y[l - 1] <= y[i]:
        l -= 1
    left_min = float(np.min(y[l:i + 1]))
    r = i
    while r + 1 < y.size and y[r + 1] <= y[i]:
        r += 1
    right_min = float(np.min(y[i:r + 1]))
    return l, r, left_min, right_min


def find_peaks(y: np.ndarray, x: np.ndarray, prominence: float = 0.0,
               min_distance: float = 0.0, smooth: int = 0, poly: int = 3,
               max_peaks: int = 40) -> List[dict]:
    """Detect peaks; ``prominence``/``min_distance`` are in y / x units."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    yy = savgol(y, int(smooth), int(poly)) if smooth and smooth >= 3 else y
    peaks = []
    for i in _local_maxima(yy):
        l, r, lmin, rmin = _prominence_extent(yy, i)
        prom = yy[i] - max(lmin, rmin)
        if prom < prominence:
            continue
        if min_distance > 0 and peaks and (x[i] - peaks[-1]["_x"]) < min_distance:
            if yy[i] > peaks[-1]["_y"]:
                peaks[-1] = {"i": i, "l": l, "r": r, "prom": prom,
                             "_x": float(x[i]), "_y": float(yy[i])}
            continue
        peaks.append({"i": i, "l": l, "r": r, "prom": prom,
                      "_x": float(x[i]), "_y": float(yy[i])})
    peaks.sort(key=lambda p: p["i"])
    return peaks[:max_peaks]


def _valleys(y: np.ndarray) -> List[int]:
    """Indices of every local minimum (deduplicated across flat plateaus)."""
    out: List[int] = []
    for j in range(1, y.size - 1):
        if y[j] <= y[j - 1] and y[j] <= y[j + 1]:
            if out and j == out[-1] + 1:
                if y[j] < y[out[-1]]:
                    out[-1] = j
            else:
                out.append(j)
    return out


def _outer_boundary(ys: np.ndarray, i: int, step: int, span: int,
                    valleys: Sequence[int], cut_frac: float) -> int:
    """Boundary on a side that has no neighbouring peak.

    Descend from the apex to ``cut_frac`` of the peak height (measured against
    the local minimum inside ``span`` points), then snap forward to the first
    local valley.  This avoids the drift-inflated areas you get by integrating
    all the way to the end of the run.
    """
    end = i + step * span
    end = max(0, min(ys.size - 1, end))
    lo, hi = (i, end) if step > 0 else (end, i)
    base = float(np.min(ys[lo:hi + 1]))
    level = base + cut_frac * (ys[i] - base)
    j = i
    while (step > 0 and j < ys.size - 1) or (step < 0 and j > 0):
        j += step
        if ys[j] <= level:
            break
    cands = [v for v in valleys if (v >= j if step > 0 else v <= j)]
    if not cands:
        return j
    cands.sort(reverse=step < 0)
    return cands[0]


def integrate_peaks(y: np.ndarray, x: np.ndarray, peaks: Sequence[dict],
                    cut_frac: float = 0.5, span_ml: float = 2.5) -> List[dict]:
    """Valley-to-valley integration with a straight baseline per peak."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    smoothed = savgol(y, 11, 3) if y.size > 15 else y
    valleys = _valleys(smoothed)
    dx = float(np.median(np.diff(x))) if x.size > 1 else 1.0
    span = max(5, int(span_ml / dx)) if dx > 0 else 200
    out: List[dict] = []
    idx = [p["i"] for p in peaks]
    for k, p in enumerate(peaks):
        i = p["i"]
        if k > 0:
            lo = int(np.argmin(smoothed[idx[k - 1]:i + 1])) + idx[k - 1]
        else:
            lo = _outer_boundary(smoothed, i, -1, span, valleys, cut_frac)
        if k < len(peaks) - 1:
            hi = int(np.argmin(smoothed[i:idx[k + 1] + 1])) + i
        else:
            hi = _outer_boundary(smoothed, i, +1, span, valleys, cut_frac)
        if hi <= lo:
            hi = min(lo + 1, y.size - 1)
        xs = x[lo:hi + 1]
        ys = y[lo:hi + 1]
        if xs.size < 2:
            continue
        base = np.linspace(ys[0], ys[-1], xs.size)
        corr = ys - base
        corr = np.clip(corr, 0, None)
        area = float(_trapz(corr, xs))
        apex_y = float(y[i])
        base_at_apex = float(np.interp(x[i], [xs[0], xs[-1]], [ys[0], ys[-1]]))
        height = apex_y - base_at_apex
        # width at half height
        half = base_at_apex + height / 2.0
        left_half = np.where(y[lo:i + 1] >= half)[0]
        right_half = np.where(y[i:hi + 1] >= half)[0]
        fwhm = 0.0
        if left_half.size and right_half.size:
            fwhm = float(x[i + right_half[0]] - x[lo + left_half[0]])
        out.append({
            "n": k + 1,
            "apex_x": float(x[i]),
            "apex_y": apex_y,
            "height": float(height),
            "start_x": float(xs[0]),
            "end_x": float(xs[-1]),
            "area": area,
            "fwhm": fwhm,
            "prominence": float(p["prom"]),
        })
    total = sum(p["area"] for p in out) or 1.0
    for p in out:
        p["area_pct"] = 100.0 * p["area"] / total
    return out


# --------------------------------------------------------------------------- #
# Protein sequence
# --------------------------------------------------------------------------- #
_AA_AVG = {
    "A": 71.0788, "R": 156.1875, "N": 114.1038, "D": 115.0886, "C": 103.1388,
    "E": 129.1155, "Q": 128.1307, "G": 57.0519, "H": 137.1411, "I": 113.1594,
    "L": 113.1594, "K": 128.1741, "M": 131.1926, "F": 147.1766, "P": 97.1167,
    "S": 87.0782, "T": 101.1051, "W": 186.2132, "Y": 163.1760, "V": 99.1326,
}
_AA_MONO = {
    "A": 71.03711, "R": 156.10111, "N": 114.04293, "D": 115.02694, "C": 103.00919,
    "E": 129.04259, "Q": 128.05858, "G": 57.02146, "H": 137.05891, "I": 113.08406,
    "L": 113.08406, "K": 128.09496, "M": 131.04049, "F": 147.06841, "P": 97.05276,
    "S": 87.03203, "T": 101.04768, "W": 186.07931, "Y": 163.06333, "V": 99.06841,
}
_WATER = 18.01528
_WATER_MONO = 18.01056
# EMBOSS pKa set (used for pI)
_PKA_POS = {"K": 10.8, "R": 12.5, "H": 6.5, "Nterm": 8.6}
_PKA_NEG = {"D": 3.9, "E": 4.1, "C": 8.5, "Y": 10.1, "Cterm": 3.6}
_KD = {  # Kyte-Doolittle hydropathy
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "E": -3.5, "Q": -3.5,
    "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8,
    "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}


def _net_charge(seq: str, ph: float) -> float:
    q = 0.0
    for aa, pka in _PKA_POS.items():
        n = 1 if aa == "Nterm" else seq.count(aa)
        if n:
            q += n / (1.0 + 10 ** (ph - pka))
    for aa, pka in _PKA_NEG.items():
        n = 1 if aa == "Cterm" else seq.count(aa)
        if n:
            q -= n / (1.0 + 10 ** (pka - ph))
    return q


def analyze_sequence(seq: str, a280_value: Optional[float] = None) -> dict:
    seq = "".join(c for c in (seq or "").upper() if c.isalpha())
    if not seq:
        return {"error": "empty sequence"}
    n = len(seq)
    mw_avg = sum(_AA_AVG.get(a, 110.0) for a in seq) + _WATER
    mw_mono = sum(_AA_MONO.get(a, 0.0) for a in seq) + _WATER_MONO

    nW, nY = seq.count("W"), seq.count("Y")
    nC = seq.count("C")
    cystines = nC // 2
    eps280 = 5500 * nW + 1490 * nY + 125 * cystines   # Pace et al. 1995
    a280_01pct = eps280 / mw_avg if mw_avg else 0.0    # A(0.1 %, 1 g/L)

    lo, hi = 0.0, 14.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if _net_charge(seq, mid) > 0:
            lo = mid
        else:
            hi = mid
    pi = (lo + hi) / 2

    gravy = sum(_KD.get(a, 0.0) for a in seq) / n
    aromaticity = (seq.count("F") + nY + nW) / n

    res = {
        "length": n,
        "mw_avg": mw_avg,
        "mw_mono": mw_mono,
        "pI": pi,
        "charge_pH7": _net_charge(seq, 7.0),
        "eps280": eps280,
        "a280_0_1pct": a280_01pct,
        "nW": nW, "nY": nY, "nC": nC, "cystines": cystines,
        "gravy": gravy,
        "aromaticity": aromaticity,
        "conc_mg_ml": None,
        "conc_uM": None,
    }
    if a280_value not in (None, ""):
        try:
            a = float(a280_value)
            res["conc_mg_ml"] = a / a280_01pct if a280_01pct else None
            res["conc_uM"] = (a / eps280 * 1e6) if eps280 else None   # mol/L -> µM (1 cm)
        except (TypeError, ValueError):
            pass
    return res


# --------------------------------------------------------------------------- #
# SEC molar-mass calibration
# --------------------------------------------------------------------------- #
def calibrate_sec(standards: Sequence[dict], sample_volumes: Sequence[float],
                  v0: float, vt: float) -> dict:
    """standards: [{'volume': Ve, 'mw': MW}, ...]; returns fit + predicted MW."""
    pts = [(float(s["volume"]), float(s["mw"])) for s in standards
           if s.get("volume") not in (None, "") and s.get("mw") not in (None, "")]
    pts = [(v, m) for v, m in pts if m > 0 and vt > v0]
    if len(pts) < 2:
        return {"error": "need at least 2 standards (and Vt > V0)"}
    kav = np.array([(v - v0) / (vt - v0) for v, _ in pts])
    logmw = np.log10([m for _, m in pts])
    slope, intercept = np.polyfit(kav, logmw, 1)
    pred = np.polyval([slope, intercept], kav)
    ss_res = float(np.sum((logmw - pred) ** 2))
    ss_tot = float(np.sum((logmw - logmw.mean()) ** 2)) or 1.0
    r2 = 1 - ss_res / ss_tot
    out = {
        "slope": float(slope), "intercept": float(intercept), "r2": r2,
        "v0": float(v0), "vt": float(vt),
        "standards": [{"volume": v, "mw": m, "kav": float(k)} for (v, m), k in zip(pts, kav)],
        "predictions": [],
    }
    for v in sample_volumes:
        if v is None:
            continue
        k = (float(v) - v0) / (vt - v0)
        out["predictions"].append({"volume": float(v), "kav": float(k),
                                   "mw": float(10 ** (slope * k + intercept))})
    return out


# --------------------------------------------------------------------------- #
# Cofactor : protein stoichiometry (e.g. FMN)
# --------------------------------------------------------------------------- #
def cofactor_ratio(area_protein: float, area_cofactor: float,
                   eps_protein: float, eps_cofactor: float,
                   eps_cofactor_at_protein_lambda: float = 0.0) -> dict:
    """Molar cofactor : protein ratio from two SEC peak areas.

    ``area`` is the integrated peak area in mAU*mL (AUC), ``eps`` in M-1 cm-1.
    The protein area is first corrected for the cofactor's own absorbance at the
    protein wavelength:  A_prot = A_total - (eps_cof(l)/eps_cof(l_cof)) * A_cof.
    """
    if not eps_protein or not eps_cofactor:
        return {"error": "epsilon values required"}
    corr = area_protein
    if eps_cofactor_at_protein_lambda:
        corr = area_protein - (eps_cofactor_at_protein_lambda / eps_cofactor) * area_cofactor
    n_prot = corr / eps_protein
    n_cof = area_cofactor / eps_cofactor
    ratio = (n_cof / n_prot) if n_prot else float("nan")
    return {
        "area_protein": area_protein,
        "area_protein_corrected": corr,
        "area_cofactor": area_cofactor,
        "n_protein_rel": n_prot,
        "n_cofactor_rel": n_cof,
        "ratio": ratio,
    }
