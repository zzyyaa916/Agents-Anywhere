# Account usage 1.0 — Fork 手动探针修订

唯一现行 Claude 规范见[手动探针说明](../../../docs/fork/claude-usage-probe.md)。此前自动探针和只读本地缓存的临时方案均被替代。Codex 原有采集逻辑不变。

- `GET /api/v2/account-usage`：只读缓存，绝不触发 Claude 探针。
- `POST /api/v2/account-usage/refresh`：用户手动刷新。Server 全局持久化单飞；重复调用等待同一结果，成功后 300 秒内直接返回缓存。
- `accountUsage.event({runtimeId,accountKey,eventId,windows})`：Connector 原生事件推送，Server 验证设备归属并在接收时盖时间戳。
- `accountUsage.probe({runtimeId})`：仅 Server 向指定 ARM Connector 下发。返回 `ClaudeProbeResult`，不包含 OAuth 或本机观察时钟。其他节点禁用，不作故障转移。

新增字段均保持旧字段兼容：UsageWindow 的 source、receivedAt、ageSeconds；UsageResponse 的 refresh 包含 status、nextAllowedAt、completedAt、errorCode。状态为 idle / running / success / retry / offline / circuit / disabled。source 表示事件/探针原始来源，不因从缓存读取而变更。

每个窗口在 Server 独立保留 event / probe 两路最新有效记录；按 Server receivedAt 选择较新者。未更新窗口不清空，缓存没有年龄 TTL 或重置时清空规则。旧缓存无可信接收时间时保留值并返回未知来源/年龄。失败只修改独立刷新控制状态，不能改窗口记录。

429 优先 Retry-After；无有效提示时 5→10→20 分钟退避。成功清零 429 计数并恢复 5 分钟；第三次 429 熔断到次日 00:00 UTC，届时只解除控制，不自动请求。超时和离线不增加 429 次数，也不将失败正文写入缓存。熔断和退避期间按钮置灰。

模型源为 `server/agent_server/core/account_usage.py`，schemas 由 model_json_schema(by_alias=True) 生成。原始响应、OAuth 令牌、未掩码邮箱和上游错误文本不允许进入 wire、缓存或日志。账号仍使用稳定 SHA256 键。Server 不执行外部探针，只负责指令、缓存和分发。
