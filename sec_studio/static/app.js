"use strict";
/* SEC Studio front-end. Holds a single `state` object, builds the inspector
   declaratively from it, and asks the Flask backend to rasterise previews. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const FONTS = ["Arial (Liberation Sans)", "Helvetica (Nimbus Sans)", "DejaVu Sans",
  "PT Sans", "Montserrat", "FreeSans", "Nimbus Roman (Times)", "Liberation Serif",
  "DejaVu Serif", "STIX (Times-like)", "Noto Sans SC (中文)", "Noto Serif SC (中文)"];

const PRESETS = {
  "science":     { label: "Science 单栏 85mm",    width: 85,  height: 65, base: 8 },
  "science-1.5": { label: "Science 1.5栏 120mm",  width: 120, height: 80, base: 9 },
  "nature":      { label: "Nature 单栏 89mm",     width: 89,  height: 70, base: 8 },
  "cell":        { label: "Cell 单栏 84mm",       width: 84,  height: 70, base: 8 },
  "wide":        { label: "双栏 170mm",           width: 170, height: 90, base: 10 },
  "square":      { label: "正方形 90mm",          width: 90,  height: 90, base: 9 },
};

const PALETTES = {
  "journal":   ["#C0392B", "#2471A3", "#1E8449", "#8E44AD", "#D68910", "#17A589", "#CB4335", "#2E86C1", "#7D3C98", "#B9770E"],
  "okabe-ito": ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#000000"],
  "viridis":   ["#440154", "#443983", "#31688e", "#21918c", "#35b779", "#90d743", "#fde725"],
  "grays":     ["#111111", "#444444", "#777777", "#aaaaaa", "#cccccc"],
  "warm":      ["#B03A2E", "#D68910", "#F39C12", "#CA6F1E", "#7E5109", "#A04000"],
};

const CHANNELS = ["A280", "A230", "A455"];

/* ------------------------------------------------------------------ state */
const state = {
  runs: [],
  channels: { A280: true, A230: false, A455: false },
  overrides: {},
  peaks: [],            // detected peaks (flat list)
  showPeaks: true,      // shade peak windows on the figure
  frac: { show: true, run: "", color: "#6b8ec9", show_ticks: true, show_label: true },
  an: { prominence: 15, min_distance: 0.3, smooth: 11, xmin: null, xmax: null, exclude: {} },
  seq: { text: "", a280: "", result: null },
  mw: { standards: "8.5,6600\n11.0,29000\n13.5,66900\n16.0,158000", v0: 7.6, vt: 23.562, result: null },
  cof: { eps_protein: 0, eps_cofactor: 11300, eps_cofactor_280: 0, result: null },
  screen: {
    rows: [], metric: "r_monomer", show_win: false,
    params: {
      protein_channel: "UV 1_280", cofactor_channel: "UV 3_455",
      baseline_win: [4.5, 8.5], valley_left: [13.0, 14.3], valley_right: [16.0, 18.6],
      rise_lo: 8.0, eps_protein: 20000, eps_cofactor: 12500, eps_cofactor_at_protein: 20000,
    },
  },
  spec: {
    figure: {
      width_mm: 85, height_mm: 65, dpi: 300, bg: "#ffffff", transparent: false,
      font: "Arial (Liberation Sans)", base_size: 8,
      title: "", subtitle: "", panel: "",
      title_size: 10, title_bold: true, subtitle_size: 8, panel_size: 11,
      margin_left: 0.16, margin_right: 0.04, margin_bottom: 0.17, margin_top: 0.12,
      annotate_size: true,
    },
    axes: {
      x_kind: "volume", x_range: [0, 24], y_range: [null, null],
      x_label: "Elution volume (mL)", y_label: "Absorbance (mAU)",
      x_major: null, x_minor: null, y_major: null, y_minor: null,
      tick_dir: "out", tick_len: 3, tick_width: 0.8, tick_label_size: null,
      spine_width: 0.8, spine_top: false, spine_right: false,
      grid: false, grid_ls: ":", grid_color: "#d9d9d9",
      label_size: null, x_log: false, y_log: false, invert_x: false,
    },
    curves: { lw: 1.5, ls: "-", alpha: 1.0, baseline: "start", baseline_frac: 0.05, scale: "none", smooth: 0, deriv: 0, deriv_smooth: 11 },
    legend: { show: true, pos: "upper right", frame: false, font_size: 8, ncol: 1, title: "" },
    secondary: { show: false, y_label: "Conductivity (mS/cm)", y_range: [null, null], y_color: "#8a4b0f", y_major: null },
  },
};

/* -------------------------------------------------------------- utilities */
function getPath(o, p) { return p.split(".").reduce((a, k) => (a == null ? a : a[k]), o); }
function setPath(o, p, v) {
  const ks = p.split("."); let x = o;
  for (let i = 0; i < ks.length - 1; i++) {
    const k = ks[i];
    if (x[k] == null) x[k] = /^\d+$/.test(ks[i + 1]) ? [] : {};
    x = x[k];
  }
  x[ks[ks.length - 1]] = v;
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function el(html) { const d = document.createElement("div"); d.innerHTML = html.trim(); return d.firstElementChild; }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

/* ------------------------------------------------------- series resolution */
function activeSeries() {
  const out = [];
  for (const run of state.runs) {
    if (!run.visible) continue;
    for (const ch of CHANNELS) {
      if (!state.channels[ch]) continue;
      const cn = run.channelCurve && run.channelCurve[ch];
      if (!cn) continue;
      out.push({ run, ch, curve: cn, key: run.id + "|" + cn });
    }
  }
  return out;
}
function multiChannel() { return CHANNELS.filter(c => state.channels[c]).length > 1; }
function seriesLabel(it, ov) {
  if (ov && ov.label) return ov.label;
  return multiChannel() ? it.run.label + " " + it.ch : it.run.label;
}
function buildSeriesSpec() {
  const c = state.spec.curves;
  return activeSeries().map(it => {
    const ov = state.overrides[it.key] || {};
    const pick = (k, d) => (ov[k] === undefined || ov[k] === null || ov[k] === "" ? d : ov[k]);
    return {
      run: it.run.id, curve: it.curve, channel: it.ch,
      label: seriesLabel(it, ov),
      show: ov.show !== false,
      color: pick("color", it.run.color),
      lw: pick("lw", c.lw), ls: pick("ls", c.ls), alpha: pick("alpha", c.alpha),
      axis: pick("axis", "left"),
      baseline: pick("baseline", c.baseline), baseline_frac: pick("baseline_frac", c.baseline_frac),
      scale: pick("scale", c.scale), smooth: pick("smooth", c.smooth),
      deriv: pick("deriv", c.deriv || 0), deriv_smooth: pick("deriv_smooth", c.deriv_smooth || 11),
    };
  });
}
function fracRunId() {
  if (state.frac.run) return state.frac.run;
  const r = state.runs.find(x => x.visible && x.fractionation);
  return r ? r.id : "";
}
function buildSpec() {
  const spec = Object.assign({}, state.spec, { series: buildSeriesSpec() });
  spec.fractions = {
    show: !!state.frac.show, run: fracRunId(), color: state.frac.color,
    show_ticks: !!state.frac.show_ticks, show_label: !!state.frac.show_label,
  };
  spec.peaks = state.showPeaks ? state.peaks.map((p, i) => ({
    run: p.run, curve: p.curve, x0: p.start_x, x1: p.end_x,
    top: p.apex_x, yshow: p.apex_y,
    label: p.pk_label || ("P" + (i + 1)), color: p.color,
  })) : [];
  spec.screen_windows = (state.screen.show_win ? state.screen.rows : []).map(r => ({
    run: r.run, x0: r.window[0], x1: r.window[1],
    color: state.runs.find(x => x.id === r.run)?.color || "#7f8c8d",
  }));
  return spec;
}

/* --------------------------------------------------------------- preview */
const renderPreview = debounce(async () => {
  if (!state.runs.length) { showEmpty(true); return; }
  const dpi = +$("#preview-dpi").value || 150;
  setStatus("渲染中…", "busy");
  try {
    const res = await fetch("/api/render", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec: buildSpec(), format: "png", dpi }),
    });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || res.statusText); }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const img = $("#preview");
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    img.dataset.url = url; img.src = url; img.hidden = false;
    showEmpty(false); setStatus("就绪");
  } catch (e) { setStatus("渲染失败: " + e.message, "err"); }
}, 220);

