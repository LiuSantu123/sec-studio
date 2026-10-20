#!/usr/bin/env python3
"""SEC Studio - a GraphPad-Prism-like visual editor for Aekta/UNICORN SEC runs.

Run::

    python3 app.py --data-dir /path/to/zips

then open the printed http://127.0.0.1:PORT address.
"""

from __future__ import annotations

import argparse
import glob
import io
import os
import re
import socket
import threading
import uuid
import webbrowser
import zipfile
from typing import Dict, List

from flask import Flask, jsonify, render_template, request, send_file

import akta
import analysis
import render
import project_format

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024

# In-memory store of parsed runs.
STORE: Dict[str, akta.Run] = {}
LOCK = threading.Lock()
DATA_DIR = os.path.abspath(os.path.dirname(__file__))


def _store_run(run: akta.Run) -> str:
    with LOCK:
        if run.id in STORE:
            run.id = f"{run.id}-{uuid.uuid4().hex[:6]}"
        STORE[run.id] = run
    return run.id


def _run_summary(run: akta.Run) -> dict:
    return run.to_dict()


@app.get("/")
def index():
    return render_template("index.html", data_dir=DATA_DIR)


@app.get("/api/runs")
def api_runs():
    with LOCK:
        return jsonify({"runs": [_run_summary(r) for r in STORE.values()],
                        "data_dir": DATA_DIR})


@app.post("/api/load_folder")
def api_load_folder():
    body = request.get_json(force=True, silent=True) or {}
    folder = body.get("folder") or DATA_DIR
    folder = os.path.abspath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        return jsonify({"error": f"not a directory: {folder}"}), 400
    files = sorted(glob.glob(os.path.join(folder, "*.zip"))
                   + glob.glob(os.path.join(folder, "*.csv"))
                   + glob.glob(os.path.join(folder, "*.tsv")))
    added = []
    with LOCK:
        existing = {r.source: rid for rid, r in STORE.items() if r.source}
    for path in files:
        src = os.path.basename(path)
        if src in existing and existing[src] in STORE:
            added.append(_run_summary(STORE[existing[src]]))
            continue
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            run = _parse_input(raw, src)
            run.id = _store_run(run)
            added.append(_run_summary(run))
        except Exception as exc:  # noqa: BLE001
            added.append({"error": f"{src}: {exc}"})
    return jsonify({"added": added, "folder": folder, "found": len(files)})


@app.post("/api/upload")
def api_upload():
    files = request.files.getlist("files")
    added = []
    for f in files:
        try:
            run = _parse_input(f.read(), f.filename or "")
            run.id = _store_run(run)
            added.append(_run_summary(run))
        except Exception as exc:  # noqa: BLE001
            added.append({"error": f"{f.filename}: {exc}"})
    return jsonify({"added": added})


def _parse_input(raw: bytes, source: str):
    suffix = os.path.splitext(source.lower())[1]
    if suffix in (".csv", ".tsv"):
        return akta.parse_csv(raw, source=source)
    if suffix == ".zip":
        return akta.parse_result_zip(raw, source=source)
    raise ValueError("支持的文件格式：ÄKTA/UNICORN ZIP、CSV、TSV")


@app.post("/api/project/export")
def api_project_export():
    body = request.get_json(force=True, silent=True) or {}
    state = body.get("state")
    if not isinstance(state, dict):
        return jsonify({"error": "项目界面状态缺失"}), 400
    with LOCK:
        runs = list(STORE.values())
    try:
        payload = project_format.write_project(state, runs)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400
    return send_file(io.BytesIO(payload), mimetype="application/vnd.sec-studio.project+zip",
                     as_attachment=True, download_name="sec_studio_project.secproj")


@app.post("/api/project/import")
def api_project_import():
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"error": "请选择 .secproj 项目文件"}), 400
    if not (uploaded.filename or "").lower().endswith(".secproj"):
        return jsonify({"error": "项目文件扩展名应为 .secproj"}), 400
    try:
        state, runs = project_format.read_project(uploaded.read())
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400
    with LOCK:
        STORE.clear()
        for run in runs:
            STORE[run.id] = run
    return jsonify({"state": state, "runs": [_run_summary(run) for run in runs]})


