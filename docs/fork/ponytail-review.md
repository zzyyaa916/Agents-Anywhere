# Ponytail 精简与桌面交付范围

本轮按用户指定安装并使用 [ponytail skill](https://github.com/DietrichGebert/ponytail/blob/main/skills/ponytail/SKILL.md)，full 模式。安装位置为本机 `~/.codex/skills/ponytail`，不作为项目运行依赖，不复制第三方 skill 到产品代码。

## 当前交付范围

- 只交付 Windows x64 `.exe` 和 macOS universal `.dmg`（Apple Silicon / Intel），两者均包含既有删除、用量、续聊功能。
- 不开发 iOS 功能、不产出 iOS 包、不再以官方 iOS 实测作为交付阻塞；此前报告中的 iOS 待验项仅保留历史记录。此前 iOS 工程改动只有统一版本元数据，本轮没有 iOS 源码改动。
- Server / Connector 仍是桌面功能的必要配套。账号凭据本机使用、60/300 秒采集门禁、退避、账号隔离和原生会话 ID 校验继续执行。

## 改动与保留项

| 文件 | 精简结果 |
| --- | --- |
| `connector/connector/account_usage.py` | 复用一个限时本机命令读取函数；合并字段重命名和白名单，窗口也只允许已知字段通过；保留本机 KV 格式，升级不会清空已持久化的节流时间；移除不会被 Exception 捕获的 CancelledError 冗余分支。 |
| `server/agent_server/services/account_usage.py` | 统一采集与缓存展示使用的账号来源匹配规则；保留用户隔离，移除同样冗余的取消分支。 |
| `server/agent_server/infra/repositories/session_quota.py` | 用一个 UPDATE 同时更新 quota 和条件状态，保留原行锁、版本校验和会话序列更新。 |
| `connector/tests/test_account_usage.py` | 新增 RPC 凭据白名单、本机进程超时/取消回收、采集取消传播检查。 |
| `.github/workflows/fork-desktop-build.yml` | macOS 改 universal，Windows 保持 x64，沿用官方原生脚本；仅保留两个桌面构建任务，增加安装包存在/非空检查和 SHA256SUMS。 |

三处产品代码净减少 16 行；新增验证代码单独保留。没有为了缩行引入新依赖、改变 API 或 KV 格式，也没有减少安全校验、错误处理和既有业务功能。纯内部精简继续使用未发布的 2.5.0，不改变历史分期提交。

## 验证

- Connector：63 通过，含采集、限额、Host、Codex/Claude SDK；新增合成凭据和取消用例均通过。
- Server：36 通过，含账号去重/间隔/退避、限额状态/原 ID、历史删除和架构边界。
- Ruff 和 git diff --check 通过；无需因未改 UI 而重复完整 renderer 构建，上一期两套生产构建的结果仍见 P3 报告。
- 工作流 YAML 解析通过，目标恰好为 macOS universal / Windows x64；安装包检查逻辑在临时目录分别模拟两平台，验证缺失/空文件失败、有效文件生成正确 SHA-256。模拟文件不是真安装包，没有上传。
- 全程使用独立测试解释器与一次性测试库；未重启本机 Connector，未读取真实厂商凭据。

## 安装包仍缺的条件

当前只有 Linux VM；官方 `dist:mac` 强制要求 macOS，`dist:win` 强制要求 Windows。没有可用原生构建机，`gh auth status` 显示未登录 GitHub，也没有可调用的已连接 GitHub 工具，因此尚不能推送 fork 并执行托管构建。**本轮没有生成 `.exe` / `.dmg`，工作流验证不能等同于原生产物验收。**

获得原生构建机后，在各自系统的同一分叉提交运行：

```sh
cd desktop-workbench
corepack yarn install
corepack yarn dist:win --x64
```

macOS 将最后一行替换为：

```sh
corepack yarn dist:mac --universal
```

或者把分叉提交推送至用户自己的 GitHub fork，在 Actions 中运行 `Fork Desktop test installers`；产物从两个任务的 artifacts 下载，分别包含安装包与 SHA256SUMS。凭据应通过本机/平台自己的登录流程配置，不要在对话中发送 token、API key 或密码。

真实安装启动、真实账号额度一致性和实际上下文续接仍需 Windows/macOS 实机检查；iOS 不在本轮范围。