function setStatus(t, cls = "") { const p = $("#status"); p.textContent = t; p.className = "pill " + cls; }
function showEmpty(on) { $("#empty-state").style.display = on ? "" : "none"; if (on) $("#preview").hidden = true; }

/* --------------------------------------------------- inspector builders */
function field(label, path, opts = {}) {
  const t = opts.type || "number";
  const v = getPath(state.spec, path);
  const id = "f-" + path.replace(/\./g, "-");
  if (t === "color") return `<div class="field"><label>${label}</label><input type="color" data-path="${path}" id="${id}" value="${v || "#000000"}"></div>`;
  if (t === "checkbox") return `<div class="field"><label>${label}</label><input type="checkbox" data-path="${path}" id="${id}" ${v ? "checked" : ""}></div>`;
  if (t === "select") {
    const o = opts.options.map(x => `<option value="${x[0]}" ${String(v) === String(x[0]) ? "selected" : ""}>${x[1]}</option>`).join("");
    return `<div class="field"><label>${label}</label><select data-path="${path}" id="${id}">${o}</select></div>`;
  }
  const ph = opts.placeholder ? `placeholder="${opts.placeholder}"` : "";
  const val = (v === null || v === undefined) ? "" : v;
  const step = opts.step || "any";
  return `<div class="field"><label>${label}</label><input type="${t === "text" ? "text" : "number"}" data-path="${path}" id="${id}" value="${esc(val)}" ${ph} step="${step}" ${opts.min !== undefined ? `min="${opts.min}"` : ""}></div>`;
}
function group(title, inner) { return `<div class="group"><h3>${title}</h3>${inner}</div>`; }

function buildPanes() {
  const s = state.spec;
  $('[data-pane="figure"]').innerHTML =
    group("画布预设", `
      <div class="field"><label>期刊预设</label><select id="preset-select">
        <option value="">自定义…</option>
        ${Object.entries(PRESETS).map(([k, p]) => `<option value="${k}">${p.label}</option>`).join("")}
      </select></div>
      <div class="field"><label>宽度 (mm)</label><input type="number" data-path="figure.width_mm" value="${s.figure.width_mm}" step="1"></div>
      <div class="field"><label>高度 (mm)</label><input type="number" data-path="figure.height_mm" value="${s.figure.height_mm}" step="1"></div>
      <div class="field"><label>导出 DPI</label><input type="number" data-path="figure.dpi" value="${s.figure.dpi}" step="50" min="72"></div>`) +
    group("字体 / 字号", `
      <div class="field"><label>字体</label><select data-path="figure.font">${FONTS.map(f => `<option ${s.figure.font === f ? "selected" : ""}>${f}</option>`).join("")}</select></div>
      <div class="field"><label>基准字号 (pt)</label><input type="number" data-path="figure.base_size" value="${s.figure.base_size}" step="0.5"></div>`) +
    group("背景", `
      <div class="field"><label>背景颜色</label><input type="color" data-path="figure.bg" value="${s.figure.bg}"></div>
      <div class="field"><label>透明背景</label><input type="checkbox" data-path="figure.transparent" ${s.figure.transparent ? "checked" : ""}></div>`) +
    group("标题 / 面板标签", `
      ${field("主标题", "figure.title", { type: "text", placeholder: "（可留空）" })}
      ${field("副标题", "figure.subtitle", { type: "text", placeholder: "（可留空）" })}
      ${field("面板字母", "figure.panel", { type: "text", placeholder: "A" })}
      <div class="row2">${field("标题字号", "figure.title_size")}${field("副标题字号", "figure.subtitle_size")}</div>
      <div class="field"><label>标题加粗</label><input type="checkbox" data-path="figure.title_bold" ${s.figure.title_bold ? "checked" : ""}></div>`) +
    group("边距 (0–0.5)", `
      <div class="row2">${field("左", "figure.margin_left", { step: 0.01 })}${field("右", "figure.margin_right", { step: 0.01 })}</div>
      <div class="row2">${field("下", "figure.margin_bottom", { step: 0.01 })}${field("上", "figure.margin_top", { step: 0.01 })}</div>`);

  $('[data-pane="axes"]').innerHTML =
    group("X 轴", `
      <div class="field"><label>X 类型</label><select data-path="axes.x_kind">
        <option value="volume" ${s.axes.x_kind === "volume" ? "selected" : ""}>洗脱体积 (mL)</option>
        <option value="time" ${s.axes.x_kind === "time" ? "selected" : ""}>时间 (min)</option>
        <option value="cv" ${s.axes.x_kind === "cv" ? "selected" : ""}>柱体积 (CV)</option>
      </select></div>
      ${field("X 标签", "axes.x_label", { type: "text" })}
      <div class="row2">${field("X 起", "axes.x_range.0", { placeholder: "自动" })}${field("X 止", "axes.x_range.1", { placeholder: "自动" })}</div>
      <div class="row2">${field("X 主刻度", "axes.x_major", { placeholder: "自动" })}${field("X 次刻度", "axes.x_minor", { placeholder: "自动" })}</div>`) +
    group("Y 轴", `
      ${field("Y 标签", "axes.y_label", { type: "text" })}
      <div class="row2">${field("Y 起", "axes.y_range.0", { placeholder: "自动" })}${field("Y 止", "axes.y_range.1", { placeholder: "自动" })}</div>
      <div class="row2">${field("Y 主刻度", "axes.y_major", { placeholder: "自动" })}${field("Y 次刻度", "axes.y_minor", { placeholder: "自动" })}</div>`) +
    group("刻度 / 边框", `
      <div class="field"><label>刻度方向</label><select data-path="axes.tick_dir">
        <option value="out" ${s.axes.tick_dir === "out" ? "selected" : ""}>向外</option>
        <option value="in" ${s.axes.tick_dir === "in" ? "selected" : ""}>向内</option>
        <option value="inout" ${s.axes.tick_dir === "inout" ? "selected" : ""}>双向</option>
      </select></div>
      <div class="row2">${field("刻度长", "axes.tick_len", { step: 0.1 })}${field("刻度粗", "axes.tick_width", { step: 0.1 })}</div>
      <div class="row2">${field("刻度字号", "axes.tick_label_size", { placeholder: "自动" })}${field("边框粗", "axes.spine_width", { step: 0.1 })}</div>
      <div class="row2">
        <div class="field"><label>上边框</label><input type="checkbox" data-path="axes.spine_top" ${s.axes.spine_top ? "checked" : ""}></div>
        <div class="field"><label>右边框</label><input type="checkbox" data-path="axes.spine_right" ${s.axes.spine_right ? "checked" : ""}></div>
      </div>
      <div class="row2">
        <div class="field"><label>网格</label><input type="checkbox" data-path="axes.grid" ${s.axes.grid ? "checked" : ""}></div>
        ${field("网格线型", "axes.grid_ls", { type: "text" })}
      </div>
      <div class="row2">
        <div class="field"><label>X 对数</label><input type="checkbox" data-path="axes.x_log" ${s.axes.x_log ? "checked" : ""}></div>
        <div class="field"><label>Y 对数</label><input type="checkbox" data-path="axes.y_log" ${s.axes.y_log ? "checked" : ""}></div>
      </div>
      <div class="field"><label>翻转 X 轴</label><input type="checkbox" data-path="axes.invert_x" ${s.axes.invert_x ? "checked" : ""}></div>
      ${field("标签字号", "axes.label_size", { placeholder: "自动" })}`) +
    group("右侧副坐标轴", `
      <div class="field"><label>启用副轴</label><input type="checkbox" data-path="secondary.show" ${s.secondary.show ? "checked" : ""}></div>
      ${field("副轴标签", "secondary.y_label", { type: "text" })}
      <div class="row2">${field("副 Y 起", "secondary.y_range.0", { placeholder: "自动" })}${field("副 Y 止", "secondary.y_range.1", { placeholder: "自动" })}</div>
      ${field("副轴颜色", "secondary.y_color", { type: "color" })}
      <div class="hint">到“数据”标签把某条曲线的坐标轴设为“右”，即可绘制在副轴上（如电导 vs A280）。</div>`);

  const lsOpts = [["-", "实线"], ["--", "虚线"], [":", "点线"], ["-.", "点划线"]];
  const baseOpts = [["none", "不扣基线"], ["start", "扣起始段均值"], ["min", "扣全局最小值"], ["linear", "扣起始线性拟合"]];
  const scaleOpts = [["none", "原始"], ["max", "归一化 (÷最大值)"], ["minmax", "归一化 (0–1)"]];
  $('[data-pane="curves"]').innerHTML =
    group("全局曲线样式（应用到所有导入）", `
      <div class="row2">${field("线宽", "curves.lw", { step: 0.1 })}
        <div class="field"><label>线型</label><select data-path="curves.ls">${lsOpts.map(o => `<option value="${o[0]}" ${s.curves.ls === o[0] ? "selected" : ""}>${o[1]}</option>`).join("")}</select></div></div>
      ${field("不透明度", "curves.alpha", { step: 0.05, min: 0 })}
      ${field("平滑窗口 (点)", "curves.smooth", { step: 1, min: 0, placeholder: "0 = 关闭" })}
      ${field("基线窗口 (占比)", "curves.baseline_frac", { step: 0.01, min: 0 })}
      <div class="field"><label>基线处理</label><select data-path="curves.baseline">${baseOpts.map(o => `<option value="${o[0]}" ${s.curves.baseline === o[0] ? "selected" : ""}>${o[1]}</option>`).join("")}</select></div>
      <div class="field"><label>归一化</label><select data-path="curves.scale">${scaleOpts.map(o => `<option value="${o[0]}" ${s.curves.scale === o[0] ? "selected" : ""}>${o[1]}</option>`).join("")}</select></div>`) +
    group("一键配色", `
      <div class="field"><label>配色方案</label><select id="palette-select">${Object.keys(PALETTES).map(k => `<option value="${k}">${k}</option>`).join("")}</select></div>
      <button class="btn accent" style="width:100%" id="btn-recolor-pane">🎨 应用到所有 Run</button>
      <div class="hint">按导入顺序给每个 Run 分配颜色。</div>`);

  $('[data-pane="legend"]').innerHTML =
    group("图例", `
      <div class="field"><label>显示图例</label><input type="checkbox" data-path="legend.show" ${s.legend.show ? "checked" : ""}></div>
      <div class="field"><label>位置</label><select data-path="legend.pos">
        ${["upper right", "upper left", "lower right", "lower left", "center right", "center left", "upper center", "lower center", "best"].map(p => `<option value="${p}" ${s.legend.pos === p ? "selected" : ""}>${p}</option>`).join("")}
      </select></div>
      <div class="row2">${field("字号", "legend.font_size")}${field("列数", "legend.ncol", { step: 1, min: 1 })}</div>
      ${field("图例标题", "legend.title", { type: "text", placeholder: "（可留空）" })}
      <div class="field"><label>边框</label><input type="checkbox" data-path="legend.frame" ${s.legend.frame ? "checked" : ""}></div>`);

  buildAnalysisPane();
  buildScreenPane();
  bindInputsTo($("#panes"));
  const ps = $("#preset-select"); if (ps) ps.addEventListener("change", e => applyPreset(e.target.value));
  const rp = $("#btn-recolor-pane"); if (rp) rp.addEventListener("click", () => applyPalette($("#palette-select").value));
}

