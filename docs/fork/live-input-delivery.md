# 2.5.3 消息队列与盘符选择交付记录

## 范围

用户确认运行中的新消息先排在输入框上方，支持即时补充的 Agent 才可点击「立即补充」；补充 Windows 项目选择器无法返回盘符列表的问题。核查与修订方案见 [live-input-and-usage-plan.md](live-input-and-usage-plan.md)。用户随后确认用量已恢复、新会话最后有回复；不将响应慢当作已证实的卡死，不修改采集或推理设置。instabox1 离线问题按要求暂停。

## 文件与需求对应

| 文件 | 对应要求 |
| --- | --- |
| Web/Desktop renderer `src/components/session/use-session-message-queue.ts` | 当前客户端队列、本地持久化、服务器/用户/会话作用域、派发防重、失败保留、停止暂停和恢复后手动继续。 |
| 两端 `src/components/session/session-composer.tsx` | 输入框上方队列、Enter 入队、能力驱动的立即补充、独立停止按钮与审批派发门禁。 |
| 两端 `src/components/session-detail.tsx` | 复用 steer 或普通消息端点，稳定 clientMessageId、附件引用、补充不改变 running、拒收/失败保留消息；计划审阅时不自动派发。 |
| 两端 `src/features/dashboard/api.ts` | 客户端选用既有 `/runtime/steer`，不增加 Server 端点或请求字段。 |
| 两端 `src/components/workspace-file-browser-dialog.tsx` | 复用 breadcrumb 父目录逻辑保留盘符根，空 path 请求盘符列表，识别未知 deviceOs 的 Windows 返回路径，刷新不跳回用户目录。 |
| 两端 `messages/en.json`、`messages/zh-CN.json` | 队列、失败/未知结果、暂停恢复、立即补充及盘符列表文案。 |
| 两端 `test/session-command-ui.test.mjs`、`test/runtime-command-api.test.mjs`、`test/session-message-queue.test.mjs`、`test/workspace-file-browser-dialog.test.mjs` | 真实组件交互和队列恢复/附件/并发回归；C:/Users → C:/ → 盘符列表 → D:/。 |
| Desktop/renderer/Web package、Web demo | PATCH 2.5.3；Connector 仍 2.5.2，Server 仍 2.5.1。 |
| `.github/workflows/fork-desktop-build.yml` | 在 Windows/macOS 原生 CI 中增加上述 UI 交互检查，保留官方打包与哈希核验。 |
| CHANGELOG、2.5.3 发布说明、修订方案及本文 | 操作方式、兼容性和验收边界。 |

## 逐项验收

- [x] Web 相关交互/API/队列/路径测试 45/45，Desktop renderer 43/43，通过。
- [x] 两端类型检查通过；无新增服务端 API、数据库、冻结契约字段或依赖。
- [x] 运行中可反复 Enter 入队，原任务不中止；只有显式点击且 steer 能力可用时即时补充。
- [x] 不支持 steer 的 Agent 仍可排队，未显示立即补充按钮。
- [x] 当前任务结束后按 FIFO 派发；审批、计划审阅、离线、未接管时不自动派发，停止任务会暂停队列。
- [x] Strict Mode/双击只承认一个在途派发；发送失败与未知结果不自动重放，原条目保留；派发后本地清理失败不会永久卡在发送中。
- [x] 限额或运行错误后不自动派发，但保留用户明确点击的继续/重试入口，沿用原会话和 clientMessageId。
- [x] 按服务器、用户、会话的本地作用域隔离，重新打开恢复为暂停；保存失败保留输入草稿。
- [x] 已上传附件引用可恢复，不在本地队列中复制附件文件字节。
- [x] Windows 返回父目录不再生成 C: 相对路径，能进入盘符列表、刷新并切换 D 盘；正反斜杠与 UNC 路径回归通过。
- [x] 用空白临时 Codex Home 验证真实 SDK 只读 initialize/account/read 成功且无账号；没有探测真实厂商账号、请求额度或执行付费任务。
- [x] Windows 原生 CI：主进程 154 通过、12 跳过；本轮界面 40/40；安装包 SHA 与 PE 格式核验通过。
- [x] macOS 原生 CI：主进程 165 通过、1 跳过；本轮界面 40/40；安装包 SHA 与 DMG 格式核验通过。
- [ ] 用户 Windows/macOS 真机任务队列、真实 Codex 即时补充与其他盘实际权限：待用户验收。

## 未解决风险 / 部署边界

队列保存在当前客户端，不跨设备同步；本地存储被清除会丢失草稿。关闭期间不继续派发；恢复后手动继续。网络失败可能已被厂商接受，故保留未知条目并要求人工确认，不承诺跨网络 exactly-once。

本轮不优化厂商推理或网络延迟，不改变账户用量来源、采集门禁、原生授权或凭据存储；不迁移其他服务器、不开发 iOS。

Web 源码已同步，在线 Server/Web 2.5.1 本轮尚未部署；新的桌面安装包使用内置 2.5.3 界面，沿用既有 Server。官方程序与在线 Connector 均未停止。

## 安装包

构建源码提交 `4ea6501dfc665a353285299007f3e7ca437d7e51`；[原生 CI](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42607639996)。

[公开测试版下载](https://github.com/zzyyaa916/Agents-Anywhere/releases/tag/v2.5.3-fork)，无需登录 GitHub。Windows x64：`Agents.Anywhere.Fork.Setup.2.5.3.exe`，311195159 bytes，SHA256 `45f092cccbfe5a516592bd763eda6a25738145687253d509a56d45efeec4e5a0`。GitHub Release 的资产摘要与本地核验一致；公开文件名使用句点，清单也使用相同文件名。

macOS universal：`Agents.Anywhere.Fork-2.5.3-universal.dmg`，542821167 bytes，SHA256 `95547c8d9c9e58165d827c8bc29094cd81a394d35c147213e5e3fba1fb158edd`，下载文件与构建清单一致，DMG 尾部格式核验通过。Windows 跳过项为 POSIX 专用 fixture/权限测试及未安装 Electron 时的运行探针；macOS 跳过项为同一个 Electron 探针。原生打包成功不替代真机运行验收。安装包未签名，macOS 未公证。

## 首次响应慢的核查

用户反馈 Windows 新会话发送“你好”约一分钟以上才回复。静态核查发现消息 RPC 以独立任务并发调度（普通请求最多 8 个并发），用量采集使用独立处理器；未发现每条消息固定等待一分钟的逻辑。Codex 发起任务前仍需原生初始化、会话恢复与模型/权限目录等步骤，实际哪一步耗时未测得。没有访问用户 Windows 的阶段计时，也没有执行真实账号任务；此问题仍未定位，不能视为已修复。
