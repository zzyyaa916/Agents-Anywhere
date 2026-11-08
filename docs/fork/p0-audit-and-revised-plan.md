# 现状核查笔记与需求修订方案（P0）

核查日期：2026-11-08。对应用户提供的《Agents Anywhere 功能需求说明书》§7 P0。

## 1. 基线、交付边界与已做检查

- 仓库：`https://github.com/anywhere-labs/Agents-Anywhere.git`。
- 本机检出：`/data/workspace/Agents-Anywhere`；克隆时的 `main` / `origin/main` 均为 `8fef5e3b967dfd719f4712749b3b3a3ffe4736a2`。
- HEAD 标题：Merge pull request #572 from anywhere-labs/cursor/sync-2.2.0-release-notes-4549。
- Server、Web、Desktop 当前包版本均为 `2.2.0`，不是说明书的 `2.0.3`。本笔记中的“当前”仅指该固定提交，后续施工前再次核对上游。
- 已阅读根目录 `AGENTS.md`、`CLAUDE.md`（内容为 `@AGENTS.md`），Web 子目录约束，Server 架构、API namespace、版本规则，以及下述状态、恢复、删除、存储、同步相关源码。
- 已通读 `contracts/` 各版本的说明文档、日志契约，扫描全部 188 个 JSON 文件的结构与枚举，核对 manifest 引用的 71 个产物 SHA-256，全部匹配。此项不等同于 JSON Schema fixtures 验证器、契约生成检查或运行集成测试。
- 当前契约：平台 `protocol/1.1`，Runtime Control `2.1`，工作流 `1.2`，本机记录 `2.0`、DSH Bridge `2.0`、ACP 通用扩展 `1.1`；旧版说明、schema 和 fixtures 仍需保留。不能把所有 `1.0` 目录当作当前可手改的产物。
- 本期只交付核查与修订文档，未改产品代码、数据库、版本号和自动更新配置，未启动真实 Runtime，未读取真实凭据、生产日志或数据库。
- 当前是本地完整克隆，尚未在 GitHub 创建远端 fork，也未推送。远端 fork 所属账号/组织尚未确定；不擅自选择发布身份。用户表示不熟悉交付环境，不要求用户现在准备技术配置，后续先完成本地实现与可执行交付步骤。

## 2. 与说明书的逐条差异及修订