/* ------------------------------------------------------------- analysis */
function buildAnalysisPane() {
  const pane = $('[data-pane="analysis"]');
  const f = state.frac, a = state.an;
  const runOpts = state.runs.filter(r => r.fractionation)
    .map(r => `<option value="${esc(r.id)}" ${f.run === r.id ? "selected" : ""}>${esc(r.label)}</option>`).join("");
  pane.innerHTML =
    `<div class="group sub"><h4>收集范围 (来自文件)</h4>
      <div class="field"><label>显示收集区间</label><input type="checkbox" id="fx-show" ${f.show ? "checked" : ""}></div>
      <div class="field"><label>用哪个 Run</label><select id="fx-run">
        <option value="">（第一个可见 Run）</option>${runOpts}</select></div>
      <div class="row2">
        <div class="field"><label>颜色</label><input type="color" id="fx-color" value="${f.color}"></div>
        <div class="field"><label>刻度线</label><input type="checkbox" id="fx-ticks" ${f.show_ticks ? "checked" : ""}></div>
      </div>
      <div class="field"><label>底部文字标注</label><input type="checkbox" id="fx-label" ${f.show_label ? "checked" : ""}></div>
      <div class="rbox" id="fx-info"></div>
    </div>

    <div class="group sub"><h4>峰检测 / 面积积分</h4>
      <div id="an-series" class="csv-series-list" style="max-height:120px;border:1px solid var(--line);border-radius:8px;padding:6px 8px;margin-bottom:8px"></div>
      <div class="row2">
        <div class="field"><label>Prominence</label><input type="number" id="an-prom" value="${a.prominence}" step="1"></div>
        <div class="field"><label>最小峰距</label><input type="number" id="an-dist" value="${a.min_distance}" step="0.1"></div>
      </div>
      <div class="row2">
        <div class="field"><label>平滑窗口</label><input type="number" id="an-smooth" value="${a.smooth}" step="2"></div>
        <div class="field"><label>显示峰区间</label><input type="checkbox" id="an-show" ${state.showPeaks ? "checked" : ""}></div>
      </div>
      <div class="row2">
        <div class="field"><label>检测范围起</label><input type="number" id="an-xmin" value="${a.xmin ?? ""}" step="0.1" placeholder="自动"></div>
        <div class="field"><label>检测范围止</label><input type="number" id="an-xmax" value="${a.xmax ?? ""}" step="0.1" placeholder="自动"></div>
      </div>
      <div class="row-btns">
        <button class="mini-btn pri" id="an-run">检测峰 / 积分</button>
        <button class="mini-btn" id="an-clear">清除</button>
        <button class="mini-btn" id="an-csv">导出峰表 CSV</button>
      </div>
      <div id="pk-results"></div>
    </div>

    <div class="group sub"><h4>求导 (导数曲线)</h4>
      <div class="row2">
        <div class="field"><label>阶数</label><select id="dv-order">
          <option value="1">一阶 dy/dx</option><option value="2">二阶 d²y/dx²</option></select></div>
        <div class="field"><label>平滑</label><input type="number" id="dv-smooth" value="11" step="2"></div>
      </div>
      <div class="row-btns">
        <button class="mini-btn" id="dv-apply">应用到所有曲线</button>
        <button class="mini-btn" id="dv-off">全部关闭</button>
      </div>
      <div class="hint">导数曲线单位是 mAU/mL，建议画到右侧副轴或做归一化；单条曲线也可在「数据」标签里单独设置。</div>
    </div>

    <div class="group sub"><h4>蛋白序列分析</h4>
      <div class="field col"><textarea id="sq-text" rows="4" placeholder="粘贴蛋白序列 (单字母, 逗号/空格/换行都可以)"></textarea></div>
      <div class="row2">
        <div class="field"><label>A280 读数</label><input type="number" id="sq-a280" step="0.01" placeholder="可选"></div>
        <div class="field"><label>&nbsp;</label><button class="mini-btn pri" id="sq-run">分析序列</button></div>
      </div>
      <div id="sq-results"></div>
    </div>

    <div class="group sub"><h4>SEC 分子量校准 (Kav vs log MW)</h4>
      <div class="field col"><textarea id="mw-std" rows="4" placeholder="每行一条标准品:  洗脱体积(mL),分子量(Da)">${esc(state.mw.standards)}</textarea></div>
      <div class="row2">
        <div class="field"><label>V0 (void, mL)</label><input type="number" id="mw-v0" value="${state.mw.v0}" step="0.1"></div>
        <div class="field"><label>Vt (total, mL)</label><input type="number" id="mw-vt" value="${state.mw.vt}" step="0.1"></div>
      </div>
      <div class="row-btns"><button class="mini-btn pri" id="mw-run">拟合 + 用检测峰算 MW</button></div>
      <div id="mw-results"></div>
    </div>

    <div class="group sub"><h4>辅因子化学计量 (如 FMN)</h4>
      <div class="row2">
        <div class="field"><label>ε 蛋白 @280</label><input type="number" id="cf-eps-p" value="${state.cof.eps_protein}" step="100"></div>
        <div class="field"><label>ε 辅因子 @λ</label><input type="number" id="cf-eps-c" value="${state.cof.eps_cofactor}" step="100"></div>
      </div>
      <div class="row2">
        <div class="field"><label>ε 辅因子 @280</label><input type="number" id="cf-eps-c280" value="${state.cof.eps_cofactor_280}" step="100"></div>
        <div class="field"><label>配对容差 (mL)</label><input type="number" id="cf-tol" value="1.2" step="0.1"></div>
      </div>
      <div class="row-btns"><button class="mini-btn pri" id="cf-run">按峰面积算比例</button>
        <button class="mini-btn" id="cf-fromseq">ε 蛋白取自序列</button></div>
      <div id="cf-results"></div>
    </div>`;

  // bind
  const bind = (id, ev, fn) => { const e = $("#" + id); if (e) e.addEventListener(ev, fn); };
  bind("fx-show", "change", e => { state.frac.show = e.target.checked; renderPreview(); });
  bind("fx-run", "change", e => { state.frac.run = e.target.value; updateFracInfo(); renderPreview(); });
  bind("fx-color", "input", e => { state.frac.color = e.target.value; renderPreview(); });
  bind("fx-ticks", "change", e => { state.frac.show_ticks = e.target.checked; renderPreview(); });
  bind("fx-label", "change", e => { state.frac.show_label = e.target.checked; renderPreview(); });
  bind("an-prom", "input", e => { state.an.prominence = parseFloat(e.target.value) || 0; });
  bind("an-dist", "input", e => { state.an.min_distance = parseFloat(e.target.value) || 0; });
  bind("an-smooth", "input", e => { state.an.smooth = parseInt(e.target.value) || 0; });
  bind("an-show", "change", e => { state.showPeaks = e.target.checked; renderPreview(); });
  bind("an-xmin", "input", e => { state.an.xmin = e.target.value === "" ? null : parseFloat(e.target.value); });
  bind("an-xmax", "input", e => { state.an.xmax = e.target.value === "" ? null : parseFloat(e.target.value); });
  bind("an-run", "click", detectPeaks);
  bind("an-clear", "click", () => { state.peaks = []; renderPeakTable(); renderPreview(); });
  bind("an-csv", "click", exportPeakCsv);
  bind("dv-apply", "click", () => {
    const o = parseInt($("#dv-order").value), sm = parseInt($("#dv-smooth").value) || 0;
    activeSeries().forEach(it => { state.overrides[it.key] = state.overrides[it.key] || {}; state.overrides[it.key].deriv = o; state.overrides[it.key].deriv_smooth = sm; });
    refreshStaticViews(); renderPreview();
  });
  bind("dv-off", "click", () => {
    activeSeries().forEach(it => { if (state.overrides[it.key]) { delete state.overrides[it.key].deriv; delete state.overrides[it.key].deriv_smooth; } });
    refreshStaticViews(); renderPreview();
  });
  bind("sq-run", "click", seqAnalysis);
  bind("mw-run", "click", mwCalibrate);
  bind("cf-run", "click", computeCofactor);
  bind("cf-fromseq", "click", () => {
    if (state.seq.result && state.seq.result.eps280) { state.cof.eps_protein = state.seq.result.eps280; $("#cf-eps-p").value = state.cof.eps_protein; }
    else alert("请先做一次序列分析");
  });
  ["sq-text", "sq-a280", "mw-std", "mw-v0", "mw-vt", "cf-eps-p", "cf-eps-c", "cf-eps-c280"].forEach(id => {
    const e = $("#" + id); if (e) e.addEventListener("input", () => saveAnalysisInputs());
  });
  renderAnalysisSeries();
  updateFracInfo();
  renderPeakTable();
  renderSeqResult();
  renderMwResult();
  renderCofResult();
}

