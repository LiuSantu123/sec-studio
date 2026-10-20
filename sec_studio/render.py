"""Publication-quality rendering + CSV export for parsed Aekta SEC runs.

Everything is driven by a plain-dict ``spec`` produced by the web UI, so the
same spec can be replayed / stored / applied to every imported run at once.
"""

from __future__ import annotations

import io
import csv
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib import font_manager
from matplotlib.ticker import MultipleLocator, AutoMinorLocator, MaxNLocator

import analysis
from akta import Run

__all__ = ["render_figure", "render_screen_bars", "figure_to_bytes", "export_csv",
           "FONTS", "PRESETS", "SCREEN_METRICS"]

# metric key -> (y axis label, short title)
SCREEN_METRICS = {
    "r_monomer": ("FMN : protein (mol/mol)", "FMN loading (monomer peak)"),
    "rho_monomer": ("A455 / A280 area ratio", "A455 / A280 area ratio (monomer peak)"),
    "A455_monomer": ("A455 peak area (mAU·mL)", "A455 peak area"),
    "A280_monomer": ("A280 peak area (mAU·mL)", "A280 peak area"),
    "h_ratio_monomer": ("A455 / A280 peak height", "A455 / A280 peak-height ratio"),
}

# Fonts that actually exist in this environment, mapped to friendly names.
_FONT_MAP = {
    "Arial (Liberation Sans)": "Liberation Sans",
    "Helvetica (Nimbus Sans)": "Nimbus Sans",
    "DejaVu Sans": "DejaVu Sans",
    "PT Sans": "PT Sans",
    "Montserrat": "Montserrat",
    "FreeSans": "FreeSans",
    "Nimbus Roman (Times)": "Nimbus Roman",
    "Liberation Serif": "Liberation Serif",
    "DejaVu Serif": "DejaVu Serif",
    "STIX (Times-like)": "STIXGeneral",
    "Noto Sans SC (中文)": "Noto Sans CJK SC",
    "Noto Serif SC (中文)": "Noto Serif CJK SC",
}
FONTS = list(_FONT_MAP.keys())

PRESETS = {
    "science": {"label": "Science (single column)", "width": 85, "height": 65},
    "science-1.5": {"label": "Science (1.5 column)", "width": 120, "height": 80},
    "nature": {"label": "Nature (single column)", "width": 89, "height": 70},
    "cell": {"label": "Cell (single column)", "width": 84, "height": 70},
    "square": {"label": "Square", "width": 90, "height": 90},
    "wide": {"label": "Wide / 2-column", "width": 170, "height": 90},
}

_X_LABELS = {
    "volume": "Elution volume (mL)",
    "time": "Time (min)",
    "cv": "Elution volume (CV)",
}
_X_RANGES = {"volume": [0.0, 25.0], "time": [0.0, 32.0], "cv": [0.0, 1.2]}


# --------------------------------------------------------------------------- #
# Signal processing
# --------------------------------------------------------------------------- #
def _moving_average(y: np.ndarray, window: int) -> np.ndarray:
    window = max(1, int(window))
    if window <= 1 or window >= y.size:
        return y
    if window % 2 == 0:
        window += 1
    pad = window // 2
    ypad = np.pad(y, pad, mode="edge")
    kernel = np.ones(window) / window
    return np.convolve(ypad, kernel, mode="valid")


def _x_array(curve, x_kind: str, column_volume: Optional[float]) -> np.ndarray:
    return curve.x(x_kind, column_volume)


