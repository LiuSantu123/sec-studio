# SEC Studio — ÄKTA/UNICORN 分子筛(SEC)曲线工作台

一个本地运行的网页应用（类似 GraphPad Prism 的交互方式）：批量导入 ÄKTA/UNICORN 导出的
`*.zip` 结果包或通用 `*.csv` / `*.tsv` 曲线表 → 在浏览器里实时可视化地调整图片格式 / 背景 / 曲线 / 字体 / 坐标轴 / 图表题
等 → 一键应用到所有导入的数据 → 导出**期刊风格**的矢量图 / 高分辨率位图，以及**指定范围、
指定曲线**的 CSV 坐标数据。

---

## 1. 你的数据里有什么？（解析结论）

5 个 zip 全部解析成功，都是同一台 ÄKTA（**NEXTAKTA AVANT**）的 UNICORN 7.8 结果包，
Superdex 75 Increase 10/300 GL（cv = 23.562 mL，流速 0.8 mL/min），体积轴 0–23.5 mL
（≈0–29.5 min）。

| Run (zip)      | A280 (`UV 1_280`) | A230 (`UV 2_230`) | A455 (`UV 3_455`) | A260 |
|----------------|-------------------|-------------------|-------------------|------|
| `e37t3 001.zip`| ✅ 17694 pt, −59…222 mAU | ✅ 3539 pt, −45…2019 | ✅ 3539 pt, −38…32 | ❌ |
| `e90t3 002.zip`| ✅ 17694 pt, −75…1548 | ✅ 3539 pt, −44…3264 | ✅ 3539 pt, −50…348 | ❌ |
| `e95t3 003.zip`| ✅ 17694 pt, −73…850  | ✅ 3539 pt, −40…2778 | ✅ 3539 pt, −48…248 | ❌ |
| `e96t3 004.zip`| ✅ 17694 pt, −58…723  | ✅ 3539 pt, −17…2259 | ✅ 3539 pt, −41…220 | ❌ |
| `mglv3t3 005.zip`| ✅ 17695 pt, −53…146 | ✅ 3539 pt, −19…1028 | ✅ 3539 pt, −35…1274 | ❌ |

* **A280 ✅、A230 ✅、A455 ✅ 都有**（外加 Cond 电导、压力、pH、温度、流速、Digital in/out 等 30+ 通道）。
* **A260 ❌ 没有**——这台仪器这次只采集了 3 个 UV 波长（280/230/455），没有 260 nm 通道，
  所以 `A260/A280` 比值无法计算；`A455` 通常用于 455 nm 散射/浊度或辅因子（如血红素）检测，
  和 A260 不是一回事。若确实需要 A260，需要重新采集（在方法里加入 260 nm 通道）再导出。
* 可以正常画曲线（见 `examples/`）。原始信号带轻微基线漂移，所以 y 有负值；
  UI 里默认已用 “扣起始段均值” 做基线，也可切换“扣全局最小值 / 扣起始线性拟合 / 不扣”。

### SEC 收集范围能不能从文件里看到？—— **能，而且很完整**

`Chrom.1.Xml` 里除了曲线，还有一条 `EventCurves/EventCurve[@EventCurveType="Fraction"]`
（Fraction 事件曲线），逐条记录了每个收集管/孔的切换时间与体积。5 个包解析结果：

| Run | 分级体积 | 收集区间 | 孔位 | 之后 |
|---|---|---|---|---|
| e37t3 001 | 0.50 mL | 8.005 → 19.506 mL | 1.A.1–1.B.12（24 孔） | 19.783 mL 起切废液 |
| e90t3 002 | 0.50 mL | 8.004 → 19.506 mL | 1.C.1–1.D.12 | 19.783 mL |
| e95t3 003 | 0.50 mL | 8.004 → 19.505 mL | 1.E.1–1.F.12 | 19.784 mL |
| e96t3 004 | 0.50 mL | 8.005 → 19.506 mL | 1.G.1–1.H.12 | 19.783 mL |
| mglv3t3 005 | 0.50 mL | 8.004 → 19.506 mL | 2.A.1–2.B.12 | 19.783 mL |

