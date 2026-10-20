# SEC Studio —— 指向工作区记忆

本项目的完整记忆（数据格式、5 个包解析结果、收集范围、分析算法、启动与 Mac 隧道、已知坑）在：

    /data/codex/memory/sec_akta_analysis_studio.md

快速启动：`./serve.sh start` → 集群 `http://127.0.0.1:8731/`，Mac 上
`ssh -N -L 8731:127.0.0.1:8731 zheng` 后开 `http://127.0.0.1:8731/`。

## 最新分析产物（2026-10-12/13）

主记忆已更新到 2026-10-13，见上文完整文件；这里只给快速索引：

- 方法文档：`data/fmn_ranking/TABLE_PLOTTING_AND_RANKING_METHOD.md`
- 三张 A280/A455 排名表脚本：`plot_fmn_ranking_tables.py`
- A230/A455 表脚本：`plot_a230_a455_tables.py`
- 分模型统计表脚本：`plot_model_stats_table.py`
- 产物目录：`data/fmn_ranking/`（图 + CSV 全在此）
- 统计：`model_stats_molar_r_a230.csv` / `model_stats_molar_r_a230_table.*`
- 拼写：筛选来源统一为 **AffinCraft**。

## 桌面发布状态（2026-10-20）

- 已完成 Electron + PyInstaller 桌面壳：`desktop/main.cjs` 启动内置 Python 引擎，关闭窗口时清理子进程。
- 已支持 CSV/TSV 宽表与长表导入、`.secproj` 保存/恢复、原生下载保存对话框。
- Linux x86_64 一键运行包已生成并验证：`desktop/release/SEC Studio-0.1.0.AppImage`（约 209 MB）。使用前执行 `chmod +x`，双击或运行即可。
- 已增加便携网页启动器：`启动SEC Studio.sh`、`启动SEC Studio.command`、`启动SEC Studio.bat`、`启动SEC Studio.desktop`；需要本机 Python 3 和 `requirements.txt` 依赖。
- Windows NSIS 和 macOS DMG 的构建配置已写入 `desktop/package.json`，但必须在对应平台构建和验证；当前 Linux 环境不能产出可验证的原生 Windows/macOS 安装包。
- 当前工作区最初不是 Git 仓库，GitHub 发布前需初始化仓库并配置远程地址/认证。