def _process_series(y: np.ndarray, x: np.ndarray, s: dict) -> np.ndarray:
    y = np.asarray(y, dtype=np.float64).copy()
    sm = int(s.get("smooth") or 0)
    if sm > 1:
        y = _moving_average(y, sm)
    base = s.get("baseline", "none")
    if base == "min":
        y = y - np.nanmin(y)
    elif base == "start":
        frac = float(s.get("baseline_frac", 0.05) or 0.05)
        k = max(1, int(len(y) * frac))
        y = y - np.nanmean(y[:k])
    elif base == "linear":
        frac = float(s.get("baseline_frac", 0.05) or 0.05)
        k = max(2, int(len(y) * frac))
        xb, yb = x[:k], y[:k]
        if np.ptp(xb) > 0:
            m, b = np.polyfit(xb, yb, 1)
            y = y - (m * x + b)
    scale = s.get("scale", "none")
    if scale == "max":
        mx = np.nanmax(y)
        if mx:
            y = y / mx
    elif scale == "minmax":
        mn, mx = np.nanmin(y), np.nanmax(y)
        if mx - mn:
            y = (y - mn) / (mx - mn)
    return y


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _style_axis(ax, spec: dict, *, ylabel: str, y_color: str):
    a = spec.get("axes", {})
    fig = spec.get("figure", {})
    base = float(fig.get("base_size", 8))
    lw = float(a.get("spine_width", 0.8))
    tdir = a.get("tick_dir", "out")
    tlen = float(a.get("tick_len", 3.0))
    tw = float(a.get("tick_width", 0.8))
    tls = a.get("tick_label_size")
    tls = float(tls) if tls else base * 0.95
    lsz = a.get("label_size")
    lsz = float(lsz) if lsz else base * 1.05

    for side, spine in ax.spines.items():
        visible = True
        if side == "top":
            visible = bool(a.get("spine_top", False))
        if side == "right":
            visible = bool(a.get("spine_right", False))
        spine.set_visible(visible)
        spine.set_linewidth(lw)
        spine.set_color("#000000")

    ax.tick_params(direction=tdir, length=tlen, width=tw, labelsize=tls,
                   color="#000000", labelcolor=y_color, top=bool(a.get("spine_top", False)),
                   right=bool(a.get("spine_right", False)))
    ax.set_ylabel(ylabel, fontsize=lsz, color=y_color)
    ax.xaxis.label.set_size(lsz)
    if a.get("grid"):
        ax.grid(True, linestyle=a.get("grid_ls", ":"),
                color=a.get("grid_color", "#d9d9d9"), linewidth=0.6, alpha=0.9)
        ax.set_axisbelow(True)


def _apply_locators(ax, spec: dict, x_kind: str, x_range, y_range):
    a = spec.get("axes", {})
    if x_range:
        lo, hi = x_range[0], x_range[1]
        if lo is not None:
            ax.set_xlim(left=float(lo))
        if hi is not None:
            ax.set_xlim(right=float(hi))
    if a.get("x_major"):
        ax.xaxis.set_major_locator(MultipleLocator(float(a["x_major"])))
    if a.get("x_minor"):
        ax.xaxis.set_minor_locator(MultipleLocator(float(a["x_minor"])))
    elif a.get("x_minor_n"):
        ax.xaxis.set_minor_locator(AutoMinorLocator(int(a["x_minor_n"])))
    if a.get("y_major"):
        ax.yaxis.set_major_locator(MultipleLocator(float(a["y_major"])))
    if a.get("y_minor"):
        ax.yaxis.set_minor_locator(MultipleLocator(float(a["y_minor"])))
    elif a.get("y_minor_n"):
        ax.yaxis.set_minor_locator(AutoMinorLocator(int(a["y_minor_n"])))
    if y_range:
        lo, hi = y_range[0], y_range[1]
        if lo is not None:
            ax.set_ylim(bottom=float(lo))
        if hi is not None:
            ax.set_ylim(top=float(hi))
    if a.get("x_log"):
        ax.set_xscale("log")
    if a.get("y_log"):
        ax.set_yscale("log")
    if a.get("invert_x"):
        ax.invert_xaxis()