function saveAnalysisInputs() {
  const g = id => { const e = $("#" + id); return e ? e.value : ""; };
  state.seq.text = g("sq-text"); state.seq.a280 = g("sq-a280");
  state.mw.standards = g("mw-std");
  state.mw.v0 = parseFloat(g("mw-v0")) || 0; state.mw.vt = parseFloat(g("mw-vt")) || 0;
  state.cof.eps_protein = parseFloat(g("cf-eps-p")) || 0;
  state.cof.eps_cofactor = parseFloat(g("cf-eps-c")) || 0;
  state.cof.eps_cofactor_280 = parseFloat(g("cf-eps-c280")) || 0;
}

function renderAnalysisSeries() {
  const box = $("#an-series"); if (!box) return;
  const items = activeSeries();
  if (!items.length) { box.innerHTML = `<div class="hint">先选择通道 / Run</div>`; return; }
  box.innerHTML = items.map(it => {
    const ov = state.overrides[it.key] || {};
    const color = ov.color || it.run.color;
    const on = !state.an.exclude[it.key];
    return `<label style="display:flex;align-items:center;gap:6px;font-size:12px">
      <input type="checkbox" class="an-sel" data-key="${esc(it.key)}" ${on ? "checked" : ""}>
      <span class="dot" style="background:${color}"></span>${esc(seriesLabel(it, ov))}
      <small style="color:#6b7785">(${esc(it.ch)})</small></label>`;
  }).join("");
  $$(".an-sel", box).forEach(c => c.addEventListener("change", () => {
    if (c.checked) delete state.an.exclude[c.dataset.key];
    else state.an.exclude[c.dataset.key] = true;
  }));
}

function updateFracInfo() {
  const box = $("#fx-info"); if (!box) return;
  const rid = fracRunId();
  const run = state.runs.find(r => r.id === rid);
  const f = run && run.fractionation;
  if (!f) { box.innerHTML = `<span style="color:#8a94a2">该 Run 没有收集信息</span>`; return; }
  box.innerHTML =
    `<div class="kv"><span>Run</span><b>${esc(run.label)}</b></div>
     <div class="kv"><span>收集区间</span><b>${f.start_volume.toFixed(2)} → ${f.end_volume.toFixed(2)} mL</b></div>
     <div class="kv"><span>分级</span><b>${f.count} × ${f.size_ml} mL</b></div>
     <div class="kv"><span>板/孔</span><b>${esc(f.plate)} · ${esc(f.wells[0].well)}–${esc(f.wells[f.wells.length-1].well)}</b></div>
     <div class="kv"><span>切到废液</span><b>${f.waste_volume ? f.waste_volume.toFixed(2) + " mL" : "-"}</b></div>`;
}

async function detectPeaks() {
  saveAnalysisInputs();
  const series = buildSeriesSpec().filter(s => !state.an.exclude[s.run + "|" + s.curve] && s.show !== false);
  if (!series.length) { alert("没有可分析的曲线"); return; }
  const xr = [state.an.xmin, state.an.xmax];
  setStatus("积分中…", "busy");
  try {
    const res = await fetch("/api/analyze", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec: buildSpec(), series, x_kind: state.spec.axes.x_kind,
        x_range: xr, prominence: state.an.prominence, min_distance: state.an.min_distance, smooth: state.an.smooth }),
    });
    const j = await res.json();
    state.peaks = j.peaks || [];
    renderPeakTable(); renderPreview();
    setStatus(`检测到 ${state.peaks.length} 个峰`);
  } catch (e) { setStatus("积分失败: " + e.message, "err"); }
}

function renderPeakTable() {
  const box = $("#pk-results"); if (!box) return;
  if (!state.peaks.length) { box.innerHTML = `<div class="hint">还没有检测结果</div>`; return; }
  const xk = state.spec.axes.x_kind;
  const unit = xk === "time" ? "min" : (xk === "cv" ? "CV" : "mL");
  const rows = state.peaks.map((p, i) => {
    p.pk_label = p.pk_label || ("P" + (i + 1));
    return `<tr><td><span class="dot" style="background:${p.color}"></span> ${esc(p.label)}</td>
      <td>${p.pk_label}</td><td>${p.apex_x.toFixed(2)}</td><td>${p.height.toFixed(1)}</td>
      <td>${p.area.toFixed(1)}</td><td>${p.area_pct.toFixed(1)}</td><td>${p.fwhm.toFixed(2)}</td>
      <td>${p.start_x.toFixed(2)}–${p.end_x.toFixed(2)}</td></tr>`;
  }).join("");
  box.innerHTML = `<div class="pk-wrap"><table class="pk-table">
    <thead><tr><th>曲线</th><th>峰</th><th>顶点(${unit})</th><th>高度</th><th>面积</th><th>%</th><th>FWHM</th><th>区间(${unit})</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <div class="hint">面积为「谷-谷 + 线性基线」积分，单位 mAU·${unit}。</div>`;
}

function exportPeakCsv() {
  if (!state.peaks.length) { alert("没有峰可导出"); return; }
  const xk = state.spec.axes.x_kind;
  const head = ["series", "run", "curve", "peak", "apex_x", "height", "area", "area_pct", "fwhm", "start_x", "end_x", "x_unit", "unit"];
  const lines = [head.join(",")];
  state.peaks.forEach((p, i) => {
    const lbl = p.pk_label || ("P" + (i + 1));
    lines.push([csvq(p.label), csvq(p.run), csvq(p.curve), lbl,
      p.apex_x.toFixed(4), p.height.toFixed(4), p.area.toFixed(4), p.area_pct.toFixed(3),
      p.fwhm.toFixed(4), p.start_x.toFixed(4), p.end_x.toFixed(4), xk, p.unit || ""].join(","));
  });
  download(new Blob([lines.join("\n")], { type: "text/csv" }), "sec_peaks.csv");
}
function csvq(s) { s = String(s == null ? "" : s); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }

