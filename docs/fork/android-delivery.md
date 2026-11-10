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
- [ ] Android JVM 单测与 release 构建，产物签名/包身份/大小/SHA 核验：进行中。
- [ ] Android 真机安装、与官方版并排、真实登录/任务/文件权限/生命周期、额度实际打满与原上下文续聊：待用户验收。

## 未解决风险

Claude 的新数据源需升级 Connector >=2.5.4，旧 Connector 不会因手机更新而停止原先的采集；没有部署或重启任何在线服务。原生事件缺字段/账号缺身份时保守显示不可用，跨设备数据由既有 Server 去重，不能承诺闲置时实时或永不封号。

P0 报告过的现有模型渠道由 Server 接收/保存 Key 的风险仍在；本期没有扩展或修改该链路，新用量路径和测试不传出原生账号凭据。

## 安装与回退

Fork APK 与官方版包名不同，无需卸载官方版。卸载 Fork 仅移除其手机本地数据，不删除 Server 历史；删除项目/会话是服务端不可撤销操作，必须阅读确认弹窗。

安装包、构建提交、签名公钥指纹、SHA256 和下载链接待产物核验后补齐。