def render_figure(spec: dict, runs: Dict[str, Run]) -> Figure:
    fig_cfg = spec.get("figure", {})
    ax_cfg = spec.get("axes", {})
    leg_cfg = spec.get("legend", {})
    sec_cfg = spec.get("secondary", {})
    series = [s for s in spec.get("series", []) if s.get("show", True)]

    font_name = _FONT_MAP.get(fig_cfg.get("font", ""), fig_cfg.get("font") or "DejaVu Sans")
    base = float(fig_cfg.get("base_size", 8))

    matplotlib.rcParams.update({
        "font.family": font_name,
        "font.size": base,
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
    })

    w_in = float(fig_cfg.get("width_mm", 85)) / 25.4
    h_in = float(fig_cfg.get("height_mm", 65)) / 25.4
    fig = plt.figure(figsize=(w_in, h_in), dpi=float(fig_cfg.get("dpi", 300)))

    bg = fig_cfg.get("bg", "#ffffff")
    transparent = bool(fig_cfg.get("transparent", False))
    fig.patch.set_facecolor(bg)
    fig.patch.set_alpha(0.0 if transparent else 1.0)

    left = float(fig_cfg.get("margin_left", 0.16))
    right = 1.0 - float(fig_cfg.get("margin_right", 0.04))
    bottom = float(fig_cfg.get("margin_bottom", 0.17))
    top = 1.0 - float(fig_cfg.get("margin_top", 0.12))
    ax = fig.add_axes([left, bottom, right - left, top - bottom])
    ax.set_facecolor(bg)
    ax.patch.set_alpha(0.0 if transparent else 1.0)

    x_kind = ax_cfg.get("x_kind", "volume")
    need_secondary = sec_cfg.get("show") and any(s.get("axis") == "right" for s in series)
    ax2 = ax.twinx() if need_secondary else None

    handles, labels = [], []
    used_right = False
    for s in series:
        run = runs.get(s.get("run"))
        if run is None:
            continue
        curve = run.curves.get(s.get("curve"))
        if curve is None:
            continue
        x = _x_array(curve, x_kind, run.meta.get("column_volume"))
        y = _process_series(curve.y, x, s)
        deriv = int(s.get("deriv") or 0)
        if deriv:
            y = analysis.derivative(y, x, deriv, smooth=int(s.get("deriv_smooth") or 0))
        target = ax2 if (ax2 is not None and s.get("axis") == "right") else ax
        if target is ax2:
            used_right = True
        label = s.get("label") or (f"{run.name} {curve.label}" if s.get("auto_label", True) else curve.label)
        ln, = target.plot(
            x, y,
            color=s.get("color", "#333333"),
            lw=float(s.get("lw", 1.5)),
            ls=s.get("ls", "-"),
            alpha=float(s.get("alpha", 1.0)),
            solid_capstyle="round",
            label=label,
            zorder=float(s.get("z", 2)),
        )
        handles.append(ln)
        labels.append(label)

    # axes labels / ranges
    xlabel = ax_cfg.get("x_label") or _X_LABELS.get(x_kind, "x")
    ylabel = ax_cfg.get("y_label") or _ylabel_for(series, runs)
    left_color = "#000000"
    _style_axis(ax, spec, ylabel=ylabel, y_color=left_color)
    ax.set_xlabel(xlabel, fontsize=float(ax_cfg.get("label_size") or base * 1.05))

    xr = ax_cfg.get("x_range")
    if not xr or xr[0] is None:
        xr = _X_RANGES.get(x_kind, [None, None])
    _apply_locators(ax, spec, x_kind, xr, ax_cfg.get("y_range"))

    # --- fraction-collection overlay ------------------------------------ #
    fr_cfg = spec.get("fractions") or {}
    if fr_cfg.get("show") and x_kind == "volume":
        rid = fr_cfg.get("run")
        run = runs.get(rid)
        frac = run.fractionation if run else None
        if frac and frac.wells:
            col = fr_cfg.get("color", "#6b8ec9")
            start, end = frac.start_volume, frac.end_volume
            ax.axvspan(start, end, color=col, alpha=float(fr_cfg.get("alpha", 0.10)),
                       zorder=0, linewidth=0)
            if fr_cfg.get("show_ticks", True):
                size = frac.size_ml or 0.5
                edges = np.arange(start, end + size * 0.5, size)
                for e in edges:
                    ax.axvline(e, color=col, lw=0.4, ls=":", alpha=0.55, zorder=1)
            if fr_cfg.get("show_label", True):
                ax.annotate(f"fractions {start:.1f}–{end:.1f} mL ({frac.count}×{frac.size_ml:g})",
                            xy=(0.5, -0.27), xycoords="axes fraction", ha="center", va="top",
                            fontsize=base * 0.78, color=col)
            if frac.waste_volume:
                ax.axvline(frac.waste_volume, color="#c0392b", lw=0.7, ls="--",
                           alpha=0.7, zorder=1)

    # --- peak overlays --------------------------------------------------- #
    for pk in spec.get("peaks", []):
        col = pk.get("color", "#c0392b")
        ax.axvspan(pk["x0"], pk["x1"], color=col, alpha=float(pk.get("alpha", 0.12)),
                   zorder=0, linewidth=0)
        if pk.get("label"):
            ax.annotate(pk["label"], xy=(pk["top"], pk.get("yshow", 0)),
                        xytext=(0, 6), textcoords="offset points",
                        ha="center", va="bottom", fontsize=base * 0.72, color=col)

    # --- design-screen monomer windows ----------------------------------- #
    for sw in spec.get("screen_windows", []):
        col = sw.get("color", "#7f8c8d")
        ax.axvspan(sw["x0"], sw["x1"], color=col, alpha=0.10, zorder=0, linewidth=0)
        ax.axvline(sw["x0"], color=col, lw=0.5, ls=":", alpha=0.6, zorder=1)
        ax.axvline(sw["x1"], color=col, lw=0.5, ls=":", alpha=0.6, zorder=1)

    if ax2 is not None and used_right:
        y2label = sec_cfg.get("y_label") or ""
        _style_axis(ax2, spec, ylabel=y2label, y_color=sec_cfg.get("y_color", "#000000"))
        ax2.spines["right"].set_visible(True)
        if sec_cfg.get("y_range"):
            lo, hi = sec_cfg["y_range"][0], sec_cfg["y_range"][1]
            if lo is not None:
                ax2.set_ylim(bottom=float(lo))
            if hi is not None:
                ax2.set_ylim(top=float(hi))
        if sec_cfg.get("y_major"):
            ax2.yaxis.set_major_locator(MultipleLocator(float(sec_cfg["y_major"])))
        ax2.tick_params(colors=sec_cfg.get("y_color", "#000000"))
        ax2.yaxis.label.set_color(sec_cfg.get("y_color", "#000000"))

    # title / subtitle / panel
    title = fig_cfg.get("title") or ""
    subtitle = fig_cfg.get("subtitle") or ""
    panel = fig_cfg.get("panel") or ""
    ty = 1.0 - float(fig_cfg.get("title_y", 0.02))
    if title:
        fig.text(0.5, ty, title, ha="center", va="bottom",
                 fontsize=float(fig_cfg.get("title_size", base * 1.25)),
                 fontweight="bold" if fig_cfg.get("title_bold", True) else "normal")
    if subtitle:
        sy = ty - float(fig_cfg.get("subtitle_gap", 0.055))
        fig.text(0.5, sy, subtitle, ha="center", va="bottom",
                 fontsize=float(fig_cfg.get("subtitle_size", base)))
    if panel:
        fig.text(left - 0.14, top + 0.015, panel, ha="left", va="bottom",
                 fontsize=float(fig_cfg.get("panel_size", base * 1.4)), fontweight="bold")

    # legend
    if leg_cfg.get("show", True) and labels:
        pos = leg_cfg.get("pos", "upper right")
        loc = _legend_loc(pos)
        leg = ax.legend(
            handles, labels, loc=loc,
            frameon=bool(leg_cfg.get("frame", False)),
            fontsize=float(leg_cfg.get("font_size") or base * 0.9),
            ncol=int(leg_cfg.get("ncol", 1)),
            handlelength=float(leg_cfg.get("handlelength", 1.6)),
            handletextpad=float(leg_cfg.get("handletextpad", 0.5)),
            borderaxespad=float(leg_cfg.get("borderaxespad", 0.4)),
            labelspacing=float(leg_cfg.get("labelspacing", 0.3)),
            title=leg_cfg.get("title") or None,
        )
        if leg_cfg.get("title"):
            leg.get_title().set_fontsize(float(leg_cfg.get("font_size") or base * 0.9))
        leg.get_frame().set_linewidth(0.6)
        leg.get_frame().set_edgecolor("#000000")

    if fig_cfg.get("annotate_size"):
        fig.text(0.995, 0.005, f"{fig_cfg.get('width_mm', 85):g} × {fig_cfg.get('height_mm', 65):g} mm",
                 ha="right", va="bottom", fontsize=base * 0.8, color="#9aa3ad")

    return fig