| 编号 | 原需求位置 | 当前代码事实与证据 | 修订后的施工方案 |
| --- | --- | --- | --- |
| D01 | 基于版本、§7.1 | main 已为 2.2.0，包版本与发布说明已演进。 | 固定上述 SHA 为 P0 基线，不回退到 2.0.3。后续阶段从核对后的上游和前期成果建立独立分支。 |
| D02 | §2、§3.3、§6 | Web 与 Desktop 并非物理共用一个 renderer：`web-next/src/`、`desktop-workbench/renderer/src/` 各自有工作台、API 客户端与国际化资源。旧 `desktop-next/` 已退役。 | 两套当前 renderer 同步修改、分别测试，Electron 主进程另行检查；不借本项目做 UI 目录合并。 |
| D03 | §1、§3.3 | 已有 `DELETE /api/v2/projects/{project_id}`，响应 `projectId/detachedSessions/serverTime`；仓储 `projects.py:delete_project` 对含任意会话的项目返回冲突，只有空项目可删。 | 扩展既有端点，不能新增同名平行 API，也不能将“已有接口”误判为满足级联需求。新增明确的删除数量字段前先写兼容契约；保留旧响应字段的含义，不将删除数量冒充 detached 数量。 |
| D04 | §3.1、§3.3 | 没有 `DELETE /sessions/{id}`。已有会话归档 `archived`，还有 Runtime 来源可用性 `source_state`；它们与删除不同。前端 `deleteProject` 已有 API/context 方法，当前菜单仅有归档等入口，且 context 的旧逻辑会把会话 projectId 清空。 | 新增单会话删除契约和入口；项目删除成功须实际移除子会话，不能沿用“解绑会话”的本地列表更新。归档与来源状态保持各自语义。 |
| D05 | §3.3 Connector 无改动、§3.4 无残留 | `sessions.py:upsert_connector_session` 会按平台 ID 或 `(connector_id,runtime_id,external_session_id)` 找回身份，并在缺记录时插入；同时按 cwd 自动建项目。Connector 周期/重连扫描会重报本地历史。 | 单纯硬删会重新出现。P1 在 Server 保存最小删除抑制标记，覆盖平台身份与原生绑定身份，过滤元数据、完整快照、增量和 inventory 的重放，且保证被抑制条目不阻塞同批其他会话。Connector 本地原生历史不删除。 |
| D06 | §3.4 数据库无残留 | D05 所需防重导入标记及 §3.3 操作日志必须保留极少元数据，与字面上的“数据库零记录”冲突。 | “无残留”明确为消息、Timeline、附件与会话/项目业务行清除；仅保留删除身份抑制标记和审计记录，不留正文、附件、原始路径或凭据。此为显式需求修订，不能静默将硬删改成软归档。 |
| D07 | §3.2 正在运行 | 会话有 `waiting/pending/running/stopping/waiting_approval`，还存在独立 active-run 表、Redis Runtime 状态缓存、创建工作流和 Goal 自动续跑。仅检查 SQL 的 `status == running` 不够。 | 删除前统一检查最新可用 Runtime 状态、active run、未完成创建/准入及自动续跑；上述忙碌态拒绝 409。停止请求已发出但仍 stopping 也不能删。检查与准入/ingest 必须共享有效的并发隔离；项目任一忙会话导致整项拒绝，返回阻塞会话 ID，不做部分删除。离线不能当作 idle。 |
| D08 | §3.3、§3.4 | `sessions.project_id` 外键为 RESTRICT；Timeline、shares、active runs、planning 等子表存在 CASCADE。还有没有 session FK 的工作流/统计关联。文件支持 Local 与 S3。 | 删除顺序先子会话再项目；逐项审查无 FK 的会话关联。复用 `files.delete_session`，涵盖原始文件、元数据与缩略图；不假设仅有本地附件目录。不改无关全局使用量统计口径。 |
| D09 | §3.3 | Timeline 先进入内存/Redis 缓冲，随后落 PostgreSQL；Runtime 状态可由缓存投影覆盖 SQL。已有 `TimelineWriteBuffer.discard_session`、`SessionRuntimeStateCache.discard`。 | 删除必须处理未落库数据、Redis revision/cache、在途上传和延迟回放，复用现有 fence 与清理方法；不能只依赖数据库 CASCADE。文件与 SQL 无共同事务，失败/重启必须可重试，不能报告成功后遗留附件。 |
| D10 | §3.1 403、§3.2 幂等 | 现有项目删除将不存在与不属于当前用户都映射为 404。 | 按用户硬要求，本次删除接口对“存在但非本人所有”明确 403，缺失与重复删除选 404；限定在本功能，不顺手改整个站点的 404 所有权策略。 |
| D11 | §4.4 | 仓库 Runtime provider 名为 `claude`，不是 `claude_code`；存在多个同 provider 的命名实例 `runtimeId`。现有 `/admin/usage/*` 是平台活跃事件/报表，不是上游账号额度。 | 用量快照可继续使用需求的 `claude_code` 来源名，但 Connector 边界显式映射 `claude`；调度按账号和 Runtime 来源，实例仅作为采集位置，不能将 runtimeId 当账号去重键，也不能复用管理员报表作为剩余额度。 |
| D12 | §1.3、§5.2 | 现有 `SessionRunService._send_message_admitted` 接受 Runtime 状态 idle 或 error，传原 externalSessionId；普通失败未必强迫新建会话。`core/session_states.py` 允许 error 转其他状态，只有其独立 `can_send_session_message` helper 限 idle。 | 背景修订为“缺少可靠的限额等待、恢复时间与恢复协调”；P3 先验证现有失败后续发路径，避免重写已有恢复逻辑；统一涉及的实际发送门禁而不是只改一个 helper。 |
| D13 | §5.3 limited | 当前 SessionStatus 没有 limited。GoalStatus 已有 `usageLimited`，但它是目标状态，不能充当会话状态。Runtime 状态缓存可覆盖会话列表状态。 | P3 单独扩展会话限额事实和有效状态投影，协调 SQL、缓存、事件与读取；防止 Runtime 的旧 error/idle 覆盖 limited。Goal 自动续跑在限额时也须受约束，不因会话恢复就擅自恢复已暂停目标。 |
| D14 | §2 全端一致、§5.5 官方 iOS | iOS `V2RuntimeStatus` 将未知字符串解析为 unknown，并不原生认识 limited。只增加服务端状态不等于官方客户端可发消息。 | 到点恢复必须同时使列表、会话 Runtime 状态和发送准入回到官方客户端识别的可发送状态；按真实官方版本实测刷新、重新打开和发送。源码只证明未知值容错，不能替代官方安装包验收。 |
| D15 | §2 版本后缀、§7.5、§8 | 仓库规定跨端接口变更升 MINOR；用户要求以官方版本加分叉后缀，与此不同。Python 版本与 Electron SemVer 格式也不完全相同。 | 用户随后要求按官方规范融入新需求：P1 跨端接口升至 `2.3.0`，保持所有端 MINOR 一致，发布说明标明分叉，并写明各端最低配套版本、协议变化和迁移。打包前验证 Python/Node 接受该标识，不宣称仅加后缀就保证官方兼容。 |
| D16 | §8 自动更新 | Desktop 自有更新服务比较 Server `/health` 与构建记录，下载源在 `desktop-workbench/config.json`，当前指向官方 mac/windows latest。`update-version.ts` 比较时忽略 `+` 元数据。 | P1 交付前禁用官方安装包下载或改为用户分叉源；不能依赖 `+k1/+k2` 比较触发更新。无分叉下载地址时禁用下载、按成套安装交付，不虚构发布 URL。 |
| D17 | §7.5 | 当前只有 Linux 沙箱；尚无用户指定的生产/测试 Server、备份目标、Windows/macOS 构建机和 iOS 实机。 | 本地 headless 测试、安装包构建、真实安装验收、生产备份部署分别记录。未实测项不能勾选通过，也不能为满足表格声称 Linux 上已完成 macOS 安装/签名。 |
| D18 | 项目 MIT 描述 | README 声明 MIT；根目录没有独立 LICENSE 文件，仅发现旧 dsh-bridge 子目录的 LICENSE。 | 记录分发许可文本缺口，发布前核实上游版权与许可文本，不擅自用子目录声明替代全仓库版权声明；不影响本地核查，不顺手补造版权信息。 |

