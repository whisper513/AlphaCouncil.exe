# AlphaCouncil AI · 实时/离线证券分析仪表板

简述（中文）：
- 一个可本地运行的证券分析仪表板，支持实时行情、离线历史分析、基本面与新闻聚合，以及通过本地代理调用大模型生成参考结论。
- 适配中国 A 股代码自动后缀映射（如 000592→000592.SZ），在外部配额受限时自动回退本地数据；支持 CSV 导入与条件评估接口。
- 可一键打包为 Windows 可执行程序，并提供数据网关与计划任务脚本，便于长期增量更新。

Overview (English):
- A local-first stock analysis dashboard with realtime quotes, offline historical analytics, fundamentals/news aggregation, and LLM-assisted summaries via a local proxy.
- Auto mapping for China A-shares (e.g., 000592→000592.SZ), graceful fallback to local data when remote quota is limited; CSV import and condition-evaluation API are supported.
- One-click Windows packaging into an executable, plus a data gateway and scheduled job scripts for daily incremental updates.

## 项目进度（中文）
- 已完成：
  - 实时仪表板与数据网关（HTTP/WS）
  - A 股代码自动映射与统一分析接口（含条件评估）
  - 离线 CSV 导入、本地 SQLite 历史读取、离线分析按钮
  - LLM 代理与设置页（支持 DeepSeek/OpenAI）
  - 一键打包与发布脚本、公开包生成（剔除敏感文件）
- 进行中/计划：
  - 数据源适配更多免费/开源渠道
  - 策略模块化与单元测试

## 阻碍与暂停说明（中文）
- 外部行情与基本面接口存在配额/付费限制，免费额度不足时会影响实时与历史拉取。
- 数据合规与授权边界尚未完全明确，限制进一步开放更多源的自动接入。
- 作者目前精力与预算有限，短期难以持续投入；项目转入维护模式，欢迎社区贡献。
- 建议离线方案：CSV 导入 + `/data/analyze?source=local`。

## Status & Roadblocks (English)
- Completed:
  - Realtime dashboard & data gateway (HTTP/WS)
  - A-share auto mapping & unified analyze API (with condition checks)
  - Offline CSV import, local SQLite history, offline analyze UI
  - LLM proxy & settings page (DeepSeek/OpenAI)
  - Packaging & release scripts, public zip without secrets
- Roadblocks:
  - Remote APIs have quota/cost limits; free tiers are insufficient.
  - Licensing/compliance constraints limit broader integrations.
  - Limited time/budget; project in maintenance mode. Community PRs are welcome.
  - Recommended: offline CSV + `/data/analyze?source=local`.

# AlphaCouncil 打包工程（Windows）

本目录包含将现有网页仪表板和本地 LLM 代理打包为可执行软件（`.exe`）所需的工程与脚本。结构划分为“底层（服务/算法）”与“应用层（界面/启动）”，便于后续增删改查。

## 目录结构
- `app/launcher.py`：应用层启动器。负责启动静态网页服务与 LLM 代理，并打开内嵌网页窗口（或默认浏览器）。
- `app/ui/alpha-dashboard.html`：仪表板页面（已复制当前版本）。
- `build/requirements.txt`：打包所需依赖列表（`pywebview`、`pyinstaller`）。
- `scripts/build_exe.ps1`：一键打包脚本，生成 `AlphaCouncil.exe`。
- `scripts/run_dev.ps1`：开发模式运行脚本（不打包，直接用 Python 运行）。
 - `build/VERSION`：应用版本号（如 `0.1.0`），打包时内嵌并在窗口标题展示。
 - `build/version_info.txt`：Windows 版本资源（文件/产品版本、描述等）。
 - `build/icon.ico`：可选的程序图标（如提供，将在打包时嵌入）。

## 快速使用
1. 安装依赖并打包（需联网）：
   - 右键以管理员方式运行 `scripts/build_exe.ps1`；或在 PowerShell 中执行：
   - `powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1`
2. 打包完成后，在 `dist/` 目录下得到 `AlphaCouncil.exe`。双击运行后会弹出内嵌窗口并自动启动两个本地服务：
   - 静态网页服务（默认 `http://127.0.0.1:5173/`）
- LLM 代理服务（默认 `http://127.0.0.1:8787/llm`）

