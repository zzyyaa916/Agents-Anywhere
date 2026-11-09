# P2 用量功能交付核查（本地实现，未部署）

分支：`feat/con+be+fe+dsk/account-usage`。版本 2.4.0；承接 P1。按用户后续要求，P2 汇报后继续 P3，仍分别保留分支和提交。

## 改动与需求对应

| 文件组 | 需求 |
| --- | --- |
| Connector account_usage / dispatch | §4.2：本机只读采集、双格式解析、duration 判断、凭据本机使用；§4.3：持久间隔、退避、白名单结果 |
| Server core / repository / service / API / app | §4.3–4.4：统一调度、跨 worker/用户账号预算、来源绑定、用户隔离、缓存快照与受限手动刷新 |
| v2_55 / schema / migration classifier | §4.4、§8：缓存与采集门禁可迁移、可回滚 |
| Web 与 Desktop account-usage / footer / session-view / workspace-context | §4.5：剩余百分比、当地重置时间、过期更新时间、≤20% 对应实例提示，无账号占位 |
| 契约、版本、日志与测试 | §2、§7、§8：成套 2.4.0、接口契约、隔离测试、无真实凭据操作 |

## §4.6 逐条验收

| 验收项 | 结果 |
| --- | --- |
| Codex 5 小时/周数值与官方桌面一致 | **待实机比对**；模拟协议验证窗口位置交换、剩余计算和未知时长，未读取真实账号。 |
| Claude 数值与同机 /usage 一致 | **待实机比对**；模拟新 limits 优先、旧字段、分模型窗口和请求头，未使用真实 OAuth 凭据。 |
| 同账号三设备只显示一份 | **本地通过**；数据库集成测试并发刷新、三来源绑定只采集一次、返回一个快照。 |
| 断网/429 保留旧值且不影响会话 | **本地通过（模拟故障）**；持久 60/300 秒门禁、300→900→1800 退避、重建采集器仍使用门禁；真实 React 界面保留数值并标过期，其他 API 回归通过。 |
| 日志/数据库无账号凭据明文 | **本地链路通过，生产待抽查**；严格额外字段拒绝、合成 token 请求只进入本机 HTTP，序列化快照与 KV 不含 token/上游额外字段；日志仅异常类型，不使用真实账号与生产日志。 |

## 验证

- Server 用量、架构、删除、迁移：146 通过；全局锁变更后重跑用量专项（见提交前结果）。
- Connector 用量：10 通过。Web 类型/协议通过、既有测试 473 通过；Desktop renderer 类型通过、既有测试 475 通过；新增两端用量交互测试另行运行。
- 新增 Python 模块 ruff 通过；未将 headless 测试当作原生安装和官方 App 实测。

## 未解决风险

Claude 接口非官方；自定义凭据环境暂不可用；真实账号数值/日志对照与原生打包待完成。未部署、更未重启运行中的 Connector。本期没有改动 P0 已报告的官方模型渠道凭据链路。

## 本期文件

- `CHANGELOG.md`
- `android/app/build.gradle.kts`
- `connector/connector/account_usage.py`
- `connector/connector/server/dispatch.py`
- `connector/pyproject.toml`
- `connector/tests/test_account_usage.py`
- `contracts/account-usage/1.0/README.md`
- `contracts/account-usage/1.0/usage-collection.schema.json`
- `contracts/account-usage/1.0/usage-response.schema.json`
- `desktop-workbench/package.json`
- `desktop-workbench/renderer/package.json`
- `desktop-workbench/renderer/src/components/account-usage.tsx`
- `desktop-workbench/renderer/src/components/session-view.tsx`
- `desktop-workbench/renderer/src/components/sidebar/sidebar-account-footer.tsx`
- `desktop-workbench/renderer/src/components/workspace-context.tsx`
- `desktop-workbench/renderer/test/account-usage.test.mjs`
- `docs/releases/2.4.0-fork-p2.md`
- `dsh-bridge-next/package.json`
- `ios/Agents Anywhere/Agents Anywhere.xcodeproj/project.pbxproj`
- `server/agent_server/api/account_usage.py`
- `server/agent_server/app.py`
- `server/agent_server/core/account_usage.py`
- `server/agent_server/infra/db/migrations.py`
- `server/agent_server/infra/db/schema.py`
- `server/agent_server/infra/repositories/account_usage.py`
- `server/agent_server/infra/repositories/facade.py`
- `server/agent_server/services/account_usage.py`
- `server/migrations/versions/v2_55.py`
- `server/pyproject.toml`
- `server/tests/conftest.py`
- `server/tests/test_account_usage.py`
- `server/tests/test_database_migrations.py`
- `web-next/package.json`
- `web-next/src/components/account-usage.tsx`
- `web-next/src/components/session-view.tsx`
- `web-next/src/components/sidebar/sidebar-account-footer.tsx`
- `web-next/src/components/workspace-context.tsx`
- `web-next/src/lib/demo-api.ts`
- `web-next/test/account-usage.test.mjs`