其他可读到的信息：

* 分级体积 / 收集器类型：`Result.xml` → `Frac volume (Elution)=0.50 ml`、`Frac tube type=96 deep well plate`、
  `Frac start position=Next tube`（方法文件 `MethodData` 里还有 `mIsFixedVolumeFractionation` 等）。
* 每个孔的**具体洗脱体积与时间**（`examples/example_e37t3_001_fractions.csv` 就是从文件导出的）。
* `NextFracData` 是收集盘布局的 **PNG 图**（96 深孔板 + 收集器前脸示意）。

所以工作台里可以把**收集区间直接画在图上**（底色 + 每 0.5 mL 的虚线分格 + 切废液虚线），
分析相关数据时也能自动把默认积分范围设成实际收集范围。

---

## 2. 快速开始

```bash
cd /data/codex/webui/sec/sec_studio
./run.sh                      # 默认扫描上一层目录(含 zip 的文件夹)，端口 8731，自动打开浏览器
# 或
python3 app.py --data-dir /data/codex/webui/sec --port 8731
# 或指定
./run.sh /path/to/zips 8080
```

打开 <http://127.0.0.1:8731/>。页面加载时会自动扫描数据文件夹并把所有 `*.zip` 解析进来；
也可以随时用 **导入数据** 按钮或**拖拽** ZIP、CSV、TSV 文件到左侧区域批量添加数据。

CSV/TSV 通用格式：第一行是列名，支持宽表（X 列 + 多条数值曲线）和带 `run` / `series` / `curve` 分组列及 `value` 列的长表。默认自动识别 `x`、`volume (mL)`、`elution volume`、`time (min)` 等常见 X 轴名称；无法识别时使用第一列。支持逗号、分号或制表符分隔、UTF-8 BOM，以及数值中的空单元格。文件中每条曲线按自身有效的 X/Y 行导入。导入后可在坐标轴设置中调整轴标题。已有 CSV 导出仍支持长表/宽表、选择曲线、处理参数和按 Run 打包。

依赖：`python3`、`numpy`、`matplotlib`、`flask`（`pip install matplotlib flask`）。

### 桌面版原型（开发中）

桌面壳位于 `desktop/`，用 Electron 打开独立窗口并启动本地 Python 引擎。开发运行步骤：

```bash
python3 -m pip install -r desktop/requirements-build.txt
cd desktop
npm ci
npm start
```

可用 `SEC_STUDIO_PYTHON` 指定 Python 可执行文件。Linux AppImage、Windows 安装包和 macOS DMG 分别使用 `npm run package:linux`、`npm run package:win`、`npm run package:mac` 构建，需在对应平台构建；构建前需安装 PyInstaller。Linux AppImage 已生成，Windows/macOS 安装、签名和公证验证仍待完成。

工具栏的“保存项目”会生成 `.secproj` 文件，包含全部导入曲线数据与当前图形/分析状态；“打开项目”恢复上次工作区。导出图形和数据仍使用现有导出选项。

### 一键启动网页工作台

也可以直接双击 `sec_studio` 目录里的启动器，在默认浏览器中打开本地工作台：

* Windows：`启动SEC Studio.bat`
* macOS：`启动SEC Studio.command`（首次使用如被系统拦截，可在文件上右键选择“打开”）
* Linux：`启动SEC Studio.sh`，或使用 `启动SEC Studio.desktop`

启动器会绑定 `127.0.0.1:8731`，并自动打开浏览器；关闭启动器终端即可停止服务。若 8731 端口已占用，可设置环境变量 `SEC_STUDIO_PORT` 后启动。此便携启动方式需要本机安装 Python 3 和运行依赖：`python -m pip install -r requirements.txt`。它不会修改系统服务或安装目录，适合先按“解压一个文件夹、双击启动”的形态试用。无 Python 依赖的正式安装包仍以各平台打包版为准。

---

