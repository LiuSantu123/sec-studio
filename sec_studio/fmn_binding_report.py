#!/usr/bin/env python3
"""Rank de novo designs by FMN loading from SEC A280 / A455 peak areas.

The metric itself lives in ``analysis.screen_run`` / ``analysis.screen_runs``
(shared with the web UI, POST /api/screen) - this file is only the CLI.

Fixed rules (see analysis.DEFAULT_SCREEN, all overridable):
  * constant baseline  : median of the 4.5-8.5 mL pre-elution plateau (per channel)
  * monomer window     : [valley in 13.0-14.3 mL] .. [valley in 16.0-18.6 mL]
  * one common window  : both channels integrated over the protein channel's window
  * area               : trapezoid of max(y - baseline, 0)  [mAU*mL]
  * rho                : A455_area / A280_area                (assumption free)
  * r                  : (A455/eps455) / (A280corr/eps280)    (molar loading)

eps455(FMN) / eps280(FMN) are literature placeholders and are identical for every
run, so they rescale all r by one constant and do NOT change the ranking.
eps280(protein) is unknown without the sequences; assuming it is equal across
designs, it also cancels from the ranking.
"""
from __future__ import annotations
import argparse, csv, glob, os

import akta, analysis

COLS = ["run", "rho_monomer", "r_monomer", "A280_monomer", "A455_monomer",
        "A280_monomer_corrected", "h_A280_monomer", "h_A455_monomer", "h_ratio_monomer",
        "rho_early", "r_early", "A280_early", "A455_early",
        "apex_mL", "mw_kda", "kav", "window", "early_window",
        "baseline_protein", "baseline_cofactor"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="/data/codex/webui/sec")
    ap.add_argument("--out", default="/data/codex/webui/sec/analysis_fmn")
    ap.add_argument("--eps-protein", type=float, default=analysis.DEFAULT_SCREEN["eps_protein"])
    ap.add_argument("--eps-cofactor", type=float, default=analysis.DEFAULT_SCREEN["eps_cofactor"])
    ap.add_argument("--eps-cofactor-at-protein", type=float,
                    default=analysis.DEFAULT_SCREEN["eps_cofactor_at_protein"])
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    runs = []
    for zp in sorted(glob.glob(os.path.join(args.folder, "*.zip"))):
        runs.append(akta.parse_result_zip(open(zp, "rb").read(), source=os.path.basename(zp)))

    params = {"eps_protein": args.eps_protein, "eps_cofactor": args.eps_cofactor,
              "eps_cofactor_at_protein": args.eps_cofactor_at_protein}
    rows = analysis.screen_runs(runs, params)

    path = os.path.join(args.out, "fmn_binding_ranking.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(COLS)
        for r in rows:
            w.writerow([f"{r[c]:.4f}" if isinstance(r[c], float) else r[c] for c in COLS])

    print(f"{'run':16} {'rho_mon':>8} {'r_mon':>7} {'A280_mon':>9} {'A455_mon':>9} "
          f"{'h280':>7} {'h455':>6} {'rho_early':>9} {'MW/kDa':>7}")
    for r in rows:
        print(f"{r['run']:16} {r['rho_monomer']:8.4f} {r['r_monomer']:7.3f} "
              f"{r['A280_monomer']:9.1f} {r['A455_monomer']:9.1f} "
              f"{r['h_A280_monomer']:7.1f} {r['h_A455_monomer']:6.1f} "
              f"{r['rho_early']:9.4f} {r['mw_kda']:7.1f}")
    print("\nwrote", path)
    return rows


if __name__ == "__main__":
    main()
