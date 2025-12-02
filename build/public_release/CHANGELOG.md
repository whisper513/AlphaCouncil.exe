# AlphaCouncil 更新日志

版本 0.1.1（2025-12-01）

- 统一配置：新增 `ABC/config/app.json`；数据网关新增 `GET/POST /config`，`alphaKey` 优先读取配置；`daily_update.py` 优先读取配置。
- 设置页：保存时同步到后端配置；加载时读取后端遮罩显示；默认 DeepSeek 接口与模型；密钥改为密码框，遮罩展示。
- 登录绑定：新增 `app/ui/login.html`，固定账号登录后自动写入 AlphaVantage 与 DeepSeek Key；导航新增“登录”。
- 仪表板：移除已删 LLM 输入框引用；LLM 调用与通用数据请求失败分类提示（网络 / 配额 / 密钥）。
- 数据网关：AlphaVantage 接口识别配额受限（返回 `Note`/`Information`），并按原因设置 HTTP 状态码（429/502/504）。
- 每日增量：配额与网络异常明确日志输出，易于诊断。

构建
- 提升版本到 `0.1.1`；`build/version_info.txt` 同步更新。
- 打包脚本：`scripts/build_exe.ps1`、`scripts/update_exe.ps1` 支持一键清理并部署到 `ABC/AlphaCouncil.exe`。

使用提示
- 设置页保存后同时写入浏览器本地与后端配置，后端仅在本机使用，不上传互联网。
- 错误提示：网络问题（502/504）、API 次数用完（429）、密钥无效（401/403）会在前端明确显示。