# Account usage 1.0 — Fork 手动探针修订

唯一现行 Claude 规范见[手动探针说明](../../../docs/fork/claude-usage-probe.md)。此前自动探针和只读本地缓存的临时方案均被替代。Codex 原有采集逻辑不变。

- `GET /api/v2/account-usage`：只读缓存，绝不触发 Claude 探针。
- `POST /api/v2/account-usage/refresh`：用户手动刷新。Server 全局持久化单飞；重复调用等待同一结果，成功后 300 秒内直接返回缓存。
- `accountUsage.event({runtimeId,accountKey,eventId,windows})`：Connector 原生事件推送，Server 验证设备归属并在接收时盖时间戳。
- `accountUsage.probe({runtimeId})`：仅 Server 向指定 ARM Connector 下发。返回 `ClaudeProbeResult`，不包含 OAuth 或本机观察时钟。其他节点禁用，不作故障转移。

新增字段均保持旧字段兼容：UsageWindow 的 source、receivedAt、ageSeconds；UsageResponse 的 refresh 包含 status、nextAllowedAt、completedAt、errorCode。状态为 idle / running / success / retry / offline / circuit / disabled。source 表示事件/探针原始来源，不因从缓存读取而变更。

每个窗口在 Server 独立保留 event / probe 两路最新有效记录；按 Server receivedAt 选择较新者。未更新窗口不清空，缓存没有年龄 TTL 或重置时清空规则。旧缓存无可信接收时间时保留值并返回未知来源/年龄。失败只修改独立刷新控制状态，不能改窗口记录。

429 优先 Retry-After；无有效提示时连续限流按 10→20→30 分钟退避（30 分钟封顶）。成功清零 429 计数并恢复 5 分钟；第三次 429 熔断到次日 00:00 UTC，届时只解除控制，不自动请求。超时和离线不增加 429 次数，也不将失败正文写入缓存。熔断和退避期间按钮置灰。

模型源为 `server/agent_server/core/account_usage.py`，schemas 由 model_json_schema(by_alias=True) 生成。原始响应、OAuth 令牌、未掩码邮箱和上游错误文本不允许进入 wire、缓存或日志。账号仍使用稳定 SHA256 键。Server 不执行外部探针，只负责指令、缓存和分发。

## 可靠性修订（2.7.0）

- `UsageWindow.resetsAt` 可为 null，表示未激活窗口；null 必须清除旧重置时间。用量仍正常计算。上游缺失 resets_at 时按 null 接收，同时产生 `MissingField` 告警。
- `ClaudeProbeResult`、`UsageSnapshot`、`ProbeRefresh` 增加 `parseWarnings`，每项只有 `field`（根路径或窗口字段路径）与 `reason`（异常类型）；无响应原文。部分窗口无效只舍弃该窗口，正常窗口继续更新；失败窗口及其 receivedAt 保持不变。告警独立于窗口数据保存。
- 新错误码 `parse_error`（非法 JSON、结构错误或没有有效窗口）、`auth_expired`（无法完成凭据刷新）。探针 detail 仅允许 `<字段>: <异常类型>`，或固定的 `write_failed_after_refresh`；不得包含异常原文。全部窗口失败时 detail 列出所有失败字段。
- 只有连续 rate_limited 翻倍退避（600、1200、1800 秒封顶）；其他错误回到 300 秒并清零连续限流计数。有效 Retry-After 始终优先，即使超过 1800 秒。保留第三次连续 429 的日熔断。
- 每个窗口独立显示 receivedAt，不能以其他窗口的最新时间表示失败窗口刚更新。
