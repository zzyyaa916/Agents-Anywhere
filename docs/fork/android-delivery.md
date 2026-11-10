# Android Fork 2.5.4 交付报告

现状核查和与原说明书的差异见 [实施方案](android-audit-and-plan.md)。用户本次明确扩展到 Android；iOS 未开发。原说明书 §4.2 的 Claude 私有接口已由用户后续要求替换为被动原生事件，凭据与采集纪律不弱化。

## 文件与需求对应

| 文件组 | 对应需求 |
| --- | --- |
| Android ForkApi、ForkController、ForkPanels、Home/Archived 屏幕和菜单 | §3 删除、精确计数与确认、§4 圆形用量展示与缓存读取 |
| Android SessionDetailScreen、SessionMessageQueue、SessionQueuePanel、SessionsApi、SessionDetailController、状态映射 | §5 原会话续聊，以及后续消息排队/显式 steer/附件/暂停/失败保留 |
| Android AppUpdates、AppConfig、Manifest、Gradle、双语资源 | Fork 独立包名/名称/数据与回调隔离、默认自托管、避免官方包覆盖、版本与更新 |
| Connector account_usage、runtime host、Claude SDK connection/events/lifecycle、测试与 host 内部扩展 | Claude 原生事件被动采集、稳定账号绑定、本机缓存、停用私有接口和凭据读取 |
| account-usage 契约 README、来源说明、发布说明、CHANGELOG、Android README | 来源修订、兼容与验收边界；未修改 wire schema、Server API 或数据库 |
| GitHub Android workflow | 隔离 runner 使用 JDK17/SDK36 做 JVM 测试和未签名 release 构建；签名在本机完成 |

## 验收清单

- [x] Connector 相关用量、原生事件、SDK/Claude 完整回合、Host、限额错误与架构回归 194 项通过，仅虚构身份/事件，不读取真实厂商凭据。
- [x] 本地稳定 APK 签名身份已建立，私钥/密码不入 Git、CI 或日志。
- [x] Android JVM 单测 172 项通过（28 个 suite，0 failed/error/skipped），release 构建成功；APK 签名、包身份、大小、SHA 与 16 KB ZIP 对齐检查通过。
- [ ] Android 真机安装、与官方版并排、真实登录/任务/文件权限/生命周期、额度实际打满与原上下文续聊：待用户验收。

## 原说明书逐条验收（本次 Android 增量）

自动化验证与真机/生产验收分别记录，未将模拟通过视为实际账号验收。

| 条款 | 本期结果 |
| --- | --- |
| §3.4 删除后跨端消失 | 使用同一服务端 DELETE，成功即移除手机条目；Web/Desktop 跨端实际刷新待用户验收，iOS 不在本期 |
| §3.4 运行中禁止删除 | API 测试验证 409 与 blockingSessionIds；真机提示待验 |
| §3.4 项目级联记录/附件清理 | 复用既有服务端实现，客户端传 expectedSessionCount；本期未在在线库执行破坏性验证 |
| §3.4 无权限返回 403 | 保留 HTTP 状态、显示固定错误；真实低权限账号未测试 |
| §3.4 确认与取消 | 项目必须输入准确名称，计数改变要求再次确认；取消不调用删除；真机点击待验 |
| §4.6 Codex 5 小时/周口径 | 保留 Codex 官方 app-server 只读采集，手机只展示缓存；同机数字比较待用户验收 |
| §4.6 Claude 5 小时/7 天口径 | 已按后续要求改为原生被动事件，模拟窗口/比例/缓存测试通过；真实事件与 /usage 对照未做 |
| §4.6 同账号三机去重 | 复用 Server 按 runtime/accountKey 聚合，Android 不另存/合并身份；三机实测未做 |
| §4.6 断网/429/过期 | Connector 回归覆盖退避、旧缓存、过期；Android 不把过期额度补成 100%，手机断网实测待验 |
| §4.6 凭据纪律 | 新增链路只传白名单数值与账号哈希；测试不使用真实凭据；未扫描在线数据库/生产日志（下述既有风险仍在） |
| §4.5 会话低额度提醒 | 新鲜且匹配 runtime 的 5 小时窗口 <=20% 显示提醒，0% 为错误色；过期/不匹配窗口不提醒，独立单测覆盖 |
| §5.5 Codex 限额等待及恢复时间 | 接入原 session 的 quota/read/recheck 与 limited 样式；模拟状态测试，真实打满未做 |
| §5.5 原会话/原上下文恢复 | 沿用原 sessionId，不创建替代会话；实际任务进度恢复待验 |
| §5.5 Claude 同样恢复 | 复用既有限额识别与原生 resume，相关 Connector 回归通过；真实限额恢复待验 |
| §5.5 iOS 降级路径 | 按用户要求不开发 iOS，本期未实测 |
| §5.5 普通错误不误判 | 现有限额错误回归通过；客户端只按明确 quota 状态展示等待 |
| §5.5 自动重试只一次 | 可选项未启用：额度到点只重新读取状态，由用户主动发送；消息 FIFO 不是限额自动重试 |
| 后续消息队列/即时补充 | 上传引用与稳定 ID 持久化、FIFO、失败暂停、重启不自动回放、账号隔离均有单测；仅 capability 允许才提供 steer，真机端到端待验 |
| 后续并排安装/管理员注册 | 独立 applicationId 与签名、不抢官方外部回调；登录走既有 Fork Server，无原生公开注册入口；并排真机待验 |

