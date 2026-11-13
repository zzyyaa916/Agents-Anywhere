# Claude 原生被动用量来源（替代原说明书 §4.2 的后续用户修订）

2026-11-10 用户要求：仅读取 Claude Code 正常任务期间提供的数据、缓存并展示，不为额度采集启动交互会话或任务，不继续请求私有 OAuth 用量接口。账号原生登录仍由用户在工作设备本机完成。

实现采用官方 Agent SDK RateLimitEvent / RateLimitInfo，只在 Claude runtime 内部解析 SDK 对象，通过 host 内部回调传递白名单原始类型（窗口种类、0..1 比例、UTC epoch 重置时间），不传递原始对象、raw、凭据或文本响应。此 host 扩展不改变 Server、Connector RPC、Runtime wire schema 或 API 字段。

同一连接创建时捕获非敏感稳定账号 hash；每次观察先核对当前账号，不混用已切换账号的数据；自定义环境和模型网关不接入此采集。账号身份来自本机 Claude 配置的 accountUuid/邮箱，仅 hash 离开本机，不读取 .credentials.json 或 Keychain。缓存写入独立 Connector 数据目录的现有 JSON KV，跨运行实例共享同一对象与锁。

仅数字与可靠重置时间均存在的窗口进入既有 usage-response 1.0 格式。SDK 缺失比例或时间时不猜数值；未知状态/窗口不升级为可用额度。合并窗口时保留各自观测时间，2.6.3 起过滤已重置窗口，对外新鲜时间取最新有效观察。刷新只读观察缓存，原生观察不触发网络请求；外部分发仍遵守现有 Server 账号去重、Claude 300 秒门禁与错误退避。不会到点伪造 100%，首次无数据展示不可用/等待原生数据。

兼容：Android 和其他客户端继续读取 Server 缓存，不接触厂商凭据。此前已部署的旧 Connector 仍使用旧采集方式，安装 Android APK 不会自动替换服务器 Connector；必须升级 Connector 才能切换本来源。Codex 来源保持既有只读 app-server 协议。

来源：[Anthropic Python Agent SDK RateLimitInfo](https://code.claude.com/docs/en/agent-sdk/python#ratelimitinfo)。事件通常在状态变化时产生，故不承诺每条消息后更新或闲置时实时刷新。

## 2.6.2 固定身份修复

启用固定运行身份 broker 时，不再读取 Connector 无权访问的 Claude 账号配置，统一通过同一 Claude launcher 的 `auth status` 获取非敏感身份，以邮箱哈希作为该模式的稳定账号键；即使配置文件可读性变化也不切换来源。此模式的旧 accountUuid 哈希缓存不沿用，等待后续正常任务的合法原生事件重新积累。普通设备沿用文件身份来源。仅哈希及标准化套餐信息离开本机，不记录原始 CLI 输出。

身份查询有 15 秒超时并在线程中执行，未登录、无邮箱或不支持的认证类型不产生身份。创建观察器和接收事件时都核对账号，切号后拒绝旧连接数据；观察器的 KV 更新仍在事件循环串行执行。该只读 CLI 查询不创建模型任务，不请求私有用量接口；不保证 CLI 自身完全离线，也不保证每次正常任务都会产生有效比例和重置时间。

## 2026-11-12 身份采集节流

固定 broker 身份查询在 Connector host 内缓存 60 秒（失败结果同样节流），同一 host 的并发事件和运行实例共用缓存与锁。过期后重新核对账号并拒绝旧连接的不同账号结果；账号切换检测最长可能延迟约 60 秒。普通配置文件身份不走此缓存，仍逐次核对。


## 2.6.2 unifiedWindows 与安卓问答卡片修复

Claude CLI 的原生 rate_limit_event 可以只在 rate_limit_info.unifiedWindows 中携带五小时与七天窗口，Python SDK 将这些字段保留于 RateLimitInfo.raw。采集现同时读取两个窗口，同一窗口只调用观察器一次，未提供统一窗口时沿用外层单窗口字段；继续拒绝非原生事件和异常数值，不把原始事件写入用量缓存。

已覆盖 SDK 真实解析器和双窗口到本地用量缓存的传递。测试夹具按本机 CLI 中的字段定义构造，时间、数值及标识使用合成数据；用户提及的抓取原文尚未提供，不能将此夹具称为该原文的逐字重放。

同轮安卓修复将时间线内问答卡片的内容区域改为有最大高度的可滚动布局，避免在无限高度的时间线行中使用权重后问题与选项被量为零高；输入框旁的卡片仍沿用受约束的空间分配。

验证：Connector 全套 1642 passed、2 skipped（macOS 专属）、1 条既有 Pydantic 警告；原生用量专项 23 passed。安卓编译与 190 项单元测试通过，无失败或跳过。未生成安卓安装包，问答卡片还需用户真机验证。Oracle 部署及真实 Claude 对话结果另行记录。

## 双源手动探针（当前规则）

后续用户完整规范已替代此前零散方案：事件通过 Connector 推送到 Server，并与仅限甲骨文 ARM 的手动探针逐窗口合并。所有观察时间由 Server 接收时记录，窗口长期保留，不按本机时间或 TTL 清空。没有自动探针；具体以[手动探针说明](claude-usage-probe.md)为准。
