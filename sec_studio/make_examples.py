#!/usr/bin/env python3
"""Render a couple of ready-to-look-at examples from a folder of Aekta zips."""
import glob, os, sys
import akta, render
import analysis

def load(folder):
    runs = {}
    for zp in sorted(glob.glob(os.path.join(folder, "*.zip"))):
        r = akta.parse_result_zip(open(zp, "rb").read(), source=os.path.basename(zp))
        runs[r.id] = r
    return runs

def main(folder, outdir):
    os.makedirs(outdir, exist_ok=True)
    runs = load(folder)
    if not runs:
        print("no zips found in", folder); return
    ids = list(runs)

    base_fig = {
        "width_mm": 85, "height_mm": 65, "dpi": 600, "bg": "#ffffff", "transparent": False,
        "font": "Arial (Liberation Sans)", "base_size": 8, "title": "", "subtitle": "",
        "panel": "", "title_size": 10, "title_bold": True, "subtitle_size": 8, "panel_size": 11,
        "margin_left": 0.17, "margin_right": 0.05, "margin_bottom": 0.18, "margin_top": 0.10,
    }
    base_axes = {
        "x_kind": "volume", "x_range": [0, 24], "y_range": [0, None],
        "x_label": "Elution volume (mL)", "y_label": "Absorbance (mAU)",
        "x_major": 5, "x_minor": 1, "y_major": None, "y_minor": None,
        "tick_dir": "out", "tick_len": 3, "tick_width": 0.8, "tick_label_size": None,
        "spine_width": 0.8, "spine_top": False, "spine_right": False,
        "grid": False, "grid_ls": ":", "grid_color": "#d9d9d9",
        "label_size": None, "x_log": False, "y_log": False, "invert_x": False,
    }
    curves = {"lw": 1.6, "ls": "-", "alpha": 1.0, "baseline": "start",
              "baseline_frac": 0.05, "scale": "none", "smooth": 0}
    legend = {"show": True, "pos": "upper right", "frame": False, "font_size": 7.5, "ncol": 1, "title": ""}
    secondary = {"show": False, "y_label": "", "y_range": [None, None], "y_color": "#000000", "y_major": None}

    pal = ["#C0392B", "#2471A3", "#1E8449", "#8E44AD", "#D68910", "#17A589", "#CB4335"]

    # --- Example 1 : A280 overlay of every run -----------------------------
    bych = {rid: {c.channel: c.name for c in runs[rid].uv_curves()} for rid in ids}
    series = [dict(run=rid, curve=bych[rid]["A280"], label=rid, show=True, color=pal[i % len(pal)],
                   lw=1.6, ls="-", alpha=1.0, axis="left", baseline="start", baseline_frac=0.05,
                   scale="none", smooth=0) for i, rid in enumerate(ids) if "A280" in bych[rid]]
    spec = {"figure": dict(base_fig, title="Size-exclusion chromatography",
                           subtitle=runs[ids[0]].meta.get("column", "")),
            "axes": dict(base_axes, y_label="A280 (mAU)"),
            "curves": curves, "legend": legend, "secondary": secondary, "series": series}
    fig = render.render_figure(spec, runs)
    for fmt, dpi in [("png", 600), ("pdf", 600), ("svg", 600)]:
        open(os.path.join(outdir, f"example_A280_overlay.{fmt}"), "wb").write(
            render.figure_to_bytes(fig, fmt=fmt, dpi=dpi))
    import matplotlib.pyplot as plt; plt.close(fig)

    # --- Example 2 : one run, A280 (left) + A230 (right) + A455 ------------
    rid = ids[0]
    ch = bych[rid]
    series2 = [
        dict(run=rid, curve=ch["A280"], label="A280", show=True, color="#C0392B", lw=1.6, ls="-",
             alpha=1.0, axis="left", baseline="start", baseline_frac=0.05, scale="none", smooth=0),
    ]
    if "A230" in ch:
        series2.append(dict(run=rid, curve=ch["A230"], label="A230 (right)", show=True, color="#2471A3",
                            lw=1.2, ls="-", alpha=0.9, axis="right", baseline="start",
                            baseline_frac=0.05, scale="none", smooth=0))
    if "A455" in ch:
        series2.append(dict(run=rid, curve=ch["A455"], label="A455", show=True, color="#1E8449",
                            lw=1.3, ls="-", alpha=0.95, axis="left", baseline="start",
                            baseline_frac=0.05, scale="none", smooth=0))
    # put A280 on the left in mAU, keep A455 small -> ok
    spec2 = {"figure": dict(base_fig, title=rid, panel="A"),
             "axes": dict(base_axes, y_label="A280 (mAU)", x_major=5, x_minor=1),
             "curves": curves, "legend": dict(legend, font_size=6.5),
             "secondary": {"show": True, "y_label": "A230 (mAU)", "y_range": [None, None],
                           "y_color": "#2471A3", "y_major": None},
             "series": series2}
    fig2 = render.render_figure(spec2, runs)
    for fmt, dpi in [("png", 600), ("pdf", 600)]:
        open(os.path.join(outdir, f"example_{rid.replace(' ', '_')}_multichannel.{fmt}"), "wb").write(
            render.figure_to_bytes(fig2, fmt=fmt, dpi=dpi))
    plt.close(fig2)

    # --- Example 3 : CSV of A280, 5-20 mL ----------------------------------
    csv = render.export_csv(spec, runs, series, x_kind="volume", x_range=[5, 20],
                            processed=True, layout="wide")
    open(os.path.join(outdir, "example_A280_5-20mL_wide.csv"), "w").write(csv)
    csv2 = render.export_csv(spec, runs, series, x_kind="volume", x_range=[5, 20],
                             processed=True, layout="tidy")
    open(os.path.join(outdir, "example_A280_5-20mL_tidy.csv"), "w").write(csv2)

    # --- Example 4 : A280 + A455 with fractions and integrated peaks -------
    rid = ids[0]
    ch = bych[rid]
    fseries = [
        dict(run=rid, curve=ch["A280"], label="A280 (protein)", show=True, color="#C0392B",
             lw=1.6, ls="-", alpha=1.0, axis="left", baseline="start", baseline_frac=0.05,
             scale="none", smooth=0, deriv=0),
    ]
    if "A455" in ch:
        fseries.append(dict(run=rid, curve=ch["A455"], label="A455 (FMN)", show=True, color="#2471A3",
                            lw=1.6, ls="-", alpha=1.0, axis="right", baseline="start",
                            baseline_frac=0.05, scale="none", smooth=0, deriv=0))
    peaks, rows = [], []
    for s in fseries:
        run = runs[s["run"]]
        curve = run.curves[s["curve"]]
        x = curve.volume
        y = render._process_series(curve.y, x, s)
        found = analysis.find_peaks(y, x, prominence=10, min_distance=0.3, smooth=11)
        found = [p for p in found if 7.5 <= x[p["i"]] <= 20.5]
        for p in analysis.integrate_peaks(y, x, found):
            p.update({"color": s["color"], "label": curve.channel or curve.name, "unit": curve.unit})
            peaks.append({"run": s["run"], "curve": s["curve"], "x0": p["start_x"], "x1": p["end_x"],
                          "top": p["apex_x"], "yshow": p["apex_y"],
                          "label": "P%d" % p["n"], "color": s["color"]})
            rows.append((curve.channel or curve.name, p["n"], p["apex_x"], p["height"],
                         p["area"], p["area_pct"], p["fwhm"], p["start_x"], p["end_x"]))
    frac = runs[rid].fractionation
    spec4 = {"figure": dict(base_fig, width_mm=120, height_mm=75, base_size=8.5,
                            title=f"{rid}: A280 + A455", subtitle=runs[rid].meta.get("column", ""), panel="A",
                            margin_left=0.13, margin_right=0.13, margin_bottom=0.22, margin_top=0.13),
             "axes": dict(base_axes, x_range=[0, 22], y_range=[0, None], y_label="A280 (mAU)",
                          x_major=2, x_minor=0.5),
             "curves": curves, "legend": dict(legend, pos="upper right"),
             "secondary": {"show": True, "y_label": "A455 (mAU)", "y_range": [0, None],
                           "y_color": "#2471A3", "y_major": None},
             "fractions": {"show": True, "run": rid, "color": "#6b8ec9",
                           "show_ticks": True, "show_label": True},
             "peaks": peaks, "series": fseries}
    fig4 = render.render_figure(spec4, runs)
    for fmt, dpi in [("png", 600), ("pdf", 600)]:
        open(os.path.join(outdir, f"example_{rid.replace(' ', '_')}_FMN_peaks.{fmt}"), "wb").write(
            render.figure_to_bytes(fig4, fmt=fmt, dpi=dpi))
    plt.close(fig4)
    with open(os.path.join(outdir, f"example_{rid.replace(' ', '_')}_peaks.csv"), "w") as fh:
        fh.write("series,peak,apex_mL,height_mAU,area_mAU_mL,area_pct,fwhm_mL,start_mL,end_mL\n")
        for r in rows:
            fh.write("%s,%d,%.3f,%.2f,%.2f,%.1f,%.3f,%.3f,%.3f\n" % r)
    if frac:
        with open(os.path.join(outdir, f"example_{rid.replace(' ', '_')}_fractions.csv"), "w") as fh:
            fh.write("well,index,volume_mL,time_min\n")
            for w in frac.wells:
                fh.write("%s,%d,%.4f,%.4f\n" % (w["well"], w["i"], w["volume"], w["time"]))

    print("examples written to", outdir)
    for f in sorted(os.listdir(outdir)):
        print("  ", f)

if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "/data/codex/webui/sec"
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "examples")
    main(folder, outdir)