@app.post("/api/remove")
def api_remove():
    body = request.get_json(force=True, silent=True) or {}
    with LOCK:
        for rid in body.get("ids", []):
            STORE.pop(rid, None)
    return jsonify({"ok": True})


def _resolve_spec_runs(spec: dict):
    with LOCK:
        return dict(STORE)


@app.post("/api/render")
def api_render():
    body = request.get_json(force=True, silent=True) or {}
    spec = body.get("spec") or {}
    fmt = body.get("format", "png")
    transparent = bool(body.get("transparent", spec.get("figure", {}).get("transparent", False)))
    dpi = body.get("dpi") or spec.get("figure", {}).get("dpi", 300)
    runs = _resolve_spec_runs(spec)
    try:
        fig = render.render_figure(spec, runs)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400
    data = render.figure_to_bytes(fig, fmt=fmt, dpi=float(dpi), transparent=transparent)
    import matplotlib.pyplot as plt
    plt.close(fig)
    mimetypes = {"png": "image/png", "pdf": "application/pdf", "svg": "image/svg+xml",
                 "tiff": "image/tiff", "jpg": "image/jpeg"}
    return send_file(io.BytesIO(data), mimetype=mimetypes.get(fmt, "application/octet-stream"))


def _safe(name: str) -> str:
    name = re.sub(r"[^\w\-.]+", "_", name or "figure").strip("_")
    return name or "figure"


@app.post("/api/analyze")
def api_analyze():
    """Peak picking + area integration for the selected series."""
    body = request.get_json(force=True, silent=True) or {}
    runs = _resolve_spec_runs(body.get("spec") or {})
    series = body.get("series") or []
    x_kind = body.get("x_kind", "volume")
    xr = body.get("x_range") or [None, None]
    prominence = float(body.get("prominence") or 0.0)
    min_distance = float(body.get("min_distance") or 0.0)
    smooth = int(body.get("smooth") or 0)
    out = []
    for s in series:
        run = runs.get(s.get("run"))
        if run is None:
            continue
        curve = run.curves.get(s.get("curve"))
        if curve is None:
            continue
        x = render._x_array(curve, x_kind, run.meta.get("column_volume"))
        y = render._process_series(curve.y, x, s)
        peaks = analysis.find_peaks(y, x, prominence=prominence,
                                    min_distance=min_distance, smooth=smooth)
        if xr[0] is not None:
            peaks = [p for p in peaks if x[p["i"]] >= float(xr[0])]
        if xr[1] is not None:
            peaks = [p for p in peaks if x[p["i"]] <= float(xr[1])]
        for p in analysis.integrate_peaks(y, x, peaks):
            p.update({"run": s.get("run"), "curve": s.get("curve"),
                      "label": s.get("label") or curve.label,
                      "channel": curve.channel, "unit": curve.unit,
                      "color": s.get("color", "#c0392b")})
            out.append(p)
    return jsonify({"peaks": out, "x_kind": x_kind})


@app.post("/api/sequence")
def api_sequence():
    body = request.get_json(force=True, silent=True) or {}
    return jsonify(analysis.analyze_sequence(body.get("seq", ""), body.get("a280")))


@app.post("/api/screen")
def api_screen():
    """Rank designs by monomer-peak cofactor loading (fixed-rule method)."""
    body = request.get_json(force=True, silent=True) or {}
    runs = _resolve_spec_runs(body.get("spec") or {})
    params = body.get("params") or {}
    rows = analysis.screen_runs(list(runs.values()), params)
    return jsonify({"rows": rows})


