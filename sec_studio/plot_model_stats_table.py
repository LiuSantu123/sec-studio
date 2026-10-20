#!/usr/bin/env python3
"""Render a statistics table for molar r and A455/A230 area ratio by model.

Input:  data/fmn_ranking/model_stats_molar_r_a230.csv
Output: data/fmn_ranking/model_stats_molar_r_a230_table.{png,pdf,svg}
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "data/fmn_ranking/model_stats_molar_r_a230.csv"
DEFAULT_OUT = ROOT / "data/fmn_ranking"

MODEL_ORDER = ["AffinCraft", "AF3", "Boltz2 affinity", "All 24"]
METRICS = [
    ("molar_r_A455_A280_eps280", "molar r  (A455/A280, \u03b5280-based)"),
    ("area_r_A455_A230", "A455/A230  area ratio  (no \u03b5 conversion)"),
]

HEADERS = [
    "Model",
    "n",
    "Mean",
    "Median",
    "Variance\n(sample)",
    "SD",
    "SEM",
    "CV (%)",
    "Min",
    "Max",
]


def fmt(value, digits: int = 5) -> str:
    if value in (None, ""):
        return "-"
    return f"{float(value):.{digits}f}"


def render(out_stem: Path) -> None:
    rows = list(csv.DictReader(open(DEFAULT_CSV)))
    by_metric: dict[str, dict[str, dict]] = {}
    for row in rows:
        by_metric.setdefault(row["metric"], {})[row["model"]] = row

    table_rows: list[list[str]] = []
    section_colors: list[str] = []
    for metric, label in METRICS:
        table_rows.append([label, "", "", "", "", "", "", "", "", ""])
        section_colors.append("#d6e4f0")
        for model in MODEL_ORDER:
            s = by_metric[metric][model]
            table_rows.append(
                [
                    model,
                    fmt(s["n"], 0),
                    fmt(s["mean"]),
                    fmt(s["median"]),
                    fmt(s["var_ddof1"], 6),
                    fmt(s["std_ddof1"]),
                    fmt(s["sem"]),
                    f"{float(s['cv']) * 100:.1f}",
                    fmt(s["min"]),
                    fmt(s["max"]),
                ]
            )
            section_colors.append("#f2f7fb" if model == "All 24" else "#ffffff")

    fig = plt.figure(figsize=(15.2, 7.2), dpi=220)
    fig.patch.set_facecolor("white")
    fig.text(
        0.035,
        0.94,
        "FMN-loading statistics by screening model",
        ha="left",
        va="top",
        fontsize=20,
        fontweight="bold",
    )
    fig.text(
        0.035,
        0.885,
        (
            "24 designs (e126/e127/e128 excluded). Each model: n = 8. "
            "Variance/SD/SEM use sample statistics (ddof=1)."
        ),
        ha="left",
        va="top",
        fontsize=10.5,
        color="#444444",
    )
    fig.text(
        0.035,
        0.035,
        "molar r = (A455/\u03b5455)/(A280_corrected/\u03b5280_design); A455/A230 area ratio uses no extinction coefficient.",
        ha="left",
        va="top",
        fontsize=9,
        color="#555555",
    )

    ax = fig.add_axes([0.03, 0.10, 0.94, 0.76])
    ax.axis("off")
    table = ax.table(
        cellText=table_rows,
        colLabels=HEADERS,
        cellLoc="center",
        colLoc="center",
        colWidths=[0.30, 0.05, 0.08, 0.08, 0.10, 0.08, 0.08, 0.08, 0.08, 0.07],
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#ffffff")
        cell.set_linewidth(0.8)
        if row == 0:
            cell.set_facecolor("#1e3a5f")
            cell.set_text_props(color="white", weight="bold", fontsize=10)
        else:
            cell.set_facecolor(section_colors[row - 1])
            cell.set_text_props(fontsize=10)
            if col == 0 and row % 5 == 1:
                cell.get_text().set_weight("bold")

    for suffix, kwargs in {".png": {"dpi": 300}, ".pdf": {}, ".svg": {}}.items():
        fig.savefig(out_stem.with_suffix(suffix), bbox_inches="tight", **kwargs)
    plt.close(fig)


def main() -> None:
    global DEFAULT_CSV
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    DEFAULT_CSV = args.csv
    render(args.out / "model_stats_molar_r_a230_table")
    print("wrote:", args.out / "model_stats_molar_r_a230_table.{png,pdf,svg}")


if __name__ == "__main__":
    main()