def _ylabel_for(series, runs) -> str:
    units = []
    for s in series:
        if s.get("axis") == "right":
            continue
        run = runs.get(s.get("run"))
        if not run:
            continue
        c = run.curves.get(s.get("curve"))
        if c and c.unit and c.unit not in units:
            units.append(c.unit)
    if len(units) == 1:
        return f"Absorbance ({units[0]})" if units[0] == "mAU" else f"Signal ({units[0]})"
    return "Absorbance (mAU)"


def _legend_loc(pos: str):
    return {
        "upper right": "upper right",
        "upper left": "upper left",
        "lower right": "lower right",
        "lower left": "lower left",
        "center right": "center right",
        "center left": "center left",
        "upper center": "upper center",
        "lower center": "lower center",
    }.get(pos, "best")


def figure_to_bytes(fig: Figure, fmt: str = "png", dpi: Optional[float] = None,
                    transparent: bool = False) -> bytes:
    buf = io.BytesIO()
    save_kw = dict(format=fmt, bbox_inches="tight", pad_inches=0.02,
                   facecolor=fig.get_facecolor())
    if dpi:
        save_kw["dpi"] = dpi
    if fmt in ("png", "tiff", "jpg"):
        save_kw["transparent"] = transparent
    fig.savefig(buf, **save_kw)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Design-screen ranking bar chart
