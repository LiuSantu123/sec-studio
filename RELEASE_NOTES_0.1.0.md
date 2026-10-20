# SEC Studio 0.1.0

首个桌面原型版本。

## 包含内容

- Electron 桌面窗口与内置 Python 分析引擎
- ÄKTA/UNICORN ZIP、CSV、TSV 导入
- SEC 曲线编辑、分析、图形和 CSV 导出
- `.secproj` 项目保存与恢复
- Linux x86_64 AppImage 一键运行包
- Windows/macOS 安装包构建配置

## Linux 使用

下载 `SEC-Studio-0.1.0-linux-x86_64.AppImage`，执行：

```bash
chmod +x SEC-Studio-0.1.0-linux-x86_64.AppImage
./SEC-Studio-0.1.0-linux-x86_64.AppImage
```

## 源码启动

请参阅 `sec_studio/README.md`。网页便携启动器位于 `sec_studio/` 目录。

Windows NSIS 和 macOS DMG 需要在对应平台执行 `npm run package:win` / `npm run package:mac` 后发布。
