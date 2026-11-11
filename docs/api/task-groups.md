# 独立方案任务组（2.6 Web 测试版）

所有端点位于 `/api/v2/task-groups`，要求登录，按用户及项目归属鉴权。旧客户端不受影响；Web、Desktop 和 Android 原生多 AI 工作台提供入口；Android 2.5.9 起直接调用 API 并复用原生会话，不依赖 WebView；iOS 不提供此功能。

- `POST /`：`{operationId, projectId, content, attachments?:InlineAttachmentRef[], candidates:[{runtime,runtimeId,selections:{}}]}`；候选数为 1–3，含 2 个，operationId 为 8–80 位字母/数字/连字符。同一 operationId 及正文重试返回同组，不重复创建；正文不同返回 409。只准备工作区，不自动调用模型。
- `GET /?projectId=...`：列出项目的任务组。
- `GET /{id}`：返回组、候选的独立会话 ID/状态、固定基线和选中候选。查询不启动任务。
- `POST /{id}/candidates/{slot}/start`：显式启动候选（slot 为 0–2）；投递前持久化领取状态和会话 ID，重复请求不重复投递；结果不确定时标为 unknown，只能查看原会话，不自动重试。
- `GET /{id}/candidates/{slot}/diff`：候选停止后读取相对共同基线的 diff，包含未跟踪文件，输出超限返回明确错误。
- `POST /{id}/select`：`{slot}`；仅记录选择，不覆盖/合并当前分支，不删除其他方案。
- `POST /{id}/handoffs`：`{operationId,slot,mode:"review"|"continue",target:{runtime,runtimeId,selections:{}},instructions?:string}`；instructions 为最多 8000 字的用户指令；有值时优先使用该指令，否则保留原 mode 默认提示。源会话停止后固定代码快照并创建独立工作区/会话，复用同样的显式 start 接口；返回新任务组。目标 AI 无法继承厂商私有线程或隐藏上下文。

Connector 新增 `worktree.prepare {root,groupId,count}`、`worktree.diff {root,groupId,slot}`、`worktree.handoff {root,groupId,slot,targetGroupId}`。root 必须来自已鉴权项目；ID、slot 有严格限制，不能传任意命令/目的路径。prepare 固定 clean HEAD，创建 1–3 个独立分支与 worktree；Git 项目仍禁止脏基线；非 Git 目录自动使用普通对话模式，无需安装 Git，不读取或复制所选目录中的文件。普通对话在 Connector 数据目录内为各 AI 创建空的独立目录，base 固定为 `conversation`；diff 返回空改动及说明，转发只携带指令、原始问题、近期对话和附件，不声称提供代码快照。Git 工作区位于该仓库 Git common directory 下的受管理目录；不复制忽略文件、凭据或依赖目录。handoff 使用临时 Git index 捕获已修改、已提交、未跟踪及二进制文件，不改原 index/HEAD；创建失败不删除用户文件。结果和工作区保留，首版不自动回收或合并。

Web 在候选会话产生后自动显示独立聊天栏，按各自 sessionId 复用原有聊天、事件流和消息投递；窗口可收起、关闭及重新打开，关闭不取消任务。每栏的转发对话框选择目标 AI、预览来源结论并填写指令；明确点击发送后才创建交接并启动目标会话，原窗口保留。转发请求沿用 operationId 幂等和 start 的一次性领取，不因失败自动重发。

任务组信息独立持久化，候选会话和转发会话在侧栏归属原始项目，不再为隔离目录新增「0」「1」项目。项目归属与执行目录分别保存：仅已鉴权任务组中预先领取的会话 ID 可以使用对应隔离目录；普通会话仍要求项目与目录一致，Connector 同步不得将任务组会话改归隔离目录项目。候选仍是普通会话，继续复用既有审批、消息队列、取消及限额处理。同一设备/仓库内交接；worktree 不提供进程/网络安全沙箱。review 提示 AI 只审查，但工作区可写，不能声称强制只读。

多 AI 首轮附件复用普通创建会话的 inline 附件结构（最多 10 个），每个候选单独持久化并交付；能力不支持时明确失败。交接同时携带原始附件和最近 100 条时间线消息中的附件，按 fileId 去重；超过 10 个或文件不可读时明确失败，不静默丢弃。附件通过现有附件通道交付，不拼入对话文字。