## 2.5 在 Mac mini 上访问（集群 + SSH，做法与 webui 一致）

集群是无图形界面的，所以**不要**在集群上开浏览器；用你当时访问 webui 的同一套办法：
服务只监听 `127.0.0.1`，从 Mac 做 SSH 端口转发，然后在 Mac 浏览器里看。

**① 在集群上以后台服务方式启动**（关掉 SSH 窗口也不会停）：

```bash
cd /data/codex/webui/sec/sec_studio
./serve.sh start                 # 默认扫描上一层目录(含 zip)，端口 8731
./serve.sh status                # 查看状态 / 端口 / 是否在监听
./serve.sh log                   # 跟踪日志
./serve.sh stop                  # 停止
```

**② 在 Mac mini 上开一个隧道**（新开一个终端窗口，保持不关）：

```bash
ssh -N -L 8731:127.0.0.1:8731 zheng
```

（`zheng` 就是你平时 `ssh zheng` 的别名；等价于 `ssh -N -L 8731:127.0.0.1:8731 amax@192.168.33.198`。
仓库里也放了 `mac-tunnel.sh`，拷到 Mac 上 `chmod +x` 后 `./mac-tunnel.sh zheng 8731` 即可，会自动打开浏览器。）

**③ 在 Mac 浏览器打开** <http://127.0.0.1:8731/>

> 已经 ssh 进集群、不想再开一个连接？在当前 SSH 会话里 **按一下 Enter**，再输入 `~C`，
> 出现 `ssh>` 提示符后输入下面这行回车，即可给当前连接动态加转发：
> ```
> -L 8731:127.0.0.1:8731
> ```
> 然后在 Mac 上打开同样的 <http://127.0.0.1:8731/>。

**备选：局域网直连**（不用隧道，但对防火墙有要求）。让服务监听所有网卡：

```bash
HOST=0.0.0.0 ./serve.sh restart
# 或前台： ./run.sh "" 8731 --host 0.0.0.0
```

然后 Mac 直接打开 <http://192.168.33.198:8731/>。本机已验证 0.0.0.0 模式下该地址返回 200；
但集群开着 `firewalld`，**若从 Mac 打不开需要放行端口**（需管理员权限；用已开放的 22 端口的隧道则不受影响）：

```bash
sudo firewall-cmd --add-port=8731/tcp --permanent && sudo firewall-cmd --reload
```

> 推荐还是用 SSH 隧道：只借用已经开放的 22 端口，不额外暴露服务，也和你当时访问 webui 的方式一致。

---

## 3. 功能一览

**导入 / 管理**
* 一键“加载文件夹” + 多文件拖拽/选择导入；自动解析每个 run 的元数据（Run 名、柱型、流速、时间、柱体积）。
* 左侧 Run 列表：显示/隐藏、重命名、单独改色、删除；顶部“显示通道”开关（A280 / A230 / A455 可任意组合叠加）。

**可视化编辑器（右侧五个标签）**
* **图形**：期刊预设（Science/Nature/Cell/单栏/双栏/正方形）、宽×高(mm)、导出 DPI、字体（含中文字体）、
  基准字号、背景色、透明背景、主标题/副标题/面板字母(A)、标题字号与加粗、四周边距。
* **坐标轴**：X 轴类型（洗脱体积 mL / 时间 min / 柱体积 CV）、X/Y 范围、标签、主/次刻度间隔、
  刻度方向(内/外/双向)、刻度长宽、刻度字号、边框粗细、上/右边框显隐、网格、X/Y 对数、翻转 X 轴；
  另有**右侧副坐标轴**（电导等不同量级信号）。
* **曲线**：全局线宽/线型/不透明度/平滑窗口/基线处理/归一化；**一键配色**（journal / Okabe-Ito / viridis / grays / warm）；
  单条曲线的颜色/图例名/左右轴/线宽/基线/归一化/平滑可单独覆盖。
* **图例**：显示开关、位置(9 种)、字号、列数、标题、边框。
* **数据**：每条曲线的逐项设置表（颜色、图例名、左右轴、高级参数）。