# --------------------------------------------------------------------------- #
def render_screen_bars(rows: List[dict], spec: Optional[dict] = None,
                       metric: str = "r_monomer",
                       colors: Optional[List[str]] = None) -> Figure:
    """Publication-style bar chart ranking the screened designs.

    ``rows`` come from ``analysis.screen_runs`` (or POST /api/screen).
    """
    spec = spec or {}
    fig_cfg = spec.get("figure", {})
    ax_cfg = spec.get("axes", {})
    font_name = _FONT_MAP.get(fig_cfg.get("font", ""), fig_cfg.get("font") or "DejaVu Sans")
    base = float(fig_cfg.get("base_size", 8))
    matplotlib.rcParams.update({
        "font.family": font_name, "font.size": base,
        "axes.unicode_minus": False, "pdf.fonttype": 42, "ps.fonttype": 42,
        "svg.fonttype": "none",
    })

    ylabel, short = SCREEN_METRICS.get(metric, (metric, metric))
    order = sorted(range(len(rows)),
                   key=lambda i: (rows[i].get(metric) if rows[i].get(metric) == rows[i].get(metric) else -1),
                   reverse=True)
    names = [str(rows[i].get("run", i)) for i in order]
    vals = [float(rows[i].get(metric) or 0) for i in order]

    w_in = float(fig_cfg.get("width_mm", 85)) / 25.4
    h_in = float(fig_cfg.get("height_mm", 65)) / 25.4
    # give each bar a sane minimum height
    h_in = max(h_in, 0.42 * len(rows) + 1.0)
    fig = plt.figure(figsize=(w_in, h_in), dpi=float(fig_cfg.get("dpi", 300)))
    bg = fig_cfg.get("bg", "#ffffff")
    fig.patch.set_facecolor(bg)
    ax = fig.add_axes([0.34, 0.16, 0.63, 0.76])
    ax.set_facecolor(bg)

    palette = colors or ["#C0392B"] * len(rows)
    ys = np.arange(len(names))
    bars = ax.barh(ys, vals, color=[palette[i] for i in order], height=0.66,
                   edgecolor="none")
    ax.set_yticks(ys)
    ax.set_yticklabels(names, fontsize=base * 0.95)
    ax.invert_yaxis()
    ax.set_xlabel(ax_cfg.get("x_label") or ylabel, fontsize=base * 1.05)

    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ax.spines.values():
        spine.set_linewidth(float(ax_cfg.get("spine_width", 0.8)))
    ax.tick_params(direction=ax_cfg.get("tick_dir", "out"),
                   length=float(ax_cfg.get("tick_len", 3.0)),
                   width=float(ax_cfg.get("tick_width", 0.8)), labelsize=base * 0.95)
    ax.grid(False)

    span = max(vals) if vals else 1.0
    ax.set_xlim(0, span * 1.18 if span > 0 else 1.0)
    for y, v in zip(ys, vals):
        ax.text(v + span * 0.02, y, f"{v:.3f}" if abs(v) < 10 else f"{v:.1f}",
                va="center", ha="left", fontsize=base * 0.85, color="#333333")

    title = fig_cfg.get("title") or short
    if title:
        ax.set_title(title, fontsize=float(fig_cfg.get("title_size", base * 1.2)),
                     fontweight="bold" if fig_cfg.get("title_bold", True) else "normal")
    sub = fig_cfg.get("subtitle")
    if sub:
        fig.text(0.5, 0.955, sub, ha="center", va="bottom", fontsize=base * 0.95)
    return fig


