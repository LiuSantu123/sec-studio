#!/usr/bin/env python3
"""A230/A455 SEC ranking tables (24 designs, no epsilon conversion).

Uses the same monomer peak window as the A280 analysis.  A230 is treated as a
protein-backbone signal and A455 as the FMN signal.

Outputs:
  data/fmn_ranking/a230_a455_abs_area_ranking_table.{png,pdf,svg,csv}
      Absolute monomer-peak areas and A455/A230 ratios, no normalization.

  data/fmn_ranking/a230_a455_normalized_ranking_table.{png,pdf,svg,csv}
      Same monomer-peak values normalized by each run's global A230 peak.

  data/fmn_ranking/a230_a455_full_table.csv
      Combined raw + normalized values for auditing.
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys
from pathlib import Path

import numpy as np

import akta
import analysis
from plot_fmn_ranking_tables import (
    METHOD_COLOR,
    SOURCE_LABEL,
    as_float,
    canon_design,
    draw_table,
    fmt,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data/fmn_ranking"

EXCLUDED = {"e126", "e127", "e128"}
REQUIRED_EXTRA = {"e98", "e103", "e104"}
SELECTED = {
    "e124", "e116", "e108", "e107", "e104", "e114", "e105", "e110",
    "e125", "e98", "e118", "e109", "e120", "e117", "e103", "e122",
    "e106", "e115", "e113", "e121", "e112", "e119", "e111", "e123",
}

_trapz = getattr(np, "trapezoid", None) or np.trapz


def _baseline(x, y, lo=4.5, hi=8.5):
    m = (x >= lo) & (x <= hi)
    return float(np.median(y[m])) if m.any() else 0.0


def _argmin(x, y, a, b, default):
    m = (x >= a) & (x <= b)
    return float(x[m][int(np.argmin(y[m]))]) if m.any() else float(default)


def _monomer(x, y):
    peaks = analysis.find_peaks(y, x, prominence=15.0, min_distance=0.4, smooth=11)
    cand = [p for p in peaks if 12.0 <= x[p["i"]] <= 16.8 and y[p["i"]] >= 20.0]
    if not cand:
        return None
    p = sorted(cand, key=lambda q: x[q["i"]])[-1]
    i = p["i"]
    lo = _argmin(x, y, x[i] - 1.5, x[i] - 0.3, x[i] - 0.8)
    hi = _argmin(x, y, x[i] + 0.3, x[i] + 2.2, x[i] + 1.2)
    return {"lo": lo, "hi": hi}


def _channel(curve):
    x = np.asarray(curve.volume)
    y = np.asarray(curve.y, float) - _baseline(curve.volume, curve.y)
    return x, y


def _integrate(x, y, lo, hi):
    m = (x >= lo) & (x <= hi)
    area = float(_trapz(np.clip(y[m], 0, None), x[m]))
    height = float(y[m].max())
    return area, height


def _global_peak(x, y, lo=7.0, hi=20.0):
    m = (x >= lo) & (x <= hi)
    return float(y[m].max()) if m.any() else float("nan")


def collect_rows(ev4: Path, ev5: Path) -> list[dict]:
    rows = []
    for folder in (ev4, ev5):
        for zp in sorted(glob.glob(os.path.join(folder, "*.zip"))):
            run = akta.parse_result_zip(open(zp, "rb").read(), source=os.path.basename(zp))
            design = canon_design(run.id)
            if design not in SELECTED:
                continue
            x280, y280 = _channel(run.curves["UV 1_280"])
            x230, y230 = _channel(run.curves["UV 2_230"])
            x455, y455 = _channel(run.curves["UV 3_455"])
            mp = _monomer(x280, y280)
            if mp is None:
                continue
            lo, hi = mp["lo"], mp["hi"]
            a230, h230 = _integrate(x230, y230, lo, hi)
            a455, h455 = _integrate(x455, y455, lo, hi)
            g230 = _global_peak(x230, y230)
            rows.append(
                {
                    "design": design,
                    "run": run.id,
                    "source": SOURCE_LABEL.get(
                        "own_model" if design in REQUIRED_EXTRA or 105 <= int(design[1:]) <= 109 else "af3" if 110 <= int(design[1:]) <= 117 else "boltz2",
                        "?",
                    ),
                    "window": [round(lo, 2), round(hi, 2)],
                    "global_a230_peak": g230,
                    "a230_area": a230,
                    "a455_area": a455,
                    "h230": h230,
                    "h455": h455,
                }
            )
    for row in rows:
        a = row["a230_area"]
        b = row["a455_area"]
        ha = row["h230"]
        hb = row["h455"]
        row["a455_a230_area"] = (b / a) if a else None
        row["a230_a455_area"] = (a / b) if b else None
        row["a455_a230_peak"] = (hb / ha) if ha else None
        row["a230_a455_peak"] = (ha / hb) if hb else None
        row["norm_a230_peak"] = (ha / row["global_a230_peak"]) if row["global_a230_peak"] else None
        row["norm_a455_peak"] = (hb / row["global_a230_peak"]) if row["global_a230_peak"] else None
        row["norm_a230_area"] = (a / row["global_a230_peak"]) if row["global_a230_peak"] else None
        row["norm_a455_area"] = (b / row["global_a230_peak"]) if row["global_a230_peak"] else None
    rows.sort(key=lambda r: (-r["a455_a230_area"], r["design"]))
    return rows


def write_tidy(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ev4", type=Path, default=ROOT / "data/ev4")
    parser.add_argument("--ev5", type=Path, default=ROOT / "data/ev5t1")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    rows = collect_rows(args.ev4, args.ev5)
    if len(rows) != 24:
        raise SystemExit(f"expected 24 rows, got {len(rows)}")
    present = {row["design"] for row in rows}
    if not REQUIRED_EXTRA <= present or present & EXCLUDED:
        raise SystemExit(f"design set wrong: extras missing={REQUIRED_EXTRA - present}, excluded={sorted(present & EXCLUDED)}")

    args.out.mkdir(parents=True, exist_ok=True)

    # Absolute-area table (no normalization, no epsilon).
    abs_headers = [
        "Rank",
        "Design",
        "A230 area\n(mAU\u00b7mL)",
        "A455 area\n(mAU\u00b7mL)",
        "A455/A230\n(area)",
        "A230/A455\n(area)",
        "A455/A230\n(peak)",
        "Screening method",
    ]
    abs_rows = [
        [
            str(rank),
            row["design"],
            fmt(row["a230_area"], 1),
            fmt(row["a455_area"], 1),
            fmt(row["a455_a230_area"], 4),
            fmt(row["a230_a455_area"], 4),
            fmt(row["a455_a230_peak"], 4),
            row["source"],
        ]
        for rank, row in enumerate(rows, start=1)
    ]
    draw_table(
        title="A230/A455 SEC monomer-peak area comparison: 24 designs",
        subtitle=(
            "No normalization, no epsilon conversion. A230 = protein-backbone signal; "
            "A455 = FMN signal. Sorted by monomer A455/A230 area ratio. "
            "e126/e127/e128 excluded."
        ),
        note=(
            "Areas use the same monomer window as the A280 analysis. "
            "A230/A455 ratios are signal ratios, not molar ratios."
        ),
        headers=abs_headers,
        rows=abs_rows,
        colors=[METHOD_COLOR[row["source"]] for row in rows],
        col_widths=[0.06, 0.075, 0.12, 0.12, 0.13, 0.13, 0.12, 0.205],
        out_stem=args.out / "a230_a455_abs_area_ranking_table",
        figsize=(15.6, 10.2),
        table_font=9.6,
        header_font=9.4,
    )
    write_tidy(
        args.out / "a230_a455_abs_area_ranking_table.csv",
        [
            "rank",
            "design",
            "run",
            "source",
            "a230_area_mAU_mL",
            "a455_area_mAU_mL",
            "a455_a230_area",
            "a230_a455_area",
            "a455_a230_peak",
            "sort_key",
        ],
        [
            {
                "rank": rank,
                "design": row["design"],
                "run": row["run"],
                "source": row["source"],
                "a230_area_mAU_mL": row["a230_area"],
                "a455_area_mAU_mL": row["a455_area"],
                "a455_a230_area": row["a455_a230_area"],
                "a230_a455_area": row["a230_a455_area"],
                "a455_a230_peak": row["a455_a230_peak"],
                "sort_key": "A455/A230 area descending",
            }
            for rank, row in enumerate(rows, start=1)
        ],
    )

    # Normalized table (denominator = each run's global A230 peak).
    norm_headers = [
        "Rank",
        "Design",
        "Norm.\nA230 peak",
        "Norm.\nA455 peak",
        "A455/A230\n(peak)",
        "Norm.\nA230 area",
        "Norm.\nA455 area",
        "A455/A230\n(area)",
        "Screening method",
    ]
    norm_rows = [
        [
            str(rank),
            row["design"],
            fmt(row["norm_a230_peak"], 4),
            fmt(row["norm_a455_peak"], 4),
            fmt(row["a455_a230_peak"], 4),
            fmt(row["norm_a230_area"], 4),
            fmt(row["norm_a455_area"], 4),
            fmt(row["a455_a230_area"], 4),
            row["source"],
        ]
        for rank, row in enumerate(rows, start=1)
    ]
    draw_table(
        title="A230/A455 SEC normalized monomer-peak comparison: 24 designs",
        subtitle=(
            "Each design was divided by its own global A230 peak. A230/A455 values "
            "and ratios use only the monomer peak. Sorted by monomer A455/A230 area ratio. "
            "e126/e127/e128 excluded."
        ),
        note=(
            "Normalized values are relative units, not mAU. Normalization cancels in "
            "the ratio, so the rank order matches the absolute-area table."
        ),
        headers=norm_headers,
        rows=norm_rows,
        colors=[METHOD_COLOR[row["source"]] for row in rows],
        col_widths=[0.06, 0.075, 0.12, 0.12, 0.13, 0.12, 0.12, 0.13, 0.185],
        out_stem=args.out / "a230_a455_normalized_ranking_table",
        figsize=(16.2, 10.2),
        table_font=9.5,
        header_font=9.3,
    )
    write_tidy(
        args.out / "a230_a455_normalized_ranking_table.csv",
        [
            "rank",
            "design",
            "run",
            "source",
            "global_a230_peak_mAU",
            "norm_a230_peak",
            "norm_a455_peak",
            "a455_a230_peak",
            "norm_a230_area",
            "norm_a455_area",
            "a455_a230_area",
            "sort_key",
        ],
        [
            {
                "rank": rank,
                "design": row["design"],
                "run": row["run"],
                "source": row["source"],
                "global_a230_peak_mAU": row["global_a230_peak"],
                "norm_a230_peak": row["norm_a230_peak"],
                "norm_a455_peak": row["norm_a455_peak"],
                "a455_a230_peak": row["a455_a230_peak"],
                "norm_a230_area": row["norm_a230_area"],
                "norm_a455_area": row["norm_a455_area"],
                "a455_a230_area": row["a455_a230_area"],
                "sort_key": "A455/A230 area descending",
            }
            for rank, row in enumerate(rows, start=1)
        ],
    )

    # Full audit CSV.
    write_tidy(
        args.out / "a230_a455_full_table.csv",
        [
            "rank",
            "design",
            "run",
            "source",
            "window",
            "global_a230_peak_mAU",
            "a230_area_mAU_mL",
            "a455_area_mAU_mL",
            "h230_mAU",
            "h455_mAU",
            "a455_a230_area",
            "a230_a455_area",
            "a455_a230_peak",
            "a230_a455_peak",
            "norm_a230_peak",
            "norm_a455_peak",
            "norm_a230_area",
            "norm_a455_area",
        ],
        [
            {
                "rank": rank,
                "design": row["design"],
                "run": row["run"],
                "source": row["source"],
                "window": "-".join(str(v) for v in row["window"]),
                "global_a230_peak_mAU": row["global_a230_peak"],
                "a230_area_mAU_mL": row["a230_area"],
                "a455_area_mAU_mL": row["a455_area"],
                "h230_mAU": row["h230"],
                "h455_mAU": row["h455"],
                "a455_a230_area": row["a455_a230_area"],
                "a230_a455_area": row["a230_a455_area"],
                "a455_a230_peak": row["a455_a230_peak"],
                "a230_a455_peak": row["a230_a455_peak"],
                "norm_a230_peak": row["norm_a230_peak"],
                "norm_a455_peak": row["norm_a455_peak"],
                "norm_a230_area": row["norm_a230_area"],
                "norm_a455_area": row["norm_a455_area"],
            }
            for rank, row in enumerate(rows, start=1)
        ],
    )

    print("wrote absolute-area table:", args.out / "a230_a455_abs_area_ranking_table.{png,pdf,svg,csv}")
    print("wrote normalized table:", args.out / "a230_a455_normalized_ranking_table.{png,pdf,svg,csv}")
    print("wrote full audit csv:", args.out / "a230_a455_full_table.csv")
    print("A455/A230 area ranking:")
    print("  " + " > ".join(row["design"] for row in rows))


if __name__ == "__main__":
    main()
