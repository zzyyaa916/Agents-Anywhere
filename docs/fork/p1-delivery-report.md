# P1 删除功能交付核查（本地验证完成，尚未部署）

日期：2026-11-08。分支：`feat/be+fe+dsk/delete-projects-sessions`。基线：上游 `8fef5e3b967dfd719f4712749b3b3a3ffe4736a2`。按用户后续“按照官方的做”指示，沿用官方分层、API、契约和版本规则，跨端 MINOR 同步为 2.3.0。P2/P3 未实施。

## 改动与需求对应

| 范围 | 改动 | 需求 |
| --- | --- | --- |
| Server API / service / repository | 新增单会话 DELETE、项目删除预览，扩展原项目 DELETE 为级联；403/404/409、数量变化重确认、精确阻塞 ID | §3.1–3.3 |
| 数据与同步 | 文件/缩略图、业务子数据、终端根与缓存、Runtime cache、Timeline 待写清理；最小原生身份删除标记与审计；晚到同步、并发上传/发送防护；缓存清理失败可重试和后台恢复 | §3.3–3.4，P0 D05–D09 |
| Web 与 Desktop renderer | 两套官方源目录同步新增危险色菜单、可取消确认、项目名二次确认和 Server 全量计数；成功即时移除本地列表、退出删除会话；409 明确提示阻塞 ID | §3.1–3.4 |
| 版本 / 更新 / 打包 | 按官方 MINOR 规则同步所有端版本元数据，清空 Desktop 官方安装包下载源，准备原生平台手动打包工作流 | §2、§7.5、§8 |
| 文档与测试 | API、P0 修订、CHANGELOG、迁移/回滚/发布说明，后端与两个 renderer 验收测试 | §7、§8 |

未改变官方模型渠道凭据链路，没有读取或传输真实 Codex/Claude 登录凭据，没有启动真实 Agent 回合，没有把生产配置或登录信息写入提交。

## §3.4 验收清单逐条结果

| 原验收项 | 结果与证据 |
| --- | --- |
| Web 删除已结束会话后，Desktop 和官方 iOS 列表也消失 | **部分通过**：Server 删除后会话 meta 为 404、列表不再返回，同一 Server 提供一致数据；Web/Desktop 菜单、API、状态更新均已接入、两套构建通过。尚未用已安装 Desktop 与官方 iOS 做跨设备真实刷新，不能勾选全通过。 |
| 运行中会话拒删且明确提示 | **本地通过**：running/waiting/pending/stopping/waiting_approval、active run、缓存运行态、活动 Goal、未完成创建均返回 409，包含阻塞 ID；两端交互测试验证提示、弹窗保留。 |
| 删除项目级联清理会话和附件，无业务残留 | **本地通过**：含归档和 106 个跨分页会话；数据库业务记录、Timeline、文件/缩略图、终端与缓存清理，重复原生绑定可删除、防重导入及 SQL 迁移回滚。Local 真文件、S3 多页清理使用官方适配器测试；真实生产/S3 环境未操作。只保留允许的最小抑制/审计元数据与原活动统计事实。 |
| 无权限账号调用删除返回 403 | **本地通过**：独立测试账号对项目/会话 DELETE 和预览均为 403，所有者数据保持。 |
| 确认可取消，取消后数据不变 | **本地通过**：两套 renderer 真实 React/JSDOM 交互测试，取消不调用删除；项目名不匹配、计数未加载/失败时不能确认，计数变化要求重新确认，重复点击只发一次。 |

## 验证记录

- Server 广泛会话/API/Timeline/身份/状态/inventory 回归：292 passed，14 skipped。
- 最终删除、官方 Connector 删除及原生工作流回归：39 passed。
- 删除、架构边界、当前版本、无版本库识别、v2_53→v2_54→v2_53 迁移专项：38 passed（为前一批验证，部分与上述重叠，不相加）。
- Local/S3 设备数据存储、附件 streaming、Connector pipeline、来源行锁、Timeline 连接专项：23 passed；有 1 条现有大图 fixture 的 Pillow 警告。
- Web：473 passed；类型检查、protocol:check、生产构建通过。
- Desktop renderer：475 passed；类型检查、protocol:check、静态生产构建通过。
- Desktop 主进程：163 passed；TypeScript 编译通过。没有启动 Electron GUI 或当前 Connector。
- 新 Python 文件 ruff 检查通过，修改代码的未定义名称/重复定义检查通过，git diff --check 通过。仓库现存 sessions.py 的 BaseModel 未使用导入未顺手清理，未宣称全仓库 lint 零问题。
- 原生打包 workflow YAML 可解析，只有手动触发、contents:read、两个 native 平台；不引用用户 secrets，不自动发布或部署。此工作流**尚未在 GitHub 执行**。
- 改动集合的潜在硬编码密钥模式扫描为 0，未纳入 .env 或 lockfile；此项只针对本次改动，不替代生产数据库/全链路日志审计。

