# P3 原会话续聊交付核查（本地完成，未部署）

日期：2026-11-09。分支 `feat/con+be+fe+dsk/quota-resume`，继承 P2 `b20cc0a0`；版本 2.5.0。P1 删除在 `fee54aee`，P2 单独分支与报告保留。

## 改动与需求对应

| 文件组 | 具体结果 | 需求 |
| --- | --- | --- |
| Connector quota_errors、runtime_host、Claude sdk/events | 集中保守识别；Codex 结构错误/文案、Claude 两种载体；只上报限额事实，泛化 429 不误判 | §5.3–5.4 |
| Server core/session_quota、models、session_states、quota repository | 持久 limited、命中窗口、UTC 恢复时间、账号 hash 和原生 ID；到点读时 idle；成功续发后消费等待 | §5.3–5.4 |
| session_run、session_quota API、session state ingest、cache/meta projection | 门禁在实际发送路径重查；保留原 ID、缺失/变化拒绝新建；重新检查受 P2 节流；停止/删除不自动复活 | §2 数据一致、§5.3 |
| Timeline repository、通知处理 | 保留原始失败，追加“因限额中断”安全系统项；原生完整重同步不删除平台标注 | §5.3 |
| Web / Desktop session-quota、session-view、sidebar、状态类型 | 限额样式、恢复时间/未知占位、重新检查、等待后手动继续提示 | §5.4 |
| contracts/protocol/1.2、session-quota/1.0、导出器及生成类型 | 冻结旧契约；limited 事件用 1.2，恢复事件继续兼容 1.0；Android 只扩展数据版本接收 | §2、§5.4、P0 D13–D14 |
| v2_56、版本、CHANGELOG、打包工作流名称 | 可升级回滚、全端 MINOR 同步；复用官方原生打包脚本 | §7–§8 |

## §5.5 验收逐条结果

| 原验收项 | 结果 |
| --- | --- |
| Codex 打满 5 小时后进入 limited、时间正确、不新建 | **本地模拟通过，真实额度打满待验**：Connector 强信号识别，数据库对应账号窗口取最晚恢复时间，原平台/原生 ID 不变，安全标注持久化。 |
| 到点同会话带原上下文继续 | **协议/恢复代码回归通过，真实任务进度待验**：推进持久 deadline 后列表与 Runtime 投影 idle，实际发送参数沿用原 ID；原生 ID 缺失拒绝；既有 SDK thread/resume、Claude resume 路径回归。不能把模拟参数检查当作实际上下文工作验证。 |
| Claude 同样复现通过 | **本地模拟通过，真实额度打满待验**：同一组双 Runtime 测试，加助手错误块/错误结果、Host 上报与完整 Claude 回合回归。 |
| 官方 iOS 到点后原会话可发消息 | **待实机验收**：已核查源码未知状态容错，Server 到点回 idle，恢复事件用旧版本；未运行官方安装包，不宣称通过。 |
| 普通错误不误判 | **本地通过**：普通 429、网络、权限错误、DSH、普通助手引用均不判定 limited；创建、发送、中断、状态共享等既有行为回归通过。 |
| 开启自动重试仅重发一次 | **不适用（可选功能未实现）**：默认无自动重发，恢复后由用户手动继续；无定时重发副作用。 |

补充：未知 deadline 的重新检查只接受新鲜同账号、对应来源绑定的可用额度；旧值/另一账号不会提前解除。停止 limited 与删除回归通过；重复失败保留同一平台会话，未引入新建替代路径。

## 本地验证

- Server P3 / P2 / 旧契约 / 原生身份 / 架构 / Connector pipeline / P1 删除回归：82 通过。
- 数据库迁移（含 v2_56 升降级）、状态机、状态共享、原有创建/发送/中断：171 通过、1 跳过（既有可选环境项），200 项不属于本次筛选。
- 最终状态序列与契约专项：38 通过；时间线标注加入后再跑续聊 / Connector pipeline / 旧新契约：40 通过。
- 最后显式补测时间线标注去重/完整重同步保留、直接删除 limited，会话专项 7 通过。
- Connector 最终用量、限额、完整 Claude 回合、Codex/Claude SDK、Host：182 通过。
- Web 测试 475 通过；Desktop renderer 477 通过；新界面最终专项 2 通过；Electron 主进程 163 通过。
- Web 与 Desktop 类型、契约检查通过；两套生产构建通过。新 Python 模块 lint 与语法/未定义变量检查通过。
- 测试仅使用独立 venv、一次性 PostgreSQL 测试库、虚构账号/凭据、模拟厂商响应，没有实际账号额度探测和真实 Agent 任务；没有部署或重启运行中的 Connector。