### 统一配置与默认联网模式（前后端一体化）
- 统一配置文件：`ABC/config/app.json`
- 支持字段（后端 `/config` 读写）：
  - `dashboardDefaultSymbol`：仪表板默认股票代码
  - `dashboardSource`：默认数据源（`http` | `local`）
  - `dashboardUrl`：默认行情接口URL（在 `http` 模式下使用）
  - `dashboardInterval`：默认轮询间隔毫秒数
  - `dashboardSimple`：是否启用简洁模式（隐藏工作流区域）
- 前端仪表板会在启动时从 `http://localhost:8788/config` 拉取并应用上述配置，并写回到浏览器本地缓存。
- 兜底：若仍出现指向旧演示地址（`localhost:8080/quote.json`）的情况，前端会自动切换到 `http://localhost:8788/data/quote?symbol=<symbol>`。

### WebSocket 推送（低时延）
- WS端点：`ws://localhost:8789/ws/quote?symbol=<symbol>`（默认与 HTTP 网关同机，端口=HTTP+1）
- 前端切换到“WebSocket推送”后自动使用上述端点。
- 稳定性策略：WS连续失败自动回退到 HTTP 轮询，并在 2 秒后重试或继续轮询。

### 隐藏控制台窗口（正常应用启动体验）
- 打包脚本已加入 `--noconsole` 参数，生成的 `AlphaCouncil.exe` 在打开时不显示终端窗口。
- 内部静态站与 LLM 代理以后台线程启动，无需额外窗口。

## 在后端服务器使用 API Key（环境变量）
- 为了避免在前端填写敏感信息，后端代理支持从环境变量读取各服务的 API Key，优先级为：请求内显式 `api_key` > 基于 `name` 或域名的专用环境变量 > 通用环境变量。
- 支持的环境变量：
  - `OPENAI_API_KEY`：用于 `name=openai` 或域名包含 `openai` 的端点。
  - `DEEPSEEK_API_KEY`：用于 `name=deepseek` 或域名包含 `deepseek` 的端点。
  - `LLM_API_KEY` / `API_KEY`：通用兜底。

### 在 Windows（PowerShell）中设置环境变量
- 临时设置（当前会话）：
  - `$Env:DEEPSEEK_API_KEY = "sk-xxxx"`
- 永久设置（写入用户环境）：
  - `setx DEEPSEEK_API_KEY "sk-xxxx"`
  - 设置后需重新启动应用或终端，使新环境变量生效。

### 使用说明
- 前端如果不填写 `API Key`，后端会尝试读取对应环境变量；如同时填写，优先使用前端提供的显式值。
- 多模型聚合（providers）场景：建议在 `name` 字段填 `openai`、`deepseek` 等，以便后端正确匹配环境变量。

## 依赖说明
- Windows 需安装或可使用系统 Edge/Chromium WebView（大多数 Win10+ 已内置）。若内嵌窗口无法启动，程序会自动回退到系统默认浏览器。

## 开发模式
- 执行 `scripts/run_dev.ps1` 可在不打包情况下启动，便于调试。
  - 若浏览器缓存导致页面未更新，可执行强制刷新（Ctrl+F5）或清除本地缓存；前端已包含兜底逻辑自动修正旧演示地址。

## 工程管理与快速构建
- 一键清理+打包+部署到 ABC：
  - `powershell -ExecutionPolicy Bypass -File ABC/scripts/update_exe.ps1`
- 仅打包（并复制到 ABC）：
  - `powershell -ExecutionPolicy Bypass -File ABC/scripts/build_exe.ps1 -DeployToABC`
  - 清理构建产物：
  - `powershell -ExecutionPolicy Bypass -File ABC/scripts/clean_build.ps1`
- 开发模式（同时启动静态与代理服务）：
  - `powershell -ExecutionPolicy Bypass -File ABC/scripts/run_dev.ps1`
  - 参数示例：`-ServeStatic:$true -RunLLMProxy:$true -RunLauncher:$false`
  - 启动数据网关：`-RunDataGateway:$true -DataPort 8788`

## 数据源网关（Data Gateway）
- 服务脚本：`ABC/services/data-gateway.py`
- 默认端口：`8788`（可在 `run_dev.ps1` 通过 `-DataPort` 指定）
- 必备环境变量：
  - `ALPHAVANTAGE_API_KEY`：Alpha Vantage 的 API Key（免费额度有限，注意速率限制）。