## 未解决风险

Claude 的新数据源需升级 Connector >=2.5.4，旧 Connector 不会因手机更新而停止原先的采集；没有部署或重启任何在线服务。原生事件缺字段/账号缺身份时保守显示不可用，跨设备数据由既有 Server 去重，不能承诺闲置时实时或永不封号。

P0 报告过的现有模型渠道由 Server 接收/保存 Key 的风险仍在；本期没有扩展或修改该链路，新用量路径和测试不传出原生账号凭据。

## 安装与回退

Fork APK 与官方版包名不同，无需卸载官方版。卸载 Fork 仅移除其手机本地数据，不删除 Server 历史；删除项目/会话是服务端不可撤销操作，必须阅读确认弹窗。

### 已核验产物

- [下载 APK](https://github.com/zzyyaa916/Agents-Anywhere/releases/download/v2.5.4-fork/Agents.Anywhere.Fork.apk)：43,347,656 bytes（43.35 MB / 41.34 MiB），Android 8.0+，`com.agentsanywhere.fork`，2.5.4 / versionCode 15；arm64-v8a、armeabi-v7a、x86、x86_64 通用包。
- [配套 Connector wheel](https://github.com/zzyyaa916/Agents-Anywhere/releases/download/v2.5.4-fork/anywhere_cli-2.5.4-py3-none-any.whl)：需在工作设备的 **Fork 独立用户/虚拟环境**升级；不安装在手机，不覆盖官方版环境。升级时保留原 Fork 的配置目录和 systemd 服务参数，只重启对应 Fork 服务。首次原生登录仍由用户本机完成。
- [校验文件](https://github.com/zzyyaa916/Agents-Anywhere/releases/download/v2.5.4-fork/SHA256SUMS)；[发布页](https://github.com/zzyyaa916/Agents-Anywhere/releases/tag/v2.5.4-fork)。
- 构建源码：`3e5f35b617a402b78b5caa4f54262e2cccb452df`；[成功 CI](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42745697738)。
- APK SHA256：`c813bfdc2b299b1ace015029fe7c46628e16a6c7a429484cddfa9c2fdbe0ffcc`。
- wheel SHA256：`7c57102555ed2a3d99e46c043babc9b5f1390fab8c322ea2d4267e61f5f4cd03`。
- 签名证书 SHA256：`c00c791a47f49dc71e5b0c91fb81cff4f8ffd377b48f37323301bf6e55147919`；RSA 3072，v2/v3 验签成功。签名私钥和密码只在本机受限目录保留供后续升级，不上传 GitHub/CI。
- 解包检查：release 非 debuggable；未声明官方外部 OAuth scheme，登录 WebView 内部处理回调；28 个原生库中未压缩项保持 16 KB 对齐。未做 ELF/硬件 16 KB 页兼容实机测试。

手机上下载 APK 后按系统提示允许当前下载来源安装，登录已有 Fork 管理员/管理员分配账号。默认站点为 `https://81.71.71.114:9443`，不是官方 443 站点；两边账号和数据独立。默认站点 TLS 标准验证已通过，但真实手机登录仍需验收。

工作设备升级应先停止对应 Fork 服务并备份其专用配置，再用该服务实际 Python/虚拟环境安装 wheel（与 wheel 同路径的 SHA256SUMS 校验一致），只启动该 Fork 服务。由于各设备安装路径不同，本期没有盲目执行通用升级命令或修改在线服务；要切换 Claude 新来源，必须逐台升级所用 Fork Connector。