## 3. 已发现的凭据红线冲突（先报告，不改无关代码）

确证的是现有源码行为与本次红线冲突，并非证明用户凭据已经泄露。没有读取用户真实密钥，也没有调用相关 API。

1. `server/agent_server/api/model_config.py:create_model_profile` 接收含 apiKey 的 ManualProfileRequest，调用 Server service。
2. `server/agent_server/services/model_config.py:create_manual_profile` 把 request.apiKey 传入 discover_offers，由 Server 探测上游；并将 `box.seal(request.apiKey, ...)` 写入 `secret_ciphertext`。
3. 同文件 `profile_key` 可在 Server 解密该 Key；`services/model_channels.py` 获取 Key 并构造 Runtime 配置下发工作设备。
4. `contracts/runtime-control/2.1/README.md` 的模型连接本身声明 `{baseUrl, apiKey}`，说明这不是孤立测试代码。

因此，“加密保存”“UI 只显示首尾”不等于“Key 从未离开工作设备”。已在用户进度消息中报告；P0 不修改/停用这条现有链路，不调用它，不做生产迁移。本次三个功能不能复用这条链路传递 Codex/Claude 登录凭据。若用户要求**整套既有产品**也满足红线，模型渠道应另立明确范围的整改，当前不能声称全站合规。

本次源码检查尚未完成全链路日志泄密审计，没有凭据值可供生产日志/数据库检索；不能将“没看到值”写成“无泄漏验收通过”。后续测试使用临时 HOME、伪凭据与捕获传输/日志的负向断言；抽查日志仅报告命中位置和数量，绝不回显敏感值。