**一键应用 / 批量**
* 所有样式都是**全局**的——改一次即作用于所有导入的 run（这就是“一键应用”）。
* “🎨 一键配色”按导入顺序给所有 run 重新上色。
* 导出对话框里都有 **“按 Run 批量 (ZIP)”**：一次把所有 run 各自导成一张图 / 一个 CSV，打包下载。

**导出**
* 图片：`PDF / SVG`（矢量，投稿首选）、`PNG / TIFF / JPG`（可选 72–1200 DPI、透明背景）。
  PDF/SVG 中字体按 TrueType 嵌入、文字保持可编辑。
* CSV：选择 **X 轴类型 + X 起止范围 + 指定曲线**；两种布局
  * 长表：`run, series, curve, volume, value, unit`
  * 宽表：共享 x 网格、每条曲线一列（便于直接粘贴进 GraphPad/Prism/Excel）
  可选“是否应用基线/平滑/归一化”。

---

## 3.5 分析功能（新增）

右侧面板新增 **「分析」** 标签，五大块：

**① 收集范围（来自文件）**
勾选即把收集窗口画到图上（底色 + 每 0.5 mL 虚线分格 + 切废液虚线 + 底部“fractions 8.0–19.5 mL (24×0.5)”标注）；
可选择用哪个 Run 的收集信息，并显示孔位范围。

**② 峰检测 / 面积积分**
对选中的曲线自动找峰（Prominence / 最小峰距 / 平滑窗口 / 检测范围可调），
输出峰表：**顶点体积、峰高、面积、%面积、FWHM、积分区间**，
默认算法是“谷–谷 + 线性基线”，面积单位 mAU·mL。
勾选“显示峰区间”会在图上加淡色色块与 P1/P2… 标注，可一键 **导出峰表 CSV**。

**③ 求导**
一键给所有曲线套一阶 `dy/dx` 或二阶 `d²y/dx²`（Savitzky-Golay，平滑窗口可调），
适合找肩峰/拐点；单条曲线也可在「数据」标签的高级设置里单独设导数阶数。

**④ 蛋白序列分析**
粘贴序列 → 返回 **平均/单同位素分子量、等电点 pI、pH7 电荷、ε280、A280(0.1%)、
W/Y/C 计数、GRAVY、芳香性**；填入 A280 读数还能直接换算 **mg/mL 与 µM 浓度**。
ε280 用 Pace 1995 公式（5500·W + 1490·Y + 125·cystine）。

**⑤ SEC 分子量校准 + 辅因子化学计量**
* 输入标准品（洗脱体积, 分子量）与 V0/Vt → 线性拟合 `log10(MW)=a·Kav+b`，
  给出 R²，并**自动用检测到的峰顶点**反算每个峰的分子量（Kav = (Ve−V0)/(Vt−V0)）。
* 辅因子（如 FMN）：填 ε蛋白@280、ε辅因子@λ、ε辅因子@280，
  把 A280 与 A455 的峰按保留体积配对，算出每个峰的 **辅因子:蛋白 摩尔比**
  （先把 A280 面积扣除辅因子在 280 nm 的吸收，再 n=面积/ε）。
  `examples/example_e37t3_001_FMN_peaks.png` / `_peaks.csv` 就是这套流程的产物。

所有分析都作用在**当前显示的处理后曲线**（基线/平滑/归一化/导数设置一致），
因此 A280 与 A455 的结果彼此可比。

---

## 3.6 设计筛选（FMN 相对装载，单体峰面积法）

右侧新增 **「筛选」** 标签：用固定的「单体峰面积」规则一键给所有导入的设计排名并出图，
方法与本仓库 `fmn_binding_report.py` / `analysis.screen_run` 完全一致（单针可复现）：

* **恒定基线**：每条通道取 4.5–8.5 mL 平台中位数（可调窗口）。
* **单体峰窗口**：`[两峰之间谷(13.0–14.3 mL) … 回落到基线谷(16.0–18.6 mL)]`，
  A280 与 A455 用**同一个窗口**积分，面积 = `∫max(y−基线,0)dV`（mAU·mL）。