async function seqAnalysis() {
  saveAnalysisInputs();
  if (!state.seq.text.trim()) { alert("请粘贴序列"); return; }
  const res = await fetch("/api/sequence", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seq: state.seq.text, a280: state.seq.a280 }) });
  state.seq.result = await res.json();
  renderSeqResult();
}
function renderSeqResult() {
  const box = $("#sq-results"); if (!box) return;
  const r = state.seq.result;
  if (!r) { box.innerHTML = ""; return; }
  if (r.error) { box.innerHTML = `<div class="rbox" style="color:#c0392b">${esc(r.error)}</div>`; return; }
  const f = (v, n = 2) => (v == null ? "-" : Number(v).toFixed(n));
  box.innerHTML = `<div class="rbox">
    <div class="kv"><span>长度</span><b>${r.length} aa</b></div>
    <div class="kv"><span>分子量 (平均)</span><b>${(r.mw_avg / 1000).toFixed(2)} kDa</b></div>
    <div class="kv"><span>分子量 (单同位素)</span><b>${(r.mw_mono / 1000).toFixed(2)} kDa</b></div>
    <div class="kv"><span>等电点 pI</span><b>${f(r.pI)}</b></div>
    <div class="kv"><span>电荷 @pH7</span><b>${f(r.charge_pH7)}</b></div>
    <div class="kv"><span>ε280</span><b>${r.eps280} M⁻¹cm⁻¹</b></div>
    <div class="kv"><span>A280 (0.1%, 1 g/L)</span><b>${f(r.a280_0_1pct, 3)}</b></div>
    <div class="kv"><span>W / Y / C</span><b>${r.nW} / ${r.nY} / ${r.nC}</b></div>
    <div class="kv"><span>GRAVY</span><b>${f(r.gravy, 3)}</b></div>
    <div class="kv"><span>芳香性</span><b>${f(r.aromaticity, 3)}</b></div>
    ${r.conc_mg_ml != null ? `<div class="kv"><span>浓度</span><b>${f(r.conc_mg_ml, 3)} mg/mL = ${f(r.conc_uM, 2)} µM</b></div>` : ""}
  </div>`;
}

function parseStandards(txt) {
  return txt.split(/[\n;]+/).map(line => line.split(/[,\s\t]+/).filter(Boolean))
    .filter(a => a.length >= 2).map(a => ({ volume: parseFloat(a[0]), mw: parseFloat(a[1]) }))
    .filter(s => !isNaN(s.volume) && !isNaN(s.mw));
}
async function mwCalibrate() {
  saveAnalysisInputs();
  const std = parseStandards(state.mw.standards);
  const vols = state.peaks.map(p => p.apex_x);
  const res = await fetch("/api/mw", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ standards: std, volumes: vols, v0: state.mw.v0, vt: state.mw.vt }) });
  state.mw.result = await res.json();
  if (state.mw.result && state.mw.result.predictions) {
    state.mw.result.predictions.forEach((pr, i) => { if (state.peaks[i]) state.peaks[i].mw = pr.mw; });
  }
  renderMwResult(); renderPeakTable();
}
function renderMwResult() {
  const box = $("#mw-results"); if (!box) return;
  const r = state.mw.result; if (!r) { box.innerHTML = ""; return; }
  if (r.error) { box.innerHTML = `<div class="rbox" style="color:#c0392b">${esc(r.error)}</div>`; return; }
  const rows = (r.predictions || []).map((p, i) =>
    `<div class="kv"><span>峰 ${i + 1} @ ${p.volume.toFixed(2)} mL (Kav ${p.kav.toFixed(3)})</span><b>${(p.mw / 1000).toFixed(1)} kDa</b></div>`).join("");
  box.innerHTML = `<div class="rbox">
    <div class="kv"><span>方程</span><b>log10(MW) = ${r.slope.toFixed(3)}·Kav + ${r.intercept.toFixed(3)}</b></div>
    <div class="kv"><span>R²</span><b>${r.r2.toFixed(4)}</b></div>
    ${rows}</div>`;
}

async function computeCofactor() {
  saveAnalysisInputs();
  const tol = parseFloat($("#cf-tol").value) || 1.2;
  const pk = state.peaks;
  const prot = pk.filter(p => p.channel === "A280");
  const cof = pk.filter(p => p.channel && p.channel !== "A280");
  if (!prot.length || !cof.length) { alert("请先检测 A280 和 A455 的峰"); return; }
  const pairs = [];
  prot.forEach(p => {
    let best = null, bd = 1e9;
    cof.forEach(c => { const d = Math.abs(c.apex_x - p.apex_x); if (d < bd) { bd = d; best = c; } });
    if (best && bd <= tol) pairs.push({ label: p.label + " @" + p.apex_x.toFixed(2), area_protein: p.area, area_cofactor: best.area });
  });
  const res = await fetch("/api/cofactor", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pairs, eps_protein: state.cof.eps_protein, eps_cofactor: state.cof.eps_cofactor,
      eps_cofactor_at_280: state.cof.eps_cofactor_280 }) });
  state.cof.result = await res.json();
  renderCofResult();
}
function renderCofResult() {
  const box = $("#cf-results"); if (!box) return;
  const r = state.cof.result; if (!r) { box.innerHTML = ""; return; }
  if (r.error) { box.innerHTML = `<div class="rbox" style="color:#c0392b">${esc(r.error)}</div>`; return; }
  const rows = (r.rows || []).map(x =>
    `<tr><td>${esc(x.label)}</td><td>${Number(x.area_protein_corrected).toFixed(1)}</td>
     <td>${Number(x.area_cofactor).toFixed(1)}</td><td><b>${Number(x.ratio).toFixed(3)}</b></td></tr>`).join("");
  box.innerHTML = `<div class="pk-wrap"><table class="pk-table">
    <thead><tr><th>峰</th><th>A280 面积(校正)</th><th>辅因子面积</th><th>辅因子:蛋白</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <div class="hint">n = (面积/ε)，比率 = (辅因子/ε_辅) / (蛋白/ε_蛋白)。ε 单位 M⁻¹cm⁻¹。</div>`;
}