## 4. Server 状态机、API 与 Connector 恢复的施工依据

### 状态与所有权

- `core/models.py:SessionStatus`：idle、waiting、pending、running、stopping、waiting_approval、error、blocked。
- `core/session_states.py`：根据 active run、观察状态和审批推导状态；stopping 未 settle 时保留。error 可退出，非不可逆终结态。
- `services/session_states.py`：inspect/reconcile/transition，使用 expected_status 避免覆盖同时发生的状态变化。
- `services/session_meta_projection.py`：列表会合并 Connector presence 与 Runtime cache；新限额投影与删除判断要覆盖此路径。
- 项目归用户；会话通过 Connector 归用户，不能从调用者传来的 userId 判断权限。现有管理员身份也不自动等于其他用户对象所有者。

### API / 契约

- 所有产品 API 均在 `/api/v2`；Web 与 Desktop `apiPath()` 接收 `/projects`、`/sessions` 等资源路径，禁止重复拼接 namespace。
- API 字段沿用 camelCase，Python 路径参数 snake_case；错误按现有端点映射 HTTPException，结构化 detail 中使用稳定 `code` 与 `message`，状态冲突 409。
- 新删单会话拟用 `DELETE /api/v2/sessions/{session_id}`；项目沿用既有 DELETE。审计只记录操作者、UTC 时间、动作、对象 ID/数量与结果，不记录请求体或会话内容。
- 先更新 `docs/api/` 中的公开约定，再修改模型和实现；受生成器管理的 schema/TS 必须由源模型重新生成，不手改冻结的 `protocol/1.0`。新增错误码按 `contracts/runtime-errors/1.0/messages.json` 中英文与同步脚本执行。
- schema 迁移当前最大编号 v2_53；P1 如需抑制标记/清理状态表，从施工时最新编号递增，提供 downgrade，不修改已发布 revision。删除业务数据本身不可通过 downgrade 找回，升级前需备份。

### 原会话恢复

- Codex：`connector/connector/runtimes/codex/sdk/client.py:ensure_thread_resumed/_resume_thread` 在未加载时调用 thread/resume，验证返回的 thread ID 与原请求一致；已有加载线程复用。原生 writer 被占用时拒绝，不新建 thread 替代。
- Claude：`connector/connector/runtimes/claude/sdk/client.py:build_sdk_options` 将持久 external_session_id 写入 SDK `resume` 选项。
- Server：`services/session_run.py` 发送 `session.send_message` 时携带原 externalSessionId，创建和续发是不同路径；限额恢复只能走续发路径，原生绑定缺失必须显式失败，禁止回落 create-and-start。

## 5. 分期修订方案与验收门槛

### P1：删除（独立分支 `feat/be+fe+dsk/delete-projects-sessions`）

1. 契约写明 403/404/409、重复删除 404、项目级联删除与精确计数、忙会话列表；设计删除抑制与清理重试的最小持久状态。
2. Server 实现所有权校验、忙碌/在途准入隔离、子数据与文件清理、缓存清理、抑制重导入、审计和 dashboard 失效通知。项目计数包含已归档会话，不能只用当前页面的前 100 条。
3. Web 与 Desktop 两套 renderer 加危险色菜单；会话确认可取消，项目确认需显示总数并输入项目名或勾选二次确认；请求成功后即移除项目及子会话并处理当前路由；409 显示可定位的阻塞会话，不吞成泛化 false。
4. 回归：空项目、归档会话、全部忙碌态、所有权、重复请求、分页项目、附件/缩略图、Local/S3、并发发送/上传/ingest、Connector 重连重报、Redis 待写、文件失败重试、取消无请求、双 renderer 行为一致。
5. 更新分叉版本/变更日志/发布说明，禁用官方安装包覆盖路径，分别验证构建与协议；测试 Server 备份演练后部署，Win/Mac 安装、官方 iOS 列表刷新实测后才能完成 §3.4 全部验收。

