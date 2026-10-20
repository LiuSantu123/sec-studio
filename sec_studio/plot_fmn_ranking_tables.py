#!/usr/bin/env python3
"""Redraw the FMN-loading ranking tables used for the SEC review.

Outputs (PNG/PDF/SVG + tidy CSV):
  data/fmn_ranking/ev5t1_fmn_affinity_ranking_table.*
      Non-normalized molar-loading ranking.  Includes the corrected ev4
      AffinCraft designs e98/e103/e104 and excludes e126/e127/e128.

  data/fmn_ranking/ev5t1_plus_corrected_ev4_fmn_affinity_ranking_table.*
      Normalized ranking for the same 24-design set.  Each design is divided
      by its own whole-chromatogram A280 peak before the monomer-window
      values are compared.  The A455/A280 ratio uses only the monomer peak
      and is sorted descending.

  data/fmn_ranking/ev5t1_plus_corrected_ev4_fmn_affinity_ranking_table_normalized_molar_r.*
      Same normalized A280/A455 values, then molar r is recomputed with the
      design-specific epsilon280 (Pace 1995) and sorted by molar r.

The numeric inputs are the already-audited tables:
  data/fmn_ranking/fmn_ev_ranking.csv
  data/fmn_ranking/normalized_sec_ranking_24designs.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RANK_CSV = ROOT / "data/fmn_ranking/fmn_ev_ranking.csv"
DEFAULT_NORM_CSV = ROOT / "data/fmn_ranking/normalized_sec_ranking_24designs.csv"
DEFAULT_OUT = ROOT / "data/fmn_ranking"

SOURCE_LABEL = {
    "own_model": "AffinCraft",
    "af3": "AF3",
    "boltz2": "Boltz2 affinity",
}
METHOD_COLOR = {
    "AffinCraft": "#dbe9f6",
    "AF3": "#d8f0de",
    "Boltz2 affinity": "#fce8b2",
}

EPS455 = 12500.0
EPS280_FMN = 20000.0

EXCLUDED = {"e126", "e127", "e128"}
REQUIRED_EXTRA = {"e98", "e103", "e104"}


def canon_design(value: str) -> str:
    """Return eNN without zero padding, e.g. e098 -> e98."""
    match = re.search(r"(\d+)", str(value))
    return f"e{int(match.group(1))}" if match else str(value)


def as_float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def fmt(value, digits: int = 1) -> str:
    if value is None:
        return "-"
    if digits == 0:
        return f"{value:.0f}"
    return f"{value:.{digits}f}"


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def resolve_source(row: dict, normalized: dict) -> str:
    source = (row.get("source") or normalized.get("source") or "").strip()
    return SOURCE_LABEL.get(source, source or "?")


def build_non_normalized(rank_rows: list[dict], selected: set[str]) -> list[dict]:
    by_design: dict[str, dict] = {}
    for row in rank_rows:
        design = canon_design(row.get("design", ""))
        if design in selected:
            # Keep rows usable for molar r; the corrected ev4/ev5 rows are unique.
            if as_float(row.get("r_design")) is not None:
                by_design[design] = row

    missing = selected - set(by_design)
    if missing:
        raise SystemExit(f"missing molar-r rows for: {sorted(missing)}")

    out = []
    for design, row in by_design.items():
        a280_area = as_float(row.get("A280_monomer"))
        a455_area = as_float(row.get("A455_monomer"))
        a280_peak = as_float(row.get("h_A280"))
        a455_peak = as_float(row.get("h_A455"))
        out.append(
            {
                "design": design,
                "run": row.get("run", ""),
                "source": SOURCE_LABEL.get(row.get("source", ""), row.get("source", "?")),
                "a280_peak": a280_peak,
                "a455_peak": a455_peak,
                "peak_ratio": (a455_peak / a280_peak) if a280_peak else None,
                "a280_area": a280_area,
                "a455_area": a455_area,
                "area_ratio": (a455_area / a280_area) if a280_area else None,
                "a280_corrected": as_float(row.get("A280_corrected")),
                "eps280_design": as_float(row.get("eps280_design")),
                "r_design": as_float(row.get("r_design")),
            }
        )
    out.sort(key=lambda item: (-item["r_design"], item["design"]))
    return out


def build_normalized_original_rank(non_norm: list[dict]) -> dict[str, int]:
    ordered = sorted(non_norm, key=lambda item: (-item["r_design"], item["design"]))
    return {row["design"]: rank for rank, row in enumerate(ordered, start=1)}


def build_normalized(
    norm_rows: list[dict],
    original_rank: dict[str, int],
    source_by_design: dict[str, str],
) -> list[dict]:
    present = {canon_design(row.get("design", "")) for row in norm_rows}
    if present & EXCLUDED:
        raise SystemExit(f"normalized input still contains excluded designs: {sorted(present & EXCLUDED)}")
    if not REQUIRED_EXTRA <= present:
        raise SystemExit(f"normalized input is missing corrected ev4 designs: {sorted(REQUIRED_EXTRA - present)}")

    out = []
    for row in norm_rows:
        design = canon_design(row.get("design", ""))
        if design in EXCLUDED:
            continue
        out.append(
            {
                "design": design,
                "run": row.get("run", ""),
                "source": source_by_design.get(design, row.get("source", "")),
                "a280_global_peak": as_float(row.get("a280_global_peak_mAU")),
                "a280_peak_norm": as_float(row.get("a280_peak_norm")),
                "a455_peak_norm": as_float(row.get("a455_peak_norm")),
                "peak_ratio_norm": as_float(row.get("peak_ratio_norm")),
                "a280_area_norm": as_float(row.get("a280_area_norm")),
                "a455_area_norm": as_float(row.get("a455_area_norm")),
                "area_ratio_norm": as_float(row.get("area_ratio_norm")),
                "r_design": as_float(row.get("r_design")),
                "original_r_rank": original_rank.get(design),
            }
        )
    out.sort(key=lambda item: (-item["peak_ratio_norm"], item["design"]))
    return out


def build_normalized_molar(
    norm_rows: list[dict],
    source_by_design: dict[str, str],
    eps_by_design: dict[str, float],
) -> list[dict]:
    """Normalize monomer areas by each run's global A280 peak, then compute
    molar r with the design-specific epsilon280.

    Because both A280 and A455 are divided by the same global peak, the
    normalization cancels in the ratio, so molar r is identical to the
    non-normalized table; only the displayed A280/A455 values are normalized.
    """
    present = {canon_design(row.get("design", "")) for row in norm_rows}
    if present & EXCLUDED:
        raise SystemExit(f"normalized input still contains excluded designs: {sorted(present & EXCLUDED)}")
    if not REQUIRED_EXTRA <= present:
        raise SystemExit(f"normalized input is missing corrected ev4 designs: {sorted(REQUIRED_EXTRA - present)}")

    corr = EPS280_FMN / EPS455
    out = []
    for row in norm_rows:
        design = canon_design(row.get("design", ""))
        if design in EXCLUDED:
            continue
        a280n = as_float(row.get("a280_area_norm"))
        a455n = as_float(row.get("a455_area_norm"))
        eps = eps_by_design.get(design)
        a280cn = (a280n - corr * a455n) if a280n is not None and a455n is not None else None
        rnorm = (
            (a455n / EPS455) / (a280cn / eps)
            if a455n is not None and a280cn and eps
            else None
        )
        out.append(
            {
                "design": design,
                "run": row.get("run", ""),
                "source": source_by_design.get(design, row.get("source", "")),
                "a280_global_peak": as_float(row.get("a280_global_peak_mAU")),
                "a280_area_norm": a280n,
                "a455_area_norm": a455n,
                "a280_corrected_norm": a280cn,
                "eps280_design": eps,
                "r_design": as_float(row.get("r_design")),
                "r_norm": rnorm,
            }
        )
    out.sort(key=lambda item: (-item["r_norm"], item["design"]))
    return out


def style_table(table, row_colors: list[str], header_size: float, body_size: float) -> None:
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#ffffff")
        cell.set_linewidth(0.8)
        if row == 0:
            cell.set_facecolor("#1e3a5f")
            cell.set_text_props(color="white", weight="bold", fontsize=header_size)
        else:
            cell.set_facecolor(row_colors[row - 1])
            cell.set_text_props(fontsize=body_size)
            if col == 0:
                cell.get_text().set_weight("bold")


def add_method_legend(fig) -> None:
    handles = [
        Patch(facecolor=METHOD_COLOR[label], edgecolor="white", label=label)
        for label in ("AffinCraft", "AF3", "Boltz2 affinity")
    ]
    fig.legend(
        handles=handles,
        loc="lower right",
        bbox_to_anchor=(0.975, 0.004),
        ncol=3,
        frameon=False,
        fontsize=8.8,
        handlelength=1.4,
    )


def draw_table(
    *,
    title: str,
    subtitle: str,
    note: str,
    headers: list[str],
    rows: list[list[str]],
    colors: list[str],
    col_widths: list[float],
    out_stem: Path,
    figsize: tuple[float, float],
    table_font: float,
    header_font: float,
) -> None:
    fig = plt.figure(figsize=figsize, dpi=220)
    fig.patch.set_facecolor("white")
    fig.text(0.035, 0.965, title, ha="left", va="top", fontsize=20, fontweight="bold")
    fig.text(0.035, 0.925, subtitle, ha="left", va="top", fontsize=10.5, color="#444444")

    ax = fig.add_axes([0.025, 0.095, 0.95, 0.80])
    ax.axis("off")
    table = ax.table(
        cellText=rows,
        colLabels=headers,
        cellLoc="center",
        colLoc="center",
        colWidths=col_widths,
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(table_font)
    style_table(table, colors, header_font, table_font)

    fig.text(
        0.035,
        0.045,
        textwrap.fill(note, 135),
        ha="left",
        va="top",
        fontsize=8.8,
        color="#555555",
        linespacing=1.25,
    )
    add_method_legend(fig)

    for suffix, kwargs in {
        ".png": {"dpi": 300},
        ".pdf": {},
        ".svg": {},
    }.items():
        fig.savefig(out_stem.with_suffix(suffix), bbox_inches="tight", **kwargs)
    plt.close(fig)


def write_tidy_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rank-csv", type=Path, default=DEFAULT_RANK_CSV)
    parser.add_argument("--norm-csv", type=Path, default=DEFAULT_NORM_CSV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    rank_rows = load_csv(args.rank_csv)
    norm_rows = load_csv(args.norm_csv)

    selected = {canon_design(row["design"]) for row in norm_rows} - EXCLUDED
    if not REQUIRED_EXTRA <= selected:
        raise SystemExit("selected design set is missing e98/e103/e104")

    non_norm = build_non_normalized(rank_rows, selected)
    if len(non_norm) != 24:
        raise SystemExit(f"expected 24 non-normalized rows, got {len(non_norm)}")
    original_rank = build_normalized_original_rank(non_norm)
    source_by_design = {row["design"]: row["source"] for row in non_norm}
    normalized = build_normalized(norm_rows, original_rank, source_by_design)
    if len(normalized) != 24:
        raise SystemExit(f"expected 24 normalized rows, got {len(normalized)}")
    eps_by_design = {row["design"]: row["eps280_design"] for row in non_norm}
    normalized_molar = build_normalized_molar(norm_rows, source_by_design, eps_by_design)
    if len(normalized_molar) != 24:
        raise SystemExit(f"expected 24 normalized-molar rows, got {len(normalized_molar)}")

    args.out.mkdir(parents=True, exist_ok=True)

    # Non-normalized molar-loading table.
    nn_headers = [
        "Rank",
        "Design",
        "A280 peak\n(mAU)",
        "A455 peak\n(mAU)",
        "Peak ratio\nA455/A280",
        "A280 area\n(mAU\u00b7mL)",
        "A455 area\n(mAU\u00b7mL)",
        "Area ratio\nA455/A280",
        "Molar r\n(FMN/protein)",
        "Screening method",
    ]
    nn_rows = [
        [
            str(rank),
            row["design"],
            fmt(row["a280_peak"], 1),
            fmt(row["a455_peak"], 1),
            fmt(row["peak_ratio"], 3),
            fmt(row["a280_area"], 1),
            fmt(row["a455_area"], 1),
            fmt(row["area_ratio"], 3),
            fmt(row["r_design"], 3),
            row["source"],
        ]
        for rank, row in enumerate(non_norm, start=1)
    ]
    draw_table(
        title="SEC FMN affinity / loading ranking from SEC",
        subtitle=(
            "No curve normalization; baseline-corrected monomer-window values. "
            "Sorted by molar loading r. e98/e103/e104 included; e126/e127/e128 excluded."
        ),
        note=(
            "A280/A455 peak values are baseline-corrected apex heights. "
            "Areas use the common monomer window and are not normalized."
        ),
        headers=nn_headers,
        rows=nn_rows,
        colors=[METHOD_COLOR[row["source"]] for row in non_norm],
        col_widths=[0.055, 0.075, 0.10, 0.10, 0.095, 0.115, 0.115, 0.09, 0.105, 0.15],
        out_stem=args.out / "ev5t1_fmn_affinity_ranking_table",
        figsize=(15.6, 10.2),
        table_font=9.7,
        header_font=9.7,
    )
    write_tidy_csv(
        args.out / "ev5t1_fmn_affinity_ranking_table.csv",
        [
            "rank",
            "design",
            "run",
            "source",
            "a280_peak_mAU",
            "a455_peak_mAU",
            "peak_ratio_A455_A280",
            "a280_area_mAU_mL",
            "a455_area_mAU_mL",
            "area_ratio_A455_A280",
            "molar_r_FMN_protein",
            "sort_key",
        ],
        [
            {
                "rank": rank,
                "design": row["design"],
                "run": row["run"],
                "source": row["source"],
                "a280_peak_mAU": row["a280_peak"],
                "a455_peak_mAU": row["a455_peak"],
                "peak_ratio_A455_A280": row["peak_ratio"],
                "a280_area_mAU_mL": row["a280_area"],
                "a455_area_mAU_mL": row["a455_area"],
                "area_ratio_A455_A280": row["area_ratio"],
                "molar_r_FMN_protein": row["r_design"],
                "sort_key": "r_design descending",
            }
            for rank, row in enumerate(non_norm, start=1)
        ],
    )

    # Normalized table: same 24 designs, divided by each design's global A280 peak.
    # The displayed values and the A455/A280 ratio use only the monomer peak.
    norm_headers = [
        "Rank",
        "Design",
        "Norm.\nA280 peak",
        "Norm.\nA455 peak",
        "Monomer peak\nA455/A280",
        "Original\nr rank",
        "Original r\n(FMN/protein)",
        "Screening method",
    ]
    norm_table_rows = [
        [
            str(rank),
            row["design"],
            fmt(row["a280_peak_norm"], 4),
            fmt(row["a455_peak_norm"], 4),
            fmt(row["peak_ratio_norm"], 4),
            fmt(row["original_r_rank"], 0),
            fmt(row["r_design"], 3),
            SOURCE_LABEL.get(row["source"], row["source"] or "?"),
        ]
        for rank, row in enumerate(normalized, start=1)
    ]
    draw_table(
        title="Normalized SEC FMN monomer-peak ranking: 24 designs",
        subtitle=(
            "Each design was divided by its own whole-chromatogram A280 peak. "
            "The A280 and A455 columns and the A455/A280 ratio use only the monomer peak. "
            "Sorted by monomer-peak A455/A280. e126/e127/e128 excluded."
        ),
        note=(
            "Normalized values are relative units, not mAU. A455/A280 uses monomer-peak "
            "A455 divided by monomer-peak A280. Original r rank is from the non-normalized table."
        ),
        headers=norm_headers,
        rows=norm_table_rows,
        colors=[METHOD_COLOR[SOURCE_LABEL.get(row["source"], row["source"] or "?")] for row in normalized],
        col_widths=[0.07, 0.08, 0.12, 0.12, 0.16, 0.10, 0.13, 0.22],
        out_stem=args.out / "ev5t1_plus_corrected_ev4_fmn_affinity_ranking_table",
        figsize=(15.4, 10.2),
        table_font=9.5,
        header_font=9.3,
    )
    write_tidy_csv(
        args.out / "ev5t1_plus_corrected_ev4_fmn_affinity_ranking_table.csv",
        [
            "norm_peak_rank",
            "design",
            "run",
            "source",
            "a280_global_peak_mAU",
            "a280_peak_norm",
            "a455_peak_norm",
            "peak_ratio_norm",
            "a280_area_norm",
            "a455_area_norm",
            "area_ratio_norm",
            "original_r_rank",
            "original_r_FMN_protein",
            "sort_key",
        ],
        [
            {
                "norm_peak_rank": rank,
                "design": row["design"],
                "run": row["run"],
                "source": SOURCE_LABEL.get(row["source"], row["source"] or "?"),
                "a280_global_peak_mAU": row["a280_global_peak"],
                "a280_peak_norm": row["a280_peak_norm"],
                "a455_peak_norm": row["a455_peak_norm"],
                "peak_ratio_norm": row["peak_ratio_norm"],
                "a280_area_norm": row["a280_area_norm"],
                "a455_area_norm": row["a455_area_norm"],
                "area_ratio_norm": row["area_ratio_norm"],
                "original_r_rank": row["original_r_rank"],
                "original_r_FMN_protein": row["r_design"],
                "sort_key": "monomer-peak A455/A280 descending",
            }
            for rank, row in enumerate(normalized, start=1)
        ],
    )

    # Normalized values + epsilon280-based molar r.
    norm_molar_headers = [
        "Rank",
        "Design",
        "Norm.\nA280 area",
        "Norm.\nA455 area",
        "Norm. A280\ncorrected",
        "Molar r\n(FMN/protein)",
        "\u03b5280 design\n(M\u207b\u00b9\u00b7cm\u207b\u00b9)",
        "Screening method",
    ]
    norm_molar_rows = [
        [
            str(rank),
            row["design"],
            fmt(row["a280_area_norm"], 4),
            fmt(row["a455_area_norm"], 4),
            fmt(row["a280_corrected_norm"], 4),
            fmt(row["r_norm"], 3),
            fmt(row["eps280_design"], 0),
            SOURCE_LABEL.get(row["source"], row["source"] or "?"),
        ]
        for rank, row in enumerate(normalized_molar, start=1)
    ]
    draw_table(
        title="Normalized SEC FMN molar-loading ranking: 24 designs",
        subtitle=(
            "Monomer-window areas were divided by each run's whole-chromatogram A280 peak, "
            "then molar r uses the design-specific \u03b5280 (Pace 1995). "
            "Sorted by molar r. e126/e127/e128 excluded."
        ),
        note=(
            "Normalized values are relative units, not mAU. The shared normalization "
            "cancels in the ratio, so molar r equals the non-normalized table."
        ),
        headers=norm_molar_headers,
        rows=norm_molar_rows,
        colors=[METHOD_COLOR[SOURCE_LABEL.get(row["source"], row["source"] or "?")] for row in normalized_molar],
        col_widths=[0.06, 0.08, 0.12, 0.12, 0.15, 0.13, 0.13, 0.21],
        out_stem=args.out / "ev5t1_plus_corrected_ev4_fmn_affinity_ranking_table_normalized_molar_r",
        figsize=(15.8, 10.2),
        table_font=9.5,
        header_font=9.3,
    )
    write_tidy_csv(
        args.out / "ev5t1_plus_corrected_ev4_fmn_affinity_ranking_table_normalized_molar_r.csv",
        [
            "rank",
            "design",
            "run",
            "source",
            "a280_global_peak_mAU",
            "a280_area_norm",
            "a455_area_norm",
            "a280_corrected_norm",
            "eps280_design",
            "molar_r_FMN_protein",
            "sort_key",
        ],
        [
            {
                "rank": rank,
                "design": row["design"],
                "run": row["run"],
                "source": SOURCE_LABEL.get(row["source"], row["source"] or "?"),
                "a280_global_peak_mAU": row["a280_global_peak"],
                "a280_area_norm": row["a280_area_norm"],
                "a455_area_norm": row["a455_area_norm"],
                "a280_corrected_norm": row["a280_corrected_norm"],
                "eps280_design": row["eps280_design"],
                "molar_r_FMN_protein": row["r_norm"],
                "sort_key": "molar r (normalized areas + epsilon280) descending",
            }
            for rank, row in enumerate(normalized_molar, start=1)
        ],
    )

    print("wrote non-normalized table:", args.out / "ev5t1_fmn_affinity_ranking_table.{png,pdf,svg,csv}")
    print("wrote normalized table:", args.out / "ev5t1_plus_corrected_ev4_fmn_affinity_ranking_table.{png,pdf,svg,csv}")
    print("wrote normalized molar-r table:", args.out / "ev5t1_plus_corrected_ev4_fmn_affinity_ranking_table_normalized_molar_r.{png,pdf,svg,csv}")
    print("non-normalized ranking:")
    print("  " + " > ".join(row["design"] for row in non_norm))
    print("normalized monomer-peak A455/A280 ranking:")
    print("  " + " > ".join(row["design"] for row in normalized))
    print("normalized molar-r ranking:")
    print("  " + " > ".join(row["design"] for row in normalized_molar))


if __name__ == "__main__":
    main()