/* --------------------------------------------------------- design screen */
function buildScreenPane() {
  const pane = $('[data-pane="screen"]');
  if (!pane) return;
  const p = state.screen.params;
  const chOpts = runsChannelOptions();
  pane.innerHTML =
    `<div class="group sub"><h4>设计筛选（单体峰 FMN 装载）</h4>
      <div class="scr-tools">
        <div class="field"><label>蛋白通道</label><select id="scr-ch-p">${chOpts.protein}</select></div>
        <div class="field"><label>辅因子通道</label><select id="scr-ch-c">${chOpts.cofactor}</select></div>
        <div class="field"><label>基线窗口 (mL) 起</label><input type="number" id="scr-blo" value="${p.baseline_win[0]}" step="0.1"></div>
        <div class="field"><label>基线窗口 (mL) 止</label><input type="number" id="scr-bhi" value="${p.baseline_win[1]}" step="0.1"></div>
        <div class="field"><label>左谷搜索 起</label><input type="number" id="scr-vlo" value="${p.valley_left[0]}" step="0.1"></div>
        <div class="field"><label>左谷搜索 止</label><input type="number" id="scr-vhi" value="${p.valley_left[1]}" step="0.1"></div>
        <div class="field"><label>右谷搜索 起</label><input type="number" id="scr-rlo" value="${p.valley_right[0]}" step="0.1"></div>
        <div class="field"><label>右谷搜索 止</label><input type="number" id="scr-rhi" value="${p.valley_right[1]}" step="0.1"></div>
        <div class="field"><label>ε 蛋白 @280</label><input type="number" id="scr-eps-p" value="${p.eps_protein}" step="100"></div>
        <div class="field"><label>ε 辅因子 @λ</label><input type="number" id="scr-eps-c" value="${p.eps_cofactor}" step="100"></div>
        <div class="field"><label>ε 辅因子 @280</label><input type="number" id="scr-eps-c280" value="${p.eps_cofactor_at_protein}" step="100"></div>
        <div class="field"><label>在图上画窗口</label><input type="checkbox" id="scr-showwin" ${state.screen.show_win ? "checked" : ""}></div>
      </div>
      <div class="row-btns">
        <button class="mini-btn pri" id="scr-run">计算排名</button>
        <button class="mini-btn" id="scr-csv">导出 CSV</button>
        <button class="mini-btn" id="scr-fig">导出排名柱状图</button>
      </div>
      <div class="scr-note">固定规则：恒定基线（平台区中位数）→ 单体峰窗口 [两峰之间谷, 回落到基线谷]
        → A280/A455 用同一窗口积分 → ρ=A455/A280，r=(A455/ε455)/(A280校正/ε280)。
        换柱子/波长时改上面各搜索窗口即可。</div>
      <div id="scr-results"></div>
    </div>`;

  const bind = (id, ev, fn) => { const e = $("#" + id); if (e) e.addEventListener(ev, fn); };
  bind("scr-ch-p", "change", e => { state.screen.params.protein_channel = e.target.value; });
  bind("scr-ch-c", "change", e => { state.screen.params.cofactor_channel = e.target.value; });
  bind("scr-blo", "input", e => { state.screen.params.baseline_win[0] = parseFloat(e.target.value) || 0; });
  bind("scr-bhi", "input", e => { state.screen.params.baseline_win[1] = parseFloat(e.target.value) || 0; });
  bind("scr-vlo", "input", e => { state.screen.params.valley_left[0] = parseFloat(e.target.value) || 0; });
  bind("scr-vhi", "input", e => { state.screen.params.valley_left[1] = parseFloat(e.target.value) || 0; });
  bind("scr-rlo", "input", e => { state.screen.params.valley_right[0] = parseFloat(e.target.value) || 0; });
  bind("scr-rhi", "input", e => { state.screen.params.valley_right[1] = parseFloat(e.target.value) || 0; });
  bind("scr-eps-p", "input", e => { state.screen.params.eps_protein = parseFloat(e.target.value) || 0; });
  bind("scr-eps-c", "input", e => { state.screen.params.eps_cofactor = parseFloat(e.target.value) || 0; });
  bind("scr-eps-c280", "input", e => { state.screen.params.eps_cofactor_at_protein = parseFloat(e.target.value) || 0; });
  bind("scr-showwin", "change", e => { state.screen.show_win = e.target.checked; renderPreview(); });
  bind("scr-run", "click", runScreen);
  bind("scr-csv", "click", screenCsv);
  bind("scr-fig", "click", screenFigure);
  renderScreenTable();
}

function runsChannelOptions() {
  const curves = new Set();
  state.runs.forEach(r => (r.curves || []).forEach(c => curves.add(c.name)));
  const names = [...curves];
  const mk = v => names.map(n => `<option value="${esc(n)}" ${v === n ? "selected" : ""}>${esc(n)}</option>`).join("");
  return { protein: mk(state.screen.params.protein_channel), cofactor: mk(state.screen.params.cofactor_channel) };
}

async function runScreen() {
  if (!state.runs.length) { alert("请先导入数据"); return; }
  setStatus("计算排名…", "busy");
  try {
    const res = await fetch("/api/screen", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec: buildSpec(), params: state.screen.params }),
    });
    const j = await res.json();
    state.screen.rows = j.rows || [];
    state.screen.rows.forEach(r => {
      const run = state.runs.find(x => x.id === r.run);
      if (run) r.color = run.color;
    });
    renderScreenTable(); renderPreview();
    setStatus(`已排名 ${state.screen.rows.length} 个设计`);
  } catch (e) { setStatus("计算失败: " + e.message, "err"); }
}

function renderScreenTable() {
  const box = $("#scr-results"); if (!box) return;
  const rows = state.screen.rows;
  if (!rows.length) { box.innerHTML = `<div class="hint">点「计算排名」得到各设计的 FMN 装载排序。</div>`; return; }
  const fmt = (v, n = 3) => (v == null || isNaN(v)) ? "-" : Number(v).toFixed(n);
  const htm = rows.map((r, i) => {
    const cls = i === 0 ? "r1" : (i === 1 ? "r2" : (i === 2 ? "r3" : ""));
    return `<tr>
      <td><span class="scr-rank ${cls}">${i + 1}</span> ${esc(r.run)}</td>
      <td>${fmt(r.r_monomer)}</td><td>${fmt(r.rho_monomer)}</td>
      <td>${fmt(r.h_ratio_monomer)}</td><td>${fmt(r.A280_monomer, 1)}</td><td>${fmt(r.A455_monomer, 1)}</td>
      <td>${fmt(r.apex_mL, 2)}</td><td>${fmt(r.mw_kda, 1)}</td>
      <td>${r.window[0].toFixed(2)}–${r.window[1].toFixed(2)}</td></tr>`;
  }).join("");
  box.innerHTML = `<div class="scr-wrap"><table class="scr-table">
    <thead><tr><th>排名 / Run</th><th>r (mol/mol)</th><th>ρ=A455/A280</th><th>峰高比</th>
      <th>A280 面积</th><th>A455 面积</th><th>apex(mL)</th><th>~MW(kDa)</th><th>窗口(mL)</th></tr></thead>
    <tbody>${htm}</tbody></table></div>
    <div class="scr-legend">r = 摩尔装载比（需 ε）；ρ 与峰高比为免假设指标；面积单位 mAU·mL；窗口为单体峰积分区间。</div>`;
}

function screenCsv() {
  if (!state.screen.rows.length) { alert("先计算排名"); return; }
  const head = ["rank", "run", "r_monomer", "rho_monomer", "h_ratio_monomer", "A280_monomer",
    "A455_monomer", "A280_monomer_corrected", "apex_mL", "mw_kda", "kav", "window_lo", "window_hi",
    "baseline_protein", "baseline_cofactor", "A280_early", "A455_early", "rho_early"];
  const lines = [head.join(",")];
  state.screen.rows.forEach((r, i) => {
    lines.push([i + 1, csvq(r.run), r.r_monomer, r.rho_monomer, r.h_ratio_monomer,
      r.A280_monomer, r.A455_monomer, r.A280_monomer_corrected, r.apex_mL, r.mw_kda, r.kav,
      r.window[0], r.window[1], r.baseline_protein, r.baseline_cofactor,
      r.A280_early, r.A455_early, r.rho_early].join(","));
  });
  download(new Blob([lines.join("\n")], { type: "text/csv" }), "fmn_binding_ranking.csv");
}

async function screenFigure() {
  if (!state.screen.rows.length) { alert("先计算排名"); return; }
  const fmt = prompt("格式 (pdf/svg/png/tiff)：", "pdf") || "pdf";
  setStatus("生成排名图…", "busy");
  try {
    const res = await fetch("/api/screen_figure", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        spec: buildSpec(), rows: state.screen.rows, metric: state.screen.metric, format: fmt,
        colors: state.screen.rows.map(r => state.runs.find(x => x.id === r.run)?.color || "#C0392B"),
      }),
    });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || res.statusText); }
    download(await res.blob(), `fmn_screen_${state.screen.metric}.${fmt}`);
    setStatus("已导出排名图");
  } catch (e) { setStatus("导出失败: " + e.message, "err"); }
}

function bindInputsTo(root) {
  $$("[data-path]", root).forEach(inp => {
    inp.addEventListener("input", () => onInput(inp));
    inp.addEventListener("change", () => onInput(inp));
  });
}
function onInput(inp) {
  const path = inp.dataset.path;
  let v;
  if (inp.type === "checkbox") v = inp.checked;
  else if (inp.type === "number") v = inp.value === "" ? null : parseFloat(inp.value);
  else v = inp.value;
  setPath(state.spec, path, v);
  if (path === "axes.x_kind") syncXLabel(v);
  renderPreview();
}
function syncXLabel(kind) {
  const map = { volume: "Elution volume (mL)", time: "Time (min)", cv: "Elution volume (CV)" };
  state.spec.axes.x_label = map[kind] || "x";
  const inp = $('[data-path="axes.x_label"]'); if (inp) inp.value = state.spec.axes.x_label;
  ["axes.x_range.0", "axes.x_range.1"].forEach(p => { const e = $(`[data-path="${p}"]`); if (e) { e.value = ""; setPath(state.spec, p, null); } });
}