# --------------------------------------------------------------------------- #
# CSV export
# --------------------------------------------------------------------------- #
def export_csv(spec: dict, runs: Dict[str, Run], which: Sequence[dict],
               x_kind: str, x_range, processed: bool = True,
               layout: str = "tidy") -> str:
    """Return CSV text for the selected series, clipped to ``x_range``."""
    lo = float(x_range[0]) if x_range and x_range[0] is not None else None
    hi = float(x_range[1]) if x_range and x_range[1] is not None else None
    cols: List[Tuple[str, np.ndarray, np.ndarray]] = []
    for s in which:
        run = runs.get(s.get("run"))
        if run is None:
            continue
        curve = run.curves.get(s.get("curve"))
        if curve is None:
            continue
        x = _x_array(curve, x_kind, run.meta.get("column_volume"))
        y = _process_series(curve.y, x, s) if processed else np.asarray(curve.y)
        if lo is not None or hi is not None:
            m = np.ones(x.shape, dtype=bool)
            if lo is not None:
                m &= x >= lo
            if hi is not None:
                m &= x <= hi
            x, y = x[m], y[m]
        name = s.get("label") or f"{run.name} {curve.label}"
        cols.append((name, x, y))

    out = io.StringIO()
    w = csv.writer(out)
    if layout == "wide":
        w.writerow(["x"] + [c[0] for c in cols])
        # resample all series on a shared grid
        if cols:
            xmin = min(c[1].min() for c in cols)
            xmax = max(c[1].max() for c in cols)
            n = max(len(c[1]) for c in cols)
            grid = np.linspace(xmin, xmax, n)
            interp = []
            for _, x, y in cols:
                o = np.argsort(x)
                interp.append(np.interp(grid, x[o], y[o]))
            for i, xv in enumerate(grid):
                w.writerow([f"{xv:.6g}"] + [f"{interp[j][i]:.6g}" for j in range(len(cols))])
    else:
        w.writerow(["run", "series", "curve", x_kind, "value", "unit"])
        for (name, x, y), s in zip(cols, which):
            curve = runs[s["run"]].curves[s["curve"]] if runs.get(s.get("run")) else None
            unit = curve.unit if curve else ""
            for xv, yv in zip(x, y):
                w.writerow([s.get("label") or name, name, s.get("curve", ""),
                            f"{xv:.6g}", f"{yv:.6g}", unit])
    return out.getvalue()
