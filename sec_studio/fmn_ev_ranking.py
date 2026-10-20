#!/usr/bin/env python3
"""Re-rank de-novo FMN designs using per-design extinction coefficients.

Rules (per user):
  * monomer = the LAST significant A280 single peak in 12-16.8 mL
    (excludes the ~19 mL non-flavin species and early aggregates)
  * baseline = constant median of the 4.5-8.5 mL plateau
  * area     = trapz(max(y - baseline, 0))   [mAU*mL]
  * molar FMN loading r = (A455/eps455) / (A280corr/eps280)
        A280corr = A280 - (eps280_FMN/eps455)*A455
  * eps280 from the plasmid-derived design sequence (Pace 1995, reduced);
    both the no-tag (design) and 6xHis-TEV (fusion) values are reported.

Output: data/fmn_ranking/fmn_ev_ranking.csv (+ printed table).
"""
from __future__ import annotations
import argparse, csv, glob, os, re
import numpy as np

import akta, analysis

_trapz = getattr(np, "trapezoid", None) or np.trapz
EPS455 = 12500.0
EPS280_FMN = 20000.0
# elution-based MW estimate (kDa), fitted from ev5 known-MW designs:
# log10(MW/kDa) = a + b*Kav, V0=7.6, Vt=23.562
MW_A, MW_B, MW_V0, MW_VT = 1.518, -0.819, 7.6, 23.562


def design_of(run_name: str):
    m = re.match(r"e(\d+)(?:t\d+)?", run_name)
    return "e%03d" % int(m.group(1)) if m else None


def source_of(design: str):
    """Which prediction model selected this design (per user, 2026-09-30)."""
    if not design:
        return ""
    d = int(design[1:])
    # ev4 runs originally labelled e90/e95/e96 were corrected to e98/e103/e104;
    # all three belong to the AffinCraft-selected group.
    if d in (90, 95, 96, 98, 103, 104) or 105 <= d <= 109:
        return "own_model"
    if 110 <= d <= 117:
        return "af3"
    if 118 <= d <= 125:
        return "boltz2"
    if 126 <= d <= 128:
        return "long_126-128"
    return "?"


def _baseline(x, y, lo=4.5, hi=8.5):
    m = (x >= lo) & (x <= hi)
    return float(np.median(y[m])) if m.any() else 0.0


def _argmin_vol(x, y, a, b, default):
    m = (x >= a) & (x <= b)
    return float(x[m][int(np.argmin(y[m]))]) if m.any() else float(default)


def monomer_peak(x, yb, lo=12.0, hi=16.8, prominence=15.0, min_h=20.0):
    pk = analysis.find_peaks(yb, x, prominence=prominence, min_distance=0.4, smooth=11)
    cand = [p for p in pk if lo <= x[p["i"]] <= hi and yb[p["i"]] >= min_h]
    if not cand:
        return None
    cand.sort(key=lambda p: x[p["i"]])
    p = cand[-1]
    i = p["i"]
    left = _argmin_vol(x, yb, x[i] - 1.5, x[i] - 0.3, x[i] - 0.8)
    right = _argmin_vol(x, yb, x[i] + 0.3, x[i] + 2.2, x[i] + 1.2)
    return {"apex": float(x[i]), "left": left, "right": right}


def area_between(x, yb, a, b):
    m = (x >= a) & (x <= b)
    return float(_trapz(np.clip(yb[m], 0, None), x[m])) if m.sum() >= 2 else 0.0


def process_run(run, designs, folder=""):
    design = design_of(run.id)
    si = designs.get(design) if design else None
    a = run.curves["UV 1_280"]
    b = run.curves["UV 3_455"]
    xa, ya = a.volume, np.asarray(a.y, float) - _baseline(a.volume, a.y)
    xb, yb = b.volume, np.asarray(b.y, float) - _baseline(b.volume, b.y)
    mp = monomer_peak(xa, ya)
    row = {"folder": folder, "run": run.id, "design": design, "source": source_of(design),
           "seq": bool(si), "error": ""}
    if mp is None:
        row.update({"monomer_mL": None, "window": None, "A280_monomer": 0.0, "A455_monomer": 0.0,
                    "rho": None, "r_design": None, "r_fusion": None, "h_ratio": None,
                    "error": "no monomer peak in 12-16.8 mL"})
        return row
    lo, hi = mp["left"], mp["right"]
    a280 = area_between(xa, ya, lo, hi)
    a455 = area_between(xb, yb, lo, hi)
    apex_y = float(ya[(xa >= lo) & (xa <= hi)].max())
    h455 = float(yb[(xb >= lo) & (xb <= hi)].max())
    corr = EPS280_FMN / EPS455
    a280c = a280 - corr * a455

    row.update({
        "monomer_mL": round(mp["apex"], 3), "window": [round(lo, 2), round(hi, 2)],
        "A280_monomer": a280, "A455_monomer": a455, "A280_corrected": a280c,
        "rho": (a455 / a280) if a280 > 0 else float("nan"),
        "h_A280": float(apex_y), "h_A455": float(h455),
        "h_ratio": (h455 / apex_y) if apex_y else float("nan"),
        "r_design": None, "r_fusion": None,
        "sec_mw_kda": float(10 ** (MW_A + MW_B * (mp["apex"] - MW_V0) / (MW_VT - MW_V0))),
    })
    if si:
        eps_d = float(si["eps280_design"])
        eps_f = float(si["eps280_fusion"])
        row["r_design"] = ((a455 / EPS455) / (a280c / eps_d)) if a280c > 0 else float("nan")
        row["r_fusion"] = ((a455 / EPS455) / (a280c / eps_f)) if a280c > 0 else float("nan")
        row.update({"eps280_design": eps_d, "eps280_fusion": eps_f,
                    "len_design": int(si["len_design"]), "mw_design_kda": float(si["mw_design_kda"]),
                    "design_seq": si["design_seq"]})
        # size / elution sanity flag: does the elution MW match the design MW?
        dm = row["mw_design_kda"]
        em = row["sec_mw_kda"]
        if dm > 20 and abs(em - dm) > 6:
            row["size_note"] = (f"elution MW ~{em:.1f}kDa != design {dm:.1f}kDa "
                                f"(mapping or non-globular / fragment?)")
    else:
        row.update({"eps280_design": None, "eps280_fusion": None, "len_design": None,
                    "mw_design_kda": None, "design_seq": ""})
    return row