## 未解决风险与交付缺口

真实 Codex/Claude 用量数值、额度耗尽后的实际上下文进度、官方 iOS 降级路径仍须实机验证；当前 Linux VM 不能产出官方要求的 Windows/macOS 原生签名安装包，没有 GitHub 发布身份，所以没有远端 fork、部署、签名、公证或安装替换。此处是可审查的本地实现，不是已上线版本。

Claude 用量接口非官方，结构变动会降级。P2 自定义凭据 environment/codexHome 暂显示不可用；无账号 hash 时不会用另一账号配额提前解锁未知等待，需停止等待后手动继续原会话。原生历史已被用户自行删除时会明确失败，不能保证恢复已不存在的上下文。

P0 发现的官方模型渠道凭据链路未改动；本次新增采集链路只发送白名单数字和账号 hash。生产数据库/日志未读取，因此不能把本地合成凭据检查表述为生产凭据审计。P1 报告记录过的环境恢复风险仍保留，本期始终使用独立测试解释器，不再操作运行中的环境。

## 本期文件清单

- `.github/workflows/fork-desktop-build.yml`
- `CHANGELOG.md`
- `android/app/build.gradle.kts`
- `android/app/src/main/java/com/agentsanywhere/app/feature/sessiondetail/SessionDetailReducer.kt`
- `connector/connector/account_usage.py`
- `connector/connector/quota_errors.py`
- `connector/connector/runtimes/claude/sdk/events.py`
- `connector/connector/server/runtime_host.py`
- `connector/pyproject.toml`
- `connector/tests/test_quota_errors.py`
- `contracts/protocol/1.2/README.md`
- `contracts/protocol/1.2/manifest.json`
- `contracts/protocol/1.2/schemas/capabilities-response.schema.json`
- `contracts/protocol/1.2/schemas/capability-set.schema.json`
- `contracts/protocol/1.2/schemas/event-envelope.schema.json`
- `contracts/protocol/1.2/schemas/event-recovery-response.schema.json`
- `contracts/protocol/1.2/schemas/goal-request.schema.json`
- `contracts/protocol/1.2/schemas/goal-response.schema.json`
- `contracts/protocol/1.2/schemas/goal-state.schema.json`
- `contracts/protocol/1.2/schemas/handshake-request.schema.json`
- `contracts/protocol/1.2/schemas/handshake-response.schema.json`
- `contracts/protocol/1.2/schemas/model-catalog-response.schema.json`
- `contracts/protocol/1.2/schemas/model-catalog.schema.json`
- `contracts/protocol/1.2/schemas/permission-catalog-response.schema.json`
- `contracts/protocol/1.2/schemas/permission-catalog.schema.json`
- `contracts/protocol/1.2/schemas/plan-document.schema.json`
- `contracts/protocol/1.2/schemas/planning-request.schema.json`
- `contracts/protocol/1.2/schemas/planning-response.schema.json`
- `contracts/protocol/1.2/schemas/planning-state.schema.json`
- `contracts/protocol/1.2/schemas/session-snapshot-response.schema.json`
- `contracts/protocol/1.2/schemas/ws-ticket-request.schema.json`
- `contracts/protocol/1.2/schemas/ws-ticket-response.schema.json`
- `contracts/session-quota/1.0/README.md`
- `desktop-workbench/package.json`
- `desktop-workbench/renderer/package.json`
- `desktop-workbench/renderer/scripts/generate-protocol-types.mjs`
- `desktop-workbench/renderer/src/components/pages/device-page.tsx`
- `desktop-workbench/renderer/src/components/session-detail.tsx`
- `desktop-workbench/renderer/src/components/session-quota.tsx`
- `desktop-workbench/renderer/src/components/session-view.tsx`
- `desktop-workbench/renderer/src/components/sidebar/session-sidebar-item.tsx`
- `desktop-workbench/renderer/src/features/dashboard/types.ts`
- `desktop-workbench/renderer/src/features/goals/use-session-goal.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/capabilities-response.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/capability-set.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/event-envelope.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/event-recovery-response.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/goal-request.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/goal-response.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/goal-state.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/handshake-response.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/model-catalog-response.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/model-catalog.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/permission-catalog-response.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/permission-catalog.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/plan-document.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/planning-request.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/planning-response.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/planning-state.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/session-snapshot-response.ts`
- `desktop-workbench/renderer/src/generated/protocol/v1_2/ws-ticket-response.ts`
- `desktop-workbench/renderer/src/lib/demo-api.ts`
- `desktop-workbench/renderer/test/session-quota.test.mjs`
- `docs/fork/p3-delivery-report.md`
- `docs/releases/2.5.0-fork-p3.md`
- `dsh-bridge-next/package.json`
- `ios/Agents Anywhere/Agents Anywhere.xcodeproj/project.pbxproj`
- `server/agent_server/api/session_quota.py`
- `server/agent_server/api/sessions.py`
- `server/agent_server/app.py`
- `server/agent_server/core/events.py`
- `server/agent_server/core/models.py`
- `server/agent_server/core/protocol.py`
- `server/agent_server/core/session_quota.py`
- `server/agent_server/core/session_states.py`
- `server/agent_server/infra/db/migrations.py`
- `server/agent_server/infra/db/schema.py`
- `server/agent_server/infra/repositories/facade.py`
- `server/agent_server/infra/repositories/session_quota.py`
- `server/agent_server/infra/repositories/sessions.py`
- `server/agent_server/infra/repositories/timeline.py`
- `server/agent_server/services/connector_ingest.py`
- `server/agent_server/services/connector_notifications.py`
- `server/agent_server/services/repository_ports.py`
- `server/agent_server/services/session_meta_projection.py`
- `server/agent_server/services/session_run.py`
- `server/migrations/versions/v2_56.py`
- `server/pyproject.toml`
- `server/scripts/export_protocol_schemas.py`
- `server/tests/test_database_migrations.py`
- `server/tests/test_protocol_contracts.py`
- `server/tests/test_session_quota.py`
- `web-next/package.json`
- `web-next/scripts/generate-protocol-types.mjs`
- `web-next/src/components/pages/device-page.tsx`
- `web-next/src/components/session-detail.tsx`
- `web-next/src/components/session-quota.tsx`
- `web-next/src/components/session-view.tsx`
- `web-next/src/components/sidebar/session-sidebar-item.tsx`
- `web-next/src/features/dashboard/types.ts`
- `web-next/src/features/goals/use-session-goal.ts`
- `web-next/src/generated/protocol/v1_2/capabilities-response.ts`
- `web-next/src/generated/protocol/v1_2/capability-set.ts`
- `web-next/src/generated/protocol/v1_2/event-envelope.ts`
- `web-next/src/generated/protocol/v1_2/event-recovery-response.ts`
- `web-next/src/generated/protocol/v1_2/goal-request.ts`
- `web-next/src/generated/protocol/v1_2/goal-response.ts`
- `web-next/src/generated/protocol/v1_2/goal-state.ts`
- `web-next/src/generated/protocol/v1_2/handshake-response.ts`
- `web-next/src/generated/protocol/v1_2/model-catalog-response.ts`
- `web-next/src/generated/protocol/v1_2/model-catalog.ts`
- `web-next/src/generated/protocol/v1_2/permission-catalog-response.ts`
- `web-next/src/generated/protocol/v1_2/permission-catalog.ts`
- `web-next/src/generated/protocol/v1_2/plan-document.ts`
- `web-next/src/generated/protocol/v1_2/planning-request.ts`
- `web-next/src/generated/protocol/v1_2/planning-response.ts`
- `web-next/src/generated/protocol/v1_2/planning-state.ts`
- `web-next/src/generated/protocol/v1_2/session-snapshot-response.ts`
- `web-next/src/generated/protocol/v1_2/ws-ticket-response.ts`
- `web-next/src/lib/demo-api.ts`
- `web-next/test/session-quota.test.mjs`