* 输出：**r (mol/mol)**、**ρ = A455/A280（免假设）**、峰高比、A280/A455 面积、apex、~MW、积分窗口；
  自动按 r 降序排名（1/2/3 名彩色高亮）。
* 参数（基线窗口、谷搜索区间、ε 蛋白/ε 辅因子）都可调，换柱/换波长时直接改；
  ε 只影响绝对 r 值、不影响排序。
* 动作：「计算排名」「导出 CSV」（全指标表）「导出排名柱状图」（PDF/SVG/PNG/TIFF，期刊样式），
  勾选「在图上画窗口」把积分区间叠加到主预览上。

> 换柱子/换蛋白时务必先看 `fmn_binding_check` 式的曲线核对窗口是否落在目标单体峰上；
> 详情与假设（ε280 未知、单体峰判定、单针无误差棒）见 `memory/sec_akta_analysis_studio.md` 第 9 节。

---

## 4. ÄKTA/UNICORN 结果包格式（解析原理）

外层 `*.zip` 里：

* `Chrom.1.Xml` — 描述每条曲线：`Name`、`AmplitudeUnit`、`DistanceBetweenPoints`(min)、
  `ColumnVolume`(mL)、以及对应的二进制点文件 `BinaryCurvePointsFileName`。
* `Chrom.1_<k>_True` — **本身又是一个 zip**（但没有中央目录，标准 `zipfile` 打不开），内含
  `CoordinateData.Amplitudes`(y) 与 `CoordinateData.Volumes`(x，单位 mL)。
* `Result.xml` — Run 名称 / 柱型 / 流速 / 采集时间等元数据。

`CoordinateData.*` 的二进制布局（小端 float32）：

```
偏移 0..21   : 22 字节固定头
偏移 22..25  : uint32  采样点数 count
偏移 26      : 0x0B 分隔符
偏移 27..    : count × float32 (little-endian)
末尾 1 字节  : 0x0B 结束符
```

`akta.py` 实现了无中央目录 zip 的手动解包 + 上述定长头解析，所以 5 个包（以及同类导出）都能稳定读取。

---

## 5. 目录结构

```
sec_studio/
├── app.py            # Flask 后端 + CLI（--data-dir / --port / --no-browser）
├── akta.py           # ÄKTA/UNICORN ZIP 与通用 CSV/TSV 解析器
├── project_format.py # 版本化 .secproj 项目存取
├── analysis.py       # 求导 / 峰检测积分 / 序列分析 / SEC 分子量 / 辅因子比例
├── render.py         # matplotlib 出版级渲染 + CSV 导出
├── make_examples.py  # 用真实数据生成示例图/CSV
├── fmn_binding_report.py  # FMN 相对装载排序 CLI（核心逻辑在 analysis.screen_run）
├── run.sh            # 前台启动
├── serve.sh          # 后台服务：start/stop/restart/status/log
├── mac-tunnel.sh     # 放到 Mac 上运行，一键开 SSH 隧道并打开浏览器
├── templates/index.html
├── static/style.css  static/app.js
├── desktop/          # Electron 外壳、PyInstaller 引擎和跨平台构建配置
└── examples/         # 生成的示例输出
```

## 6. 小贴士

* 投稿常用：`Science 单栏 85mm`，字体 `Arial (Liberation Sans)`，基准字号 8 pt，刻度向外，
  去掉上/右边框，导出 **PDF**；需要位图时选 **TIFF 600 dpi**。
* 想比较不同 run 的峰形，建议把基线设为“扣起始段均值”，X 轴用“洗脱体积 (mL)”。
* 中文标题/图注：字体选 `Noto Sans SC (中文)` 或 `Noto Serif SC (中文)`。
* 后端是有内存态的开发服务器（数据仅存内存，重启后重新扫描即可），适合本地科研使用；
  不要把端口暴露到公网。