/* --------------------------------------------------------- run list view */
function renderRuns() {
  $("#run-count").textContent = state.runs.length;
  const list = $("#run-list"); list.innerHTML = "";
  state.runs.forEach((run, i) => {
    const card = el(`<div class="run-card ${run.visible ? "" : "off"}">
      <input type="checkbox" ${run.visible ? "checked" : ""} title="显示/隐藏">
      <span class="swatch" style="background:${run.color}"><input type="color" value="${run.color}"></span>
      <div class="run-body">
        <div class="run-name" title="${esc(run.name)}">${esc(run.label)}</div>
        <div class="run-meta">${esc(run.meta.column || "")} · ${esc(run.meta.flow || "")}${esc(run.meta.flow_unit || "")}</div>
        <div class="run-tags">
          ${CHANNELS.filter(c => run.channelCurve[c]).map(c => `<span class="tag uv">${c}</span>`).join("")}
          ${run.fractionation ? `<span class="tag tag-frac">收集 ${run.fractionation.start_volume.toFixed(1)}–${run.fractionation.end_volume.toFixed(1)} mL</span>` : ""}
          <span class="tag">${run.curves.length} 通道</span>
        </div>
      </div>
      <button class="icon-btn ren" title="重命名">✎</button>
      <button class="icon-btn del" title="移除">✕</button>
    </div>`);
    const visChk = card.querySelector(":scope > input");
    visChk.addEventListener("change", () => { run.visible = visChk.checked; renderRuns(); refreshStaticViews(); renderPreview(); });
    card.querySelector(".swatch input").addEventListener("input", e => {
      run.color = e.target.value; card.querySelector(".swatch").style.background = e.target.value; renderPreview();
    });
    card.querySelector(".ren").addEventListener("click", () => {
      const v = prompt("重命名 Run", run.label); if (v != null) { run.label = v; renderRuns(); refreshStaticViews(); renderPreview(); }
    });
    card.querySelector(".del").addEventListener("click", () => { state.runs.splice(i, 1); renderRuns(); refreshStaticViews(); renderPreview(); });
    list.appendChild(card);
  });
  renderChannelToggles();
}

function renderChannelToggles() {
  const box = $("#channel-toggles"); box.innerHTML = "";
  CHANNELS.forEach(ch => {
    const n = state.runs.filter(r => r.channelCurve && r.channelCurve[ch]).length;
    const chip = el(`<span class="chip ${state.channels[ch] ? "on" : ""}">${ch} <small>${n}</small></span>`);
    chip.addEventListener("click", () => { state.channels[ch] = !state.channels[ch]; renderChannelToggles(); refreshStaticViews(); renderPreview(); });
    box.appendChild(chip);
  });
  const extra = new Set();
  state.runs.forEach(r => (r.curves || []).forEach(c => { if (!c.channel && c.unit === "mAU" && /UV/.test(c.name)) extra.add(c.name); }));
  if (extra.size) box.appendChild(el(`<div class="hint" style="flex:1 0 100%">未识别的 UV 通道：${esc([...extra].join(", "))}</div>`));
}

