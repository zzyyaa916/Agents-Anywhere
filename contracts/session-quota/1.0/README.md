# 会话限额等待 1.0（P3）

平台协议 1.2 在保留 1.0/1.1 读取能力的基础上增加 SessionStatus `limited` 和 SessionView `quotaLimit`：state=limited|ready|stopped|resumed、resetsAt(UTC ISO 或 null)、accountKey(hash 或 null)、windows(命中窗口种类)、externalSessionId(原生恢复 ID)、interruptedAt(UTC)。这是会话事实，不替代 Goal usageLimited。

Connector 在终止限额错误的 session.state.updated 中增加 metadata.quotaLimited=true、statusReason=usage_limit、status=error（底层 Runtime 自身仍为 error，Server 投影为 limited）。泛化 429、普通网络/API 错误不判定为账号额度。Server 根据对应 connector/runtimeId 绑定的账号缓存选择所有耗尽窗口中最晚的 resetsAt；无可靠数据时保留未知，不猜测恢复时间。原失败 Timeline 保留并追加安全系统提示。

GET /api/v2/sessions/{id}/quota 返回 quotaLimit；POST .../quota/recheck 受 P2 账号最小间隔与退避控制，仅新鲜同账号额度确认恢复才提前 ready。到点读时计算 idle；Server 发送门禁重新核对，恢复沿用原 externalSessionId，缺失/变化返回 409，禁止换新线程。运行态缓存的旧 idle/error 不能覆盖持久 limited，过期旧 limited/error 投影为 idle。所有官方客户端读到恢复后的 idle 可按原发送接口使用（真实安装包另验）。

停止将等待标为 stopped，删除沿用级联删除，不存在后台自动复活或重发；可选自动重试未实现。账号变化时不能用另一账号的窗口提前解除旧等待。