@app.post("/api/screen_figure")
def api_screen_figure():
    """Render the design-screen ranking bar chart (PDF/SVG/PNG/TIFF)."""
    body = request.get_json(force=True, silent=True) or {}
    spec = body.get("spec") or {}
    rows = body.get("rows") or []
    metric = body.get("metric", "r_monomer")
    fmt = body.get("format", "png")
    dpi = float(body.get("dpi") or spec.get("figure", {}).get("dpi", 600))
    colors = body.get("colors")
    import matplotlib.pyplot as plt
    try:
        fig = render.render_screen_bars(rows, spec=spec, metric=metric, colors=colors)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400
    data = render.figure_to_bytes(fig, fmt=fmt, dpi=dpi)
    plt.close(fig)
    mimetypes = {"png": "image/png", "pdf": "application/pdf", "svg": "image/svg+xml",
                 "tiff": "image/tiff", "jpg": "image/jpeg"}
    filename = _safe(body.get("filename") or f"fmn_screen_{metric}")
    return send_file(io.BytesIO(data), mimetype=mimetypes.get(fmt, "application/octet-stream"),
                     as_attachment=True, download_name=f"{filename}.{fmt}")


@app.post("/api/mw")
def api_mw():
    body = request.get_json(force=True, silent=True) or {}
    return jsonify(analysis.calibrate_sec(
        body.get("standards") or [], body.get("volumes") or [],
        float(body.get("v0") or 0.0), float(body.get("vt") or 0.0)))


@app.post("/api/cofactor")
def api_cofactor():
    body = request.get_json(force=True, silent=True) or {}
    eps_p = float(body.get("eps_protein") or 0.0)
    eps_c = float(body.get("eps_cofactor") or 0.0)
    eps_c280 = float(body.get("eps_cofactor_at_280") or 0.0)
    rows = []
    for pair in body.get("pairs") or []:
        res = analysis.cofactor_ratio(float(pair.get("area_protein") or 0),
                                      float(pair.get("area_cofactor") or 0),
                                      eps_p, eps_c, eps_c280)
        res["label"] = pair.get("label")
        rows.append(res)
    return jsonify({"rows": rows})


@app.post("/api/export_figure")
def api_export_figure():
    body = request.get_json(force=True, silent=True) or {}
    spec = body.get("spec") or {}
    fmt = body.get("format", "png")
    dpi = float(body.get("dpi") or spec.get("figure", {}).get("dpi", 600))
    transparent = bool(body.get("transparent", spec.get("figure", {}).get("transparent", False)))
    filename = _safe(body.get("filename") or "sec_figure")
    runs = _resolve_spec_runs(spec)
    import matplotlib.pyplot as plt

    mimetypes = {"png": "image/png", "pdf": "application/pdf", "svg": "image/svg+xml",
                 "tiff": "image/tiff", "jpg": "image/jpeg"}

    def render_one(sub_spec):
        fig = render.render_figure(sub_spec, runs)
        data = render.figure_to_bytes(fig, fmt=fmt, dpi=dpi, transparent=transparent)
        plt.close(fig)
        return data

    if body.get("batch"):
        # one figure per run (all series belonging to that run)
        series = spec.get("series", [])
        by_run: Dict[str, list] = {}
        for s in series:
            by_run.setdefault(s.get("run"), []).append(s)
        zbuf = io.BytesIO()
        used = set()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rid, sers in by_run.items():
                run = runs.get(rid)
                sub = dict(spec)
                sub["series"] = sers
                if run is not None:
                    fcfg = dict(sub.get("figure", {}))
                    fcfg["title"] = fcfg.get("title") or run.name
                    sub["figure"] = fcfg
                data = render_one(sub)
                base = _safe(runs[rid].name if rid in runs else str(rid))
                name = base
                i = 2
                while name in used:
                    name = f"{base}_{i}"; i += 1
                used.add(name)
                zf.writestr(f"{name}.{fmt}", data)
        zbuf.seek(0)
        return send_file(zbuf, mimetype="application/zip", as_attachment=True,
                         download_name=f"{filename}.zip")

    try:
        data = render_one(spec)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400
    return send_file(io.BytesIO(data), mimetype=mimetypes.get(fmt, "application/octet-stream"),
                     as_attachment=True, download_name=f"{filename}.{fmt}")