/* ---------------------------------------------------------- series (data) */
function renderSeriesTable() {
  const pane = $('[data-pane="series"]');
  const items = activeSeries();
  if (!items.length) { pane.innerHTML = `<div class="hint">选择通道 / Run 后，这里会列出每条曲线。</div>`; return; }
  const rows = items.map(it => {
    const ov = state.overrides[it.key] || {};
    const color = ov.color || it.run.color;
    const label = seriesLabel(it, ov);
    return `<tr data-key="${esc(it.key)}">
      <td><input type="checkbox" class="s-show" ${ov.show !== false ? "checked" : ""}></td>
      <td><input type="color" class="s-color" value="${color}" style="width:26px;height:22px;padding:0"></td>
      <td><input type="text" class="s-label" value="${esc(label)}"></td>
      <td><select class="s-axis">
        <option value="left" ${(ov.axis || "left") === "left" ? "selected" : ""}>左</option>
        <option value="right" ${ov.axis === "right" ? "selected" : ""}>右</option>
      </select></td>
      <td><button class="icon-btn s-adv" title="高级">⚙</button></td>
    </tr>
    <tr class="adv-row" hidden><td colspan="5"><div class="adv-grid">
      <label>线宽<input type="number" class="s-lw" step="0.1" value="${ov.lw != null ? ov.lw : ""}" placeholder="默认"></label>
      <label>线型<select class="s-ls"><option value="">默认</option>${["-", "--", ":", "-."].map(l => `<option value="${l}" ${ov.ls === l ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label>不透明度<input type="number" class="s-alpha" step="0.05" value="${ov.alpha != null ? ov.alpha : ""}" placeholder="默认"></label>
      <label>基线<select class="s-baseline"><option value="">默认</option>${["none", "start", "min", "linear"].map(b => `<option value="${b}" ${ov.baseline === b ? "selected" : ""}>${b}</option>`).join("")}</select></label>
      <label>归一化<select class="s-scale"><option value="">默认</option>${["none", "max", "minmax"].map(b => `<option value="${b}" ${ov.scale === b ? "selected" : ""}>${b}</option>`).join("")}</select></label>
      <label>平滑<input type="number" class="s-smooth" step="1" value="${ov.smooth != null ? ov.smooth : ""}" placeholder="默认"></label>
      <label>导数<select class="s-deriv"><option value="">默认</option>${["0", "1", "2"].map(d => `<option value="${d}" ${ov.deriv === +d ? "selected" : ""}>${d === "0" ? "原始" : d + " 阶"}</option>`).join("")}</select></label>
    </div></td></tr>`;
  }).join("");
  pane.innerHTML = `<div class="group"><h3>每条曲线设置</h3>
    <table class="ser-table"><thead><tr><th></th><th>色</th><th>图例名称</th><th>轴</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    <div class="hint">留空 = 沿用「曲线」标签里的全局默认。⚙ 展开高级设置。</div></div>`;
  bindSeriesTable(pane);
}

function bindSeriesTable(pane) {
  const setOv = (key, k, v) => {
    state.overrides[key] = state.overrides[key] || {};
    if (v === "" || v === null) delete state.overrides[key][k]; else state.overrides[key][k] = v;
  };
  $$(".ser-table tbody tr[data-key]", pane).forEach(tr => {
    const key = tr.dataset.key, adv = tr.nextElementSibling;
    tr.querySelector(".s-adv").addEventListener("click", () => { adv.hidden = !adv.hidden; });
    tr.querySelector(".s-show").addEventListener("change", e => { setOv(key, "show", e.target.checked); renderPreview(); });
    tr.querySelector(".s-color").addEventListener("input", e => { setOv(key, "color", e.target.value); renderPreview(); });
    tr.querySelector(".s-label").addEventListener("input", e => { setOv(key, "label", e.target.value); renderPreview(); });
    tr.querySelector(".s-axis").addEventListener("change", e => { setOv(key, "axis", e.target.value); renderPreview(); });
    const num = (sel, k, isInt) => {
      const n = adv.querySelector(sel); if (!n) return;
      n.addEventListener("input", e => { setOv(key, k, e.target.value === "" ? "" : (isInt ? parseInt(e.target.value) : parseFloat(e.target.value))); renderPreview(); });
    };
    num(".s-lw", "lw"); num(".s-alpha", "alpha"); num(".s-smooth", "smooth", true);
    adv.querySelector(".s-ls").addEventListener("change", e => { setOv(key, "ls", e.target.value); renderPreview(); });
    adv.querySelector(".s-baseline").addEventListener("change", e => { setOv(key, "baseline", e.target.value); renderPreview(); });
    adv.querySelector(".s-scale").addEventListener("change", e => { setOv(key, "scale", e.target.value); renderPreview(); });
    const dv = adv.querySelector(".s-deriv");
    if (dv) dv.addEventListener("change", e => { setOv(key, "deriv", e.target.value === "" ? "" : parseInt(e.target.value)); renderPreview(); });
  });
}

/* --------------------------------------------------------------- presets */
function applyPreset(key) {
  const p = PRESETS[key]; if (!p) return;
  const f = state.spec.figure;
  f.width_mm = p.width; f.height_mm = p.height; f.base_size = p.base;
  f.title_size = +(p.base * 1.25).toFixed(1);
  f.subtitle_size = p.base; f.panel_size = +(p.base * 1.4).toFixed(1);
  state.spec.legend.font_size = +(p.base * 0.9).toFixed(1);
  buildPanes(); renderPreview();
}
function applyPalette(name) {
  const pal = PALETTES[name] || PALETTES["journal"];
  state.runs.forEach((r, i) => { r.color = pal[i % pal.length]; });
  state.overrides = {};
  renderRuns(); refreshStaticViews(); renderPreview();
}
function refreshStaticViews() {
  renderSeriesTable(); fillCsvSeries();
  renderAnalysisSeries(); updateFracInfo();
}

/* ------------------------------------------------------------- data load */
async function loadFolder() {
  setStatus("扫描文件夹…", "busy");
  try {
    const res = await fetch("/api/load_folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ folder: window.DATA_DIR }) });
    const j = await res.json();
    const added = j.added || [], failed = added.filter(r => r.error);
    ingest(added);
    setStatus(`已加载 ${state.runs.length} 个 Run${failed.length ? `；导入失败：${failed.map(r => r.error).join(" / ")}` : ""}`, failed.length ? "err" : "");
  } catch (e) { setStatus("加载失败: " + e.message, "err"); }
}
async function uploadFiles(files) {
  const fd = new FormData();
  Array.from(files).forEach(f => fd.append("files", f));
  setStatus("解析中…", "busy");
  try {
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await res.json();
    const added = j.added || [], failed = added.filter(r => r.error);
    ingest(added);
    setStatus(`已加载 ${state.runs.length} 个 Run${failed.length ? `；导入失败：${failed.map(r => r.error).join(" / ")}` : ""}`, failed.length ? "err" : "");
  } catch (e) { setStatus("导入失败: " + e.message, "err"); }
}

async function saveProject() {
  setStatus("保存项目中…", "busy");
  try {
    const res = await fetch("/api/project/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state })
    });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || res.statusText); }
    download(await res.blob(), "sec_studio_project.secproj");
    setStatus("项目已保存");
  } catch (e) { setStatus("项目保存失败: " + e.message, "err"); }
}

async function openProject(file) {
  const fd = new FormData();
  fd.append("file", file);
  setStatus("打开项目中…", "busy");
  try {
    const res = await fetch("/api/project/import", { method: "POST", body: fd });
    const result = await res.json();
    if (!res.ok) throw new Error(result.error || res.statusText);
    const restored = result.state || {};
    const savedRuns = new Map((restored.runs || []).map(r => [r.id, r]));
    Object.assign(state, restored);
    state.runs = (result.runs || []).map(run => ({ ...run, ...(savedRuns.get(run.id) || {}) }));
    renderRuns();
    refreshStaticViews();
    buildAnalysisPane();
    buildScreenPane();
    buildPanes();
    renderPreview();
    setStatus(`项目已打开：${state.runs.length} 个 Run`);
  } catch (e) { setStatus("项目打开失败: " + e.message, "err"); }
}

function ingest(added) {
  const pal = PALETTES["journal"];
  const have = new Set(state.runs.map(r => r.id));
  added.forEach(r => {
    if (r.error) { console.warn(r.error); return; }
    if (have.has(r.id)) return;
    r.visible = true; r.label = r.name; r.channelCurve = {};
    (r.curves || []).forEach(c => { if (c.channel) r.channelCurve[c.channel] = c.name; });
    if (!r.color) r.color = pal[state.runs.length % pal.length];
    state.runs.push(r);
  });
  if (state.runs.some(r => r.channelCurve.A280)) state.channels.A280 = true;
  renderRuns(); refreshStaticViews();
  buildAnalysisPane();
  buildScreenPane();
  if (state.runs.length) { showEmpty(false); renderPreview(); }
}

/* ------------------------------------------------------------ export fig */
function openModal(id) { $(id).hidden = false; }
async function exportFigure(batch) {
  const body = {
    spec: buildSpec(), format: $("#fig-format").value, dpi: +$("#fig-dpi").value || 600,
    transparent: $("#fig-transparent").checked, filename: $("#fig-name").value || "sec_figure", batch: !!batch,
  };
  setStatus("导出中…", "busy");
  try {
    const res = await fetch("/api/export_figure", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || res.statusText); }
    download(await res.blob(), `${body.filename}.${batch ? "zip" : body.format}`);
    setStatus("已导出");
  } catch (e) { setStatus("导出失败: " + e.message, "err"); }
}
function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/* ------------------------------------------------------------ export csv */
function fillCsvSeries() {
  const box = $("#csv-series-list"); if (!box) return;
  const items = activeSeries();
  if (!items.length) { box.innerHTML = `<div class="hint">暂无可导出的曲线</div>`; return; }
  box.innerHTML = items.map(it => {
    const ov = state.overrides[it.key] || {};
    const color = ov.color || it.run.color;
    return `<label><input type="checkbox" class="csv-sel" data-key="${esc(it.key)}" checked>
      <span class="dot" style="background:${color}"></span> ${esc(seriesLabel(it, ov))} <small style="color:#6b7785">(${esc(it.ch)})</small></label>`;
  }).join("");
}
function selectedCsvSeries() {
  const keys = new Set($$(".csv-sel:checked").map(c => c.dataset.key));
  return buildSeriesSpec().filter(s => keys.has(s.run + "|" + s.curve));
}
async function exportCsv(batch) {
  const body = {
    spec: buildSpec(), series: selectedCsvSeries(), x_kind: $("#csv-xkind").value,
    x_range: [$("#csv-xmin").value === "" ? null : +$("#csv-xmin").value,
              $("#csv-xmax").value === "" ? null : +$("#csv-xmax").value],
    layout: $("#csv-layout").value, processed: $("#csv-processed").checked,
    filename: $("#csv-name").value || "sec_data.csv", batch: !!batch,
  };
  setStatus("导出中…", "busy");
  try {
    const res = await fetch("/api/export_csv", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || res.statusText); }
    download(await res.blob(), batch ? body.filename.replace(/\.csv$/, "") + "_per_run.zip" : body.filename);
    setStatus("已导出");
  } catch (e) { setStatus("导出失败: " + e.message, "err"); }
}

/* ----------------------------------------------------------------- wiring */
function wire() {
  $("#btn-load-folder").addEventListener("click", loadFolder);
  $("#btn-save-project").addEventListener("click", saveProject);
  $("#project-input").addEventListener("change", e => {
    if (e.target.files.length) openProject(e.target.files[0]);
    e.target.value = "";
  });
  $("#btn-recolor").addEventListener("click", () => applyPalette($("#palette-select") ? $("#palette-select").value : "journal"));
  $("#file-input").addEventListener("change", e => { if (e.target.files.length) uploadFiles(e.target.files); e.target.value = ""; });

  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("hot"); }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("hot"); }));
  dz.addEventListener("drop", e => { if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files); });

  $$("#tabs button").forEach(b => b.addEventListener("click", () => {
    $$("#tabs button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    $$(".pane").forEach(p => p.classList.toggle("active", p.dataset.pane === b.dataset.tab));
    if (b.dataset.tab === "series") renderSeriesTable();
  }));

  $("#preview-dpi").addEventListener("change", renderPreview);
  $("#preview-zoom").addEventListener("change", e => {
    const img = $("#preview"), z = e.target.value;
    if (z === "fit") { img.classList.remove("zoom"); img.style.width = ""; }
    else { img.classList.add("zoom"); img.style.width = (img.naturalWidth * (+z)) + "px"; }
  });
  $("#show-dim").addEventListener("change", e => { state.spec.figure.annotate_size = e.target.checked; renderPreview(); });

  $("#btn-export-fig").addEventListener("click", () => openModal("#modal-fig"));
  $("#btn-export-csv").addEventListener("click", () => { fillCsvSeries(); openModal("#modal-csv"); });
  $("#fig-confirm").addEventListener("click", () => exportFigure(false));
  $("#fig-batch").addEventListener("click", () => exportFigure(true));
  $("#csv-confirm").addEventListener("click", () => exportCsv(false));
  $("#csv-batch").addEventListener("click", () => exportCsv(true));
  $("#csv-all").addEventListener("click", e => { e.preventDefault(); $$(".csv-sel").forEach(c => c.checked = true); });
  $("#csv-none").addEventListener("click", e => { e.preventDefault(); $$(".csv-sel").forEach(c => c.checked = false); });
  $$("[data-close]").forEach(b => b.addEventListener("click", () => { b.closest(".modal").hidden = true; }));
  $$(".modal").forEach(m => m.addEventListener("click", e => { if (e.target === m) m.hidden = true; }));
  document.addEventListener("keydown", e => { if (e.key === "Escape") $$(".modal").forEach(m => m.hidden = true); });
}

/* ------------------------------------------------------------------- init */
buildPanes();
wire();
renderSeriesTable();
setStatus("就绪");
loadFolder();