### P2：用量（独立分支；本期不实施）

保留 §4.2 来源与 §4.3 所有硬要求。先 Codex 本机短生命周期 app-server 的 initialize、account/read、account/rateLimits/read，只读并按窗口时长归类；后 Claude 本机读取 OAuth，按指定 GET、beta 与本机版本 User-Agent 调用，只在 Connector 内存使用。不得读取账号凭据进行 P0 探针。

Server 按用户隔离后的 `(runtime, account_key)` 去重/调度，跨 Server worker 也只授予一台设备采集租约；首次发现账号需本机先派生不可逆标识，不能为“识别同账号”上传明文邮箱或 token。账号键必须来自稳定账号身份，不能哈希轮换的 accessToken；若 Claude 本机缺少稳定身份则显示不可用，不能猜测去重成功。

同账号 Claude 最短 5 分钟、Codex 1 分钟，手动刷新不越限；429/网络错误按 5→15→30 分钟退避，旧数据 stale，Web/Desktop 只读缓存。账号去重、账号切换后旧账号清除、设备离线/租约转移、时间戳乱序、结构变化、凭据负向测试均列入验收。§4.2 “已核实”在本项目中仍是待对实际 CLI/接口版本复核的输入，不提前声称兼容通过。

### P3：续聊（独立分支；本期不实施）

依赖 P2，先完成手动续聊。限额错误集中识别，区分短时请求 429 与账号额度耗尽，保守处理未知错误；命中多个仍阻塞的窗口时，不取较早重置时间虚假恢复。只恢复因限额阻塞的会话，不取消用户归档、停止、删除意图。

Server 到点回退需覆盖 Runtime cache 和事件投影；原 thread/session 身份持久保留；重查遵守 P2 间隔。P1 删除门禁中 limited 在无 active run 等忙碌事实时可删。官方 iOS 使用已发布客户端实测，不以仓库源码替代。

自动重试默认不实现（说明书明确可选），因此 P3 的“开启自动重试只重发一次”验收在首版记为不适用；若后续实现，需另测持久幂等、并发 worker、重启与用户停止取消，不能仅靠一个进程 timer。

## 6. 本期验收与未解决项

| P0 检查项 | 结果 |
| --- | --- |
| 读取原需求，确认 §2、§4.2、§4.3 硬约束 | 已完成，方案不弱化凭据纪律 |
| 核对最新 main 与 2.0.3 差异 | 已完成，固定 SHA、2.2.0 与架构差异见上 |
| 根目录约束、contracts、状态机、API、会话恢复核查 | 已完成源码核查，JSON 解析 188/188，manifest SHA-256 71/71；未运行框架级契约测试 |
| 差异逐条列出并先修订方案 | 已完成 D01–D18；文档是对原说明书的施工修订补充，原附件保持不变 |
| 发现既有凭据问题先报告、不顺手改 | 已报告模型渠道服务端接收/保存/转发 Key；未改该功能 |
| GitHub 远端 fork | 尚未配置所属账号/组织；目前仅本地克隆与 P0 文档分支 |
| §3.4 Web 删除后 Desktop / 官方 iOS 消失 | 未执行；P1 尚未开始 |
| §3.4 运行中会话拒删与提示 | 未执行；P1 尚未开始 |
| §3.4 项目、会话与附件级联清理 | 未执行；P1 尚未开始 |
| §3.4 无权限删除返回 403 | 未执行；P1 尚未开始 |
| §3.4 确认取消无数据变化 | 未执行；P1 尚未开始 |
| §4.6 用量、§5.5 续聊验收 | 未进入相应阶段 |
| 部署、生产备份、Win/Mac 安装包与官方 iOS 实测 | 未执行，环境未指定 |

主要未解决风险：模型渠道现有凭据流程与红线冲突；删除抑制标记需明确作为允许保留的最小元数据；并发准入/同步与跨存储失败恢复尚待 P1 实现证明；分叉后缀不参与现有更新比较；官方移动客户端降级需实机；远端 fork、跨平台打包及部署环境尚未落实。P0 收尾停在本笔记，不跨入 P1/P2/P3。
