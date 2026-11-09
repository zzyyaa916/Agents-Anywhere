# 圆形用量入口调整

本次按用户最新要求覆盖说明书 §4.5 的「常驻展示每个账号窗口」：常驻入口改为侧栏底部账号旁的 36px 圆形按钮，点击后才展开详情。§4.1 的剩余百分比、本地时区重置时间，§4.5 的会话提醒，以及 §2、§4.2、§4.3 的凭据边界、数据来源和采集纪律均不变。只修改 Web / Desktop；不开发 iOS。

## 修改文件

| 文件 | 对应要求 |
| --- | --- |
| `web-next/src/components/account-usage.tsx`、`desktop-workbench/renderer/src/components/account-usage.tsx` | §4.5 最新修订：复用现有 Popover 和圆形按钮，按需展开原有双端账号窗口、进度条、重置时间、过期标记与刷新入口。 |
| 两端 `src/components/sidebar/sidebar-account-footer.tsx` | §4.5 最新修订：用量入口与账号并排，不再常驻大面板；侧栏收窄时纵向排列。保留 Desktop 更新按钮。 |
| 两端 `test/account-usage.test.mjs` | 验证默认折叠、点击展开、展开只读缓存、刷新失败保留旧值及过期标记、Esc 收起、再次展开和会话实例提醒隔离。 |
| `CHANGELOG.md` | 用户可见行为同步更新。 |

## 验收结果

- [x] 默认只显示圆形入口，点击才展开 Codex / Claude Code 详情。
- [x] 保留窗口剩余百分比、重置时间、更新与过期提示、手动刷新。
- [x] Esc 和点击外部关闭；真实 Chromium 浏览器检查通过，390px 窄屏弹出层未越出视口。
- [x] Web 475 项、Desktop renderer 477 项测试通过，两端类型与协议检查通过。
- [x] Web 独立生产构建通过，已更新既有测试网页；公网登录页 HTTP 200，注册仍关闭。
- [x] 仅切换测试 Web 进程；未重启 Server、Connector 或官方自建服务器。

## 未解决的风险与范围

测试站 12% 等数字仍为演示数据，不代表真实厂商额度。说明书 §4.6 中与 Codex 官方用量页、Claude `/usage` 的实机对照，以及三台真实设备账号聚合验收仍待完成。本次没有改动采集器、Server、API 或数据库结构，不重复此前后端回归，也没有读取真实厂商凭据。

Windows / macOS 安装包尚未生成；本次 Desktop 改动已完成 renderer 检查，原生安装实测仍需相应构建环境。截图、测试站配置、日志和浏览器检查脚本仅保留本机，不进提交。