@app.post("/api/export_csv")
def api_export_csv():
    body = request.get_json(force=True, silent=True) or {}
    spec = body.get("spec") or {}
    runs = _resolve_spec_runs(spec)
    which = body.get("series") or spec.get("series") or []
    kw = dict(
        x_kind=body.get("x_kind", "volume"),
        x_range=body.get("x_range", [None, None]),
        processed=bool(body.get("processed", True)),
        layout=body.get("layout", "tidy"),
    )
    name = _safe((body.get("filename") or "sec_data").replace(".csv", ""))

    if body.get("batch"):
        by_run: Dict[str, list] = {}
        for s in which:
            by_run.setdefault(s.get("run"), []).append(s)
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rid, sers in by_run.items():
                text = render.export_csv(spec, runs, sers, **kw)
                base = _safe(runs[rid].name if rid in runs else str(rid))
                zf.writestr(f"{base}.csv", text)
        zbuf.seek(0)
        return send_file(zbuf, mimetype="application/zip", as_attachment=True,
                         download_name=f"{name}_per_run.zip")

    text = render.export_csv(spec, runs, which, **kw)
    return send_file(io.BytesIO(text.encode("utf-8")), mimetype="text/csv",
                     as_attachment=True, download_name=f"{name}.csv")


def _lan_ip() -> str:
    """Best-guess IP a *remote* client can reach this host on."""
    conn = os.environ.get("SSH_CONNECTION", "").split()
    if len(conn) >= 3:            # "<client-ip> <client-port> <server-ip> <server-port>"
        return conn[2]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def _print_access(host: str, port: int) -> None:
    """Explain how to reach the UI, mirroring the existing webui workflow."""
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
    over_ssh = bool(os.environ.get("SSH_CONNECTION"))
    ip = _lan_ip()
    bound_public = host in ("0.0.0.0", "::", "")

    print("  ────────────────────────────────────────────────────────────")
    print(f"  [集群本机]  http://127.0.0.1:{port}/")
    if bound_public:
        print(f"  [局域网直连] http://{ip}:{port}/   （已绑定 {host}）")
    print()
    print("  【从 Mac 访问 —— 推荐 SSH 端口转发，与 webui 做法一致】")
    print("  在 Mac 的终端里执行（新开一个窗口，保持不关）:")
    print(f"      ssh -N -L {port}:127.0.0.1:{port} zheng")
    print("  然后在 Mac 浏览器打开:  http://127.0.0.1:" + str(port) + "/")
    print("  （把 zheng 换成你平时 ssh 的别名；也可以直接写 " + user + "@" + ip + "）")
    print()
    print("  已经 ssh 进集群时，不想再开一个连接？在当前会话里加转发：")
    print("      按 Enter，然后输入  ~C  ，再输入下面这行回车：")
    print(f"      -L {port}:127.0.0.1:{port}")
    print()
    if not bound_public:
        print("  不想用隧道？改用下面方式启动，再从 Mac 直接打开上面的局域网直连地址：")
        print(f"      ./run.sh \"\" {port} --host 0.0.0.0")
    print("  ────────────────────────────────────────────────────────────")
    if over_ssh and not os.environ.get("DISPLAY"):
        print("  （检测到 SSH 无图形界面，已跳过自动打开浏览器）")
    print()


def main():
    global DATA_DIR
    ap = argparse.ArgumentParser(description="SEC Studio")
    ap.add_argument("--data-dir", default=os.getcwd(),
                    help="folder scanned by the 'Load folder' button (default: this folder)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; 127.0.0.1 (default) + SSH tunnel, or 0.0.0.0 for LAN")
    ap.add_argument("--port", type=int, default=8731)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    DATA_DIR = os.path.abspath(os.path.expanduser(args.data_dir))

    print(f"\n  SEC Studio")
    print(f"  data folder ->  {DATA_DIR}")
    _print_access(args.host, args.port)

    headless_ssh = bool(os.environ.get("SSH_CONNECTION")) and not os.environ.get("DISPLAY")
    if not args.no_browser and not headless_ssh:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}/")).start()
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