## 未完成与风险

1. 当前 GitHub CLI 没有登录，尚未建立远端 fork、推送或运行原生工作流；没有要求用户把 token 发到聊天。
2. 尚未生产备份、部署或替换任何已安装客户端。Win/Mac 安装包、签名/公证、官方 iOS/Android 刷新需要对应真实环境；官方打包脚本明确拒绝在 Linux 构建这些安装包。故 P1 尚未达到“成套部署并全设备验收”的完整交付门槛，不进入 P2。
3. SQL/文件没有共同事务：文件清理失败时 SQL 可回滚，但已删除的文件不能恢复；返回 503 后应重试删除。SQL 成功后的缓存失败保留持久待清理状态，由重试/后台恢复继续。详情见发布说明。
4. Server 能依收到的 Runtime 事实保护忙会话；离线期间发生但尚未同步的原生活动无法实时核实。同步路径新增删除检查查询，尚未做生产负载压测。
5. P0 已报告官方模型渠道在 Server 接收/保存/下发 Key，与本次凭据红线冲突；按要求未顺手修改，P1 也未调用它。不能宣称上游全站凭据合规。
6. 早先依赖安装误用了继承的 uv 环境变量，已按本机原 Connector 源码补回所需依赖；没有原依赖快照，不能保证逐版本恢复。之后所有 Python 开发命令均明确使用仓库 server/.venv，未再修改该运行环境，未停止或重启当前 Connector 进程。后续启动兼容性仍应留意，不能用“当前进程在线”替代重启验证。

## 完整改动文件清单

- `.github/workflows/fork-desktop-build.yml`
- `CHANGELOG.md`
- `android/app/build.gradle.kts`
- `connector/pyproject.toml`
- `desktop-workbench/config.json`
- `desktop-workbench/package.json`
- `desktop-workbench/renderer/messages/en.json`
- `desktop-workbench/renderer/messages/zh-CN.json`
- `desktop-workbench/renderer/package.json`
- `desktop-workbench/renderer/src/components/sidebar/history-delete-dialog.tsx`
- `desktop-workbench/renderer/src/components/sidebar/project-sidebar-item.tsx`
- `desktop-workbench/renderer/src/components/sidebar/session-sidebar-item.tsx`
- `desktop-workbench/renderer/src/components/workspace-context.tsx`
- `desktop-workbench/renderer/src/features/dashboard/api.ts`
- `desktop-workbench/renderer/src/features/dashboard/types.ts`
- `desktop-workbench/renderer/test/history-delete-dialog.test.mjs`
- `docs/api/history-deletion.md`
- `docs/fork/p0-audit-and-revised-plan.md`
- `docs/fork/p1-delivery-report.md`
- `docs/releases/2.3.0-fork-p1.md`
- `dsh-bridge-next/package.json`
- `ios/Agents Anywhere/Agents Anywhere.xcodeproj/project.pbxproj`
- `server/agent_server/api/projects.py`
- `server/agent_server/api/sessions.py`
- `server/agent_server/app.py`
- `server/agent_server/core/history_deletion.py`
- `server/agent_server/core/models.py`
- `server/agent_server/infra/db/migrations.py`
- `server/agent_server/infra/db/schema.py`
- `server/agent_server/infra/repositories/active_runs.py`
- `server/agent_server/infra/repositories/connectors.py`
- `server/agent_server/infra/repositories/facade.py`
- `server/agent_server/infra/repositories/history_deletion.py`
- `server/agent_server/infra/repositories/sessions.py`
- `server/agent_server/services/connector_deletion.py`
- `server/agent_server/services/connector_notifications.py`
- `server/agent_server/services/history_deletion.py`
- `server/agent_server/services/repository_ports.py`
- `server/agent_server/services/session_run.py`
- `server/agent_server/services/timeline_write_buffer.py`
- `server/migrations/versions/v2_54.py`
- `server/pyproject.toml`
- `server/tests/test_backend_mvp.py`
- `server/tests/test_database_migrations.py`
- `server/tests/test_history_deletion.py`
- `web-next/messages/en.json`
- `web-next/messages/zh-CN.json`
- `web-next/package.json`
- `web-next/src/components/sidebar/history-delete-dialog.tsx`
- `web-next/src/components/sidebar/project-sidebar-item.tsx`
- `web-next/src/components/sidebar/session-sidebar-item.tsx`
- `web-next/src/components/workspace-context.tsx`
- `web-next/src/features/dashboard/api.ts`
- `web-next/src/features/dashboard/types.ts`
- `web-next/src/lib/demo-api.ts`
- `web-next/test/history-delete-dialog.test.mjs`