- 主要接口（GET）：
  - `http://localhost:8788/data/quote?symbol=IBM`：实时行情（Global Quote），返回价格、涨跌幅等。
  - `http://localhost:8788/data/history?symbol=IBM&save=true`：历史日线（Adjusted Close），可选保存到 SQLite。
  - `http://localhost:8788/data/fundamentals?symbol=IBM`：基本面概览（PE、EPS、ROE等）。
  - `http://localhost:8788/data/news?symbol=IBM`：新闻/情绪（若API可用）。
- 无法使用券商API时的本地数据方案：
  - `http://localhost:8788/data/history_local?symbol=IBM&limit=500`：从本地 SQLite 读取最近 N 条历史数据。
  - `http://localhost:8788/data/import_csv?symbol=IBM&file=ABC/data/import/IBM.csv`：将 CSV 导入 SQLite（默认文件路径为 `ABC/data/import/<symbol>.csv`）。
  - CSV格式要求：表头包含 `date,open,high,low,close,volume`，`date` 推荐 `YYYY-MM-DD`。
- 本地数据库：`ABC/data/stocks.db`（SQLite）
  - 表：`daily_price(code, date, open, high, low, close, volume)` 主键 `(code, date)`。
  - 保存示例：访问 `/data/history?symbol=IBM&save=true` 后自动入库。

### 环境变量设置示例（PowerShell）
- 临时设置：`$Env:ALPHAVANTAGE_API_KEY = "your_key"`
- 永久设置：`setx ALPHAVANTAGE_API_KEY "your_key"`

### 常见问题与建议
- 打包失败或行为异常，先执行清理脚本再打包。
- 若需要指定 Python 解释器，以上脚本均支持 `-PythonExe` 参数，例如：`-PythonExe "C:\Python312\python.exe"`。
- 更新后 exe 位于 `ABC/AlphaCouncil.exe`，同时保留带时间戳的备份 `ABC/AlphaCouncil-YYYYMMDD-HHMMSS.bak`。
 - 如需自定义图标，请将 `icon.ico` 放到 `ABC/build/`；如需更新版本，编辑 `ABC/build/VERSION`（格式：`主.次.修订`）。

## 后续扩展建议
- 将数据源适配器与策略模块抽象为 Python 包（`core/`），在 `launcher.py` 中引入，以实现更灵活的业务扩展与单元测试。
 - 若需要完整离线运行，可将页面资源与模型配置打包进 exe（已通过 `--add-data` 处理）。

## 开发者与署名
- 主要开发者：Songzhang
- Windows 版本资源的 `CompanyName` 与版权信息已设置为 `Songzhang`；可在 `ABC/build/version_info.txt` 中调整后重新打包。
- 若需在页面中展示署名，`alpha-dashboard.html` 页脚已显示“开发者：Songzhang”。

## 每日增量更新（计划任务）

当无法使用国内券商API时，推荐通过 Alpha Vantage 每日拉取增量数据，写入本地SQLite以供离线查询与分析。

- 脚本位置：`ABC/services/daily_update.py`
- 股票清单：`ABC/data/symbols.txt`（每行一个代码，示例已提供）
- 一键执行：`ABC/scripts/run_daily_update.ps1`
- 计划任务注册：`ABC/scripts/register_daily_update.ps1`

前置条件：
- 已设置环境变量：`ALPHAVANTAGE_API_KEY`（参见上文网关配置）
- 已安装依赖：`pip install -r ABC/build/requirements.txt`

快速使用：
- 手动执行一次：
  - `powershell -ExecutionPolicy Bypass -File ABC\scripts\run_daily_update.ps1`
  - 可选参数：`-SymbolsFile` 指定清单文件，`-ExtraSymbols` 添加临时代码（逗号分隔），`-SleepSeconds` 设置节流秒数（免费额度建议≥12）
- 注册每日计划任务（默认每日09:00执行）：
  - `powershell -ExecutionPolicy Bypass -File ABC\scripts\register_daily_update.ps1`
  - 可在任务计划程序中调整时间、触发器与条件

说明：
- 增量脚本直接调用 Alpha Vantage 接口并写入 `ABC/data/stocks.db`，无需数据网关常驻。
- 为避免免费额度限流，脚本默认每次请求间休眠15秒；可根据账户级别调整。
- 若需要离线补数据，可结合 `/data/import_csv` 端点导入历史CSV，再用每日增量保持更新。
