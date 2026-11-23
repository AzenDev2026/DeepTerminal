# DeepTerminal — 版本历史与更新记录

这里记录 DeepTerminal 的每一个版本和改动。主页 / main README:
[../README.md](../README.md)

## 目录

- [2.7.x](#27x)
  - [2.7.4](#274--2026-11-23)
  - [2.7.2](#272--2026-11-23)
  - [2.7.0](#270--2026-11-23)
- [2.6.x](#26x)
  - [2.6.7](#267--2026-11-22)
  - [2.6.6](#266--2026-11-22)
  - [2.6.5](#265--2026-11-21)
  - [2.6.1](#261--2026-11-21)
  - [2.6.0](#260--2026-11-20)
- [2.5.x](#25x)
  - [2.5.1](#251)
- [2.1](#21)
- [Beta 2 和 Beta 1](#beta-2--beta-1)
- [截图](#截图)

## 2.7.x

### 2.7.4 — 2026-11-23

- **DTinfo 改为 chafa 风格终端内嵌字符画**：图标 `deepterm.png` 用半块字符
  （`▀`，上半像素做前景色、下半像素做背景色、真彩色）直接"画"进终端，
  对比度按图标自身亮度增强，深色/浅色主题都清晰；信息列在右侧
  （fastfetch / sysfetch 布局），并新增 Kernel 行。不再使用悬浮图片横幅。
- 新增 `art.py` 与对应的渲染测试。

### 2.7.2 — 2026-11-23

- 修复 **powerline 提示符变白、没有颜色**：如果启动环境里带有 `NO_COLOR`
  （部分启动器和 CI 类环境会设置），PowerShell 7.2+ 会把
  `$PSStyle.OutputRendering` 切成 `PlainText`，静默剥离提示符里所有 ANSI
  序列。现在启动 shell 时会清除 `NO_COLOR` / `CLICOLOR`，真彩色提示符恢复
  正常。

### 2.7.0 — 2026-11-23

- 新增 **split view**：`Ctrl+Shift+E` 左右分屏，`Ctrl+Shift+O` 上下分屏
  （Konsole 风格）。每个分屏有自己的一套标签页；关掉某个分屏最后一个标签页
  时该分屏自动收起。
- **DTinfo 不再是字符画信息框**：shell 侧只打印隐藏的 OSC 标记，
  DeepTerminal 客户端渲染图标和版本信息。

## 2.6.x

### 2.6.7 — 2026-11-22

- `codeout` 视觉打磨：标签只用四种颜色——错误是鲜红、成功是亮绿、加载是橙色、
  其余是亮白；混入更长的内核日志风格行（路径、时间戳、十六进制地址），
  看起来更像真实启动日志。

### 2.6.6 — 2026-11-22

- 新增 **沉浸模式**：按 `F11` 进入无边框全屏，隐藏标签栏和状态栏；
  鼠标移到屏幕最上方边缘会滑出标签栏，再按 `F11` 退出。`Shift+F11` 保留
  旧的普通全屏。
- 外观设置新增 **Pure Black** 主题：同样的深色调色板，但背景是纯 `#000000`。

### 2.6.5 — 2026-11-21

- 新增 **`codeout`** 彩蛋命令：在 Bash 或 PowerShell 标签页里输入 `codeout`，
  屏幕会刷出一片假的"系统启动"日志（`[successful]eating a pizza`、
  `[error]dont want to go to school`、`[loading]system DeepTerminal` ……）。
- 可以调参：`codeout 3s`、`codeout fast`、`codeout super`、`codeout 3s super`。
  每 60 行清理最旧的 30 行，刷屏不会堆积。默认值在
  `~/.config/AzenDev/DeepTerminal/codeout-conf.txt`：

  ```
  #code output config
  #just for fun
  [time]:3s
  [speed]:super
  ```

- `codeout stop` 停止刷屏，`codeout conf` 打印配置路径。

### 2.6.1 — 2026-11-21

- 修复首次打开时横幅乱码（盒子现在逐行对齐，不会向右漂移）。
- 每次打开 Bash / PowerShell 标签页自动执行 `clear`（可在设置里关闭）。
- 窗口变大时提示符不再下沉。

### 2.6.0 — 2026-11-20

- 调整窗口大小时不再清屏（只重排）。
- 新增 **自动字号**：字号随窗口面积缩放（6–32 pt，设置 → 外观里开关）。
- 每个新标签页顶部显示 **About DeepTerminal** 横幅。
- 恢复终端内 about 命令：在 Bash 或 PowerShell 标签页输入 **`DTinfo`**。

## 2.5.x

### 2.5.1

- 调整窗口大小时屏幕和滚动历史会重排，换行文本按新宽度重新折行而不是被裁掉。

## 2.1

- 现代化标签栏（强调色下划线、悬停关闭按钮、中键关闭）。
- **可定制提示符**：预设（Arrow、Angled、Minimal、Powerline、Whale……）、
  自定义符号和颜色、设置里的实时预览。提示符以真彩色 SGR 注入 Bash（`PS1`）
  和 PowerShell（`prompt` 函数），注入的中设置行本身不会显示在屏幕上。

## Beta 2 和 Beta 1

Beta 2 重写了终端核心：Beta 1 用 `QProcess` 管道跑 `pwsh`；Beta 2 在真实的
PTY 上跑 shell，并用 [pyte](https://github.com/selectel/pyte) 渲染屏幕，
所以全屏程序、作业控制、颜色和窗口缩放都像普通终端一样工作。

## 截图

| 深色主题 / DTinfo 字符画 | 分屏 | 浅色主题 |
|---|---|---|
| ![dark](pic/screenshot.png) | ![split](pic/screenshot-split.png) | ![light](pic/screenshot-light.png) |

图片都在 [`pic/`](pic/) 目录里；重新生成主页截图：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/make_screenshot.py
```
