# Orca 功能并入 Fork：可行性报告

核查日期：2026-11-10。Fork 基线：`b0122624`（2.5.7 客户端）；Orca 源码快照：`7c018474477fb65b4ccd1fe4cd7d34620c549158`。这是设计与源码可行性核查，尚未实现下述新功能，也未启动真实付费 agent 任务。

## 结论

**可行。建议在现有 Fork 内增加任务组、独立 worktree 和交接功能，复用现有 Connector/Runtime，不整体嵌入 Orca。** 用户可以选择单个 agent，或把同一需求同时发给三个 agent；三份结果分别保留，用户选择后再采用。选中的结果可以交给另一个 AI 审查或继续开发。

同一需求的三个候选方案应当独立运行，不能默认拆成三个互补子任务，也不能默认自动合并。三个 agent 可以是不同厂商，也可以是同一厂商的不同模型或配置，但各自必须有独立会话与工作目录。

## Orca 的实际做法与证据

以下链接固定到所查提交，避免后续主分支变化。Orca 是 Electron/TypeScript 项目，仓库声明 MIT；借用代码时须保留对应版权和许可证，另查所带依赖许可。

| 原理 | 源码证据 | 对 Fork 的启示 |
| --- | --- | --- |
| 用 Git worktree 创建独立检出目录和分支，处理基线解析、并发及删除冲突 | [worktree-add.ts](https://github.com/stablyai/orca/blob/7c018474477fb65b4ccd1fe4cd7d34620c549158/src/main/git/worktrees/creation/worktree-add.ts) | worktree 操作应在拥有仓库的 Connector 执行；客户端只发结构化请求 |
| 以持久化数据库保存调度信息，使用 SQLite WAL；内存事件不承担恢复真相 | [orchestration-db.ts](https://github.com/stablyai/orca/blob/7c018474477fb65b4ccd1fe4cd7d34620c549158/src/main/runtime/orchestration/db/orchestration-db.ts) | Fork 已有 Server/PostgreSQL，直接扩展现有存储，不引入第二个调度数据库 |
| 消息既可走结构化会话，也可走终端输入；使用 operationId、运行代际及队列语义避免误投和重复执行 | [send-agent-turn.ts](https://github.com/stablyai/orca/blob/7c018474477fb65b4ccd1fe4cd7d34620c549158/src/main/runtime/orchestration/turn-delivery/send-agent-turn.ts) | 复用 Fork 的 Runtime 消息与 clientMessageId，不依赖模拟键盘输入 |
| Worker 启动时获得 task/dispatch 标识、任务正文与回报规则 | [worker-dispatch-preamble.ts](https://github.com/stablyai/orca/blob/7c018474477fb65b4ccd1fe4cd7d34620c549158/src/main/runtime/orchestration/workers/launch/worker-dispatch-preamble.ts) | 子任务需要稳定身份、归属和结果回执，不能只开三个聊天窗口 |
| 按当前运行范围解析单个或群组收件人，身份由宿主证明 | [group-addressing.ts](https://github.com/stablyai/orca/blob/7c018474477fb65b4ccd1fe4cd7d34620c549158/src/main/runtime/orchestration/addressing/groups/group-addressing.ts) | “发送给三个”须固定收件人快照，不能广播给其他项目中的 agent |
| 回报归入对应 dispatch/run，完成后的后续操作沿任务谱系定位 | [dispatch-report-mailbox.ts](https://github.com/stablyai/orca/blob/7c018474477fb65b4ccd1fe4cd7d34620c549158/src/main/runtime/orchestration/workers/reports/dispatch-report-mailbox.ts)、[report-follow-up-action.ts](https://github.com/stablyai/orca/blob/7c018474477fb65b4ccd1fe4cd7d34620c549158/src/main/runtime/orchestration/workers/reports/report-follow-up-action.ts) | 交接必须记录来源候选和版本，不能只复制最后一句回复 |

注意：[coordinator.ts](https://github.com/stablyai/orca/blob/7c018474477fb65b4ccd1fe4cd7d34620c549158/src/main/runtime/orchestration/coordinator/coordinator.ts) 中这个 Coordinator 路径的 `decompose()` 明确要求任务预先存在；不能仅凭 README 宣称直接复用该类就能自动拆解任何任务。这也不是本需求首版所必需的能力。

## Fork 已有基础与缺口

本地核查 `connector/connector/runtimes/codex/runtime.py` 与 `claude/runtime.py`：两者的 `create_and_start_session` 已接收 `cwd`、附件、模型选择与 `client_message_id`，可在不同目录启动独立会话。现有 Server 已负责会话、消息、事件和权限；桌面与 Android 已有远程设备与 Runtime 选择界面。

但接收 `cwd` 不等于已经具备 worktree 生命周期管理。本次没有找到 Connector 的通用 worktree 创建/回收服务。还需新增：任务组及候选记录、仓库锁、基线固定、fan-out 的部分失败处理、结果快照、候选比较及交接入口。现有账号目录继续按 Fork 规则隔离，不复制厂商凭据来制造“三个账号”。

## 建议的用户流程

1. 输入需求，选择“单个执行”或“三个独立方案”。选择设备、仓库、基线，以及每个候选的 agent/模型。
2. Connector 将基线解析成同一个 commit；在受管理目录创建三个分支/worktree，分别启动会话。首版限定同一 Connector 上的 Git 仓库。
3. 页面展示三张候选卡：运行/等待审批/限额/失败/完成状态、总结、改动文件、diff 和测试证据。可以单独补充、取消或重试某个候选。
4. 用户选择一个候选。“选中”只标记结果，不隐含覆盖当前工作目录；“采用”单独执行，检查当前目录是否干净及是否有冲突。
5. 对选中版本点“交给其他 AI”，选择目标 agent 与“审查”或“继续开发”，预览交接内容后发送。

## 跨 AI 审查与继续任务

厂商原生 thread/session ID、隐藏推理、工具内部状态无法通用地迁移。可交接的是可追溯的任务材料：原始要求、约束、已确认决定、来源会话链接、base/head commit、包含新增及二进制文件的代码快照、测试命令与实际结果、未完成项和用户新增指令。长会话可提供摘要及按需读取的原始记录，不承诺完整原生上下文迁移。

**审查：** 从选中候选的固定快照创建新的审查 worktree，给目标 agent 明确审查范围，产出带文件/行号的意见。提示词中的“只读”不是安全隔离；需要强只读时须由运行环境限制写入。候选后续变化应标记原审查已过期。

**继续开发：** 从选中快照新建分支/worktree，由目标 AI 创建自己的原生会话继续工作，保留来源链。不要让两个运行中的 agent 同时写同一目录。不同设备之间要显式传输受权的仓库快照/补丁并核验哈希，不能直接转发来源设备的本地路径；跨设备可留第二阶段。

## 最小实现范围

| 层 | 必要变化 |
| --- | --- |
| 契约/Server | 新增 task group、candidate、handoff、artifact；成员权限、幂等键、事件和迁移；每个候选独立状态，选择结果不删除其他结果 |
| Connector | 受管理路径、Git 仓库验证、每仓库锁、创建与回收 worktree、独立 cwd 启动、快照/diff/测试产物收集、恢复后对账 |
| Web/Desktop | 单个/三个发送选择器、候选状态与对比、选择采用、交接预览和审查结果；桌面 renderer 同步 |
| Android | 同步创建、查看、选择和交接入口；大 diff 可折叠；iOS 按现有 Fork 范围暂不开发，须在版本说明中明确 |

跨端新增 API 需先更新契约，按仓库规则统一提升 MINOR，不能只提升某个客户端 PATCH。建议作为后续功能版本，和 2.5.7 更新流程交付分开。

## 必须解决的边界

- **基线与未提交改动：** 三个候选必须来自相同 commit。工作目录脏时，明确选择只用已提交基线，或显式快照未提交内容；不能悄悄 stash、reset 或遗漏新文件。
- **幂等与恢复：** 用 group/candidate/attempt 标识关联创建、投递与回报；网络超时先查询真实结果，不自动重复启动付费任务。三个中一个失败，其余结果保留。
- **隔离：** worktree 隔离文件检出，不隔离进程、网络、端口、数据库或凭据。并行测试需独立临时目录、端口和测试数据库；不默认复制 `.env`，不把含凭据的目录共享给候选。
- **成本与限额：** 三份独立执行会增加调用量，不能保证正好三倍；同账号共享配额。限额后保留原会话，让用户主动继续，不能重新开任务绕过限制。
- **采用与清理：** 纳入未跟踪和二进制文件；固定快照后比较。当前分支变化则重新检查冲突，不覆盖脏目录。运行中、有未保存成果或交接引用的 worktree 不自动删除。
- **输入与权限：** 路径限定在授权项目和受管理 worktree 根目录；校验 symlink、分支名与命令参数，禁用拼接 shell。结果/日志/补丁按账号和项目鉴权并设置大小及保留上限。

## 验收与工作量

先做同设备 Codex/Claude 的一组三候选纵向实现，验收：三者同基线不同 cwd；一条请求只执行一次；部分失败/断线重连/服务重启不重复投递；候选可独立取消；选中方案的快照与 diff 一致；审查不改变原结果；继续任务建立新会话；冲突和脏目录不丢数据；跨账号不可读。

在现有依赖可用且不增加新厂商适配的前提下，粗估：设计与契约 2–3 人日，Connector/Server 5–8 人日，Web/Desktop/Android 5–8 人日，故障恢复与跨平台验证 3–5 人日，共约 **15–24 人日**。这是基于源码的工程估算，不是已验证排期；跨设备代码传输、强沙箱、复杂自动评分另计。

推荐顺序：独立候选与结果比较 → 固定快照交给另一 AI 审查/继续 → 跨设备与更复杂编排。首版由用户选优；可提供 AI 评审建议，但不能把模型自评分当成正确性证明。