def load_designs(path):
    out = {}
    with open(path) as fh:
        for row in csv.DictReader(fh):
            out[row["design"]] = row
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ev4", default="/data/codex/webui/sec/data/ev4")
    ap.add_argument("--ev5", default="/data/codex/webui/sec/data/ev5t1")
    ap.add_argument("--designs", default="/data/codex/webui/sec/data/plasmid/design_sequences.csv")
    ap.add_argument("--out", default="/data/codex/webui/sec/data/fmn_ranking")
    args = ap.parse_args()

    designs = load_designs(args.designs)
    rows = []
    for folder in (args.ev4, args.ev5):
        for zp in sorted(glob.glob(os.path.join(folder, "*.zip"))):
            run = akta.parse_result_zip(open(zp, "rb").read(), source=os.path.basename(zp))
            rows.append(process_run(run, designs, folder=os.path.basename(folder)))
    os.makedirs(args.out, exist_ok=True)

    def key(r):
        rv = r.get("r_design")
        return (rv if rv is not None and rv == rv else -1,
                r.get("rho") if r.get("rho") is not None and r.get("rho") == r.get("rho") else -1,
                bool(r.get("seq")))
    rows.sort(key=key, reverse=True)

    cols = ["folder", "run", "design", "source", "seq", "monomer_mL", "sec_mw_kda", "A280_monomer", "A455_monomer",
            "rho", "r_design", "r_fusion", "eps280_design", "eps280_fusion",
            "len_design", "mw_design_kda", "h_A280", "h_A455", "h_ratio",
            "window", "A280_corrected", "error", "size_note"]
    with open(os.path.join(args.out, "fmn_ev_ranking.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])

    def F(v, n=2, d="  -"):
        return d if v is None else (f"{v:.{n}f}" if isinstance(v, float) else str(v))
    print(f"{'run':13} {'des':5} {'mon':>6} {'A280':>8} {'A455':>8} {'rho':>6} {'r(noTag)':>8} "
          f"{'r(+His)':>8} {'secMW':>6} {'dMW':>6}  note")
    for r in rows:
        note = r.get("error") or r.get("size_note") or ("" if r.get("seq") else "NO PLASMID")
        print(f"{r['run']:13} {str(r.get('design')):5} {F(r.get('monomer_mL'),2):>6} "
              f"{F(r.get('A280_monomer'),1):>8} {F(r.get('A455_monomer'),1):>8} "
              f"{F(r.get('rho'),3):>6} {F(r.get('r_design'),3):>8} {F(r.get('r_fusion'),3):>8} "
              f"{F(r.get('sec_mw_kda'),1):>6} {F(r.get('mw_design_kda'),1):>6}  {note}")
    print("\nwrote", os.path.join(args.out, "fmn_ev_ranking.csv"))

    # --- per-model summary (ev5t1 only: the batch where molar r is valid) -- #
    import statistics
    groups = {}
    for r in rows:
        rv = r.get("r_design")
        if r.get("folder") != "ev5t1" or rv is None or rv != rv:   # NaN or missing
            continue
        g = r.get("source") or "?"
        groups.setdefault(g, []).append((r["run"], float(rv)))
    print("\nPer-model FMN-loading summary (EV5t1 only, molar r, no-tag ε280):")
    for g in sorted(groups):
        vals = [v for _, v in groups[g]]
        best = max(groups[g], key=lambda x: x[1])
        print(f"  {g:16} n={len(vals):2}  mean={statistics.mean(vals):.3f} "
              f"median={statistics.median(vals):.3f}  best={best[0]}({best[1]:.3f})  "
              f">0.05: {sum(1 for v in vals if v > 0.05)}/{len(vals)}")
    return rows


if __name__ == "__main__":
    main()
