# DSH Bridge 延迟删除与文本附件：ARM fork 部署记录

分支：`fix/dsh/history-delete-and-text-attachments`（基于 `chore/release-2.7.3`）。

## 背景

- DSH 会话一旦被加载，就在 DSH 进程重启前常驻内存。Bridge 原先一律拒绝删除这类会话，AA 中约 75% 的 DSH 会话删除失败。
- DSH Harness 0.2.1-rc.5 的文件上传在读完上传流后不返回，`.md` 等文本附件无法读取。

## 插件配置：`bridgeDirectory`

| 项 | 值 |
|---|---|
| 配置名 | `bridgeDirectory`（插件条目 `agents-anywhere-bridge-next`） |
| 现网值 | `/home/aa-fork/.agents-anywhere/dsh-bridge` |
| 配置位置 | `/home/aa-fork/.agents-anywhere-fork/native/dsh/profiles/web/cordis.patch.yml` |
| 不设时 | 操作系统用户主目录下 `.agents-anywhere/dsh-bridge`，与此前行为完全一致 |

**为什么要配**：ARM 上 DSH 以 `ai-dsh` 用户运行，Connector 以 `aa-fork` 用户运行。Connector 在 `aa-fork` 的家目录发布 `connector.json`、附件暂存与创建意图目录；`ai-dsh` 家目录下的默认路径 `/var/lib/ai-agents/dsh/.agents-anywhere/dsh-bridge` 是一个指向 `/home/ubuntu/.agents-anywhere/dsh-bridge` 的断开链接。

此前的 2.6.7 包（`dsh-bridge-next-2.6.7-794bde300.tgz`）是在构建后手工把 `bridgeDirectory()` 改成返回上述固定路径（与同 commit 重新构建逐文件比对确认，仅此一行）。该补丁只存在于部署包中，第一次部署本分支的未打补丁包时，Bridge 找不到 `connector.json`，与 Connector 断开约 90 秒后被验证脚本自动回滚。改为显式配置后，路径可审查，以后部署不会漏掉。`ai-dsh` 对该目录的访问由 `/usr/local/libexec/aa-fork-bridge-acl`（`agents-anywhere-fork.service` 的 `ExecStartPost`）授予。

## 状态文件

以下文件写入 Bridge 配置的状态目录 `stateRoot(config)`；ARM 未配置 `stateRoot`，即 `/var/lib/ai-agents/dsh/.agents-anywhere/dsh-bridge-next/`：

- `pending-deletions.json`：已在 AA 删除、但 DSH 仍加载着的会话；DSH 下次启动时清除其原生文件。
- `activity.json`：每 30 秒及状态变化时写入 `pid`、`updatedAt`、运行中会话，供定时重启判断是否空闲。

## 定时重启

- `aa-fork-dsh-restart.timer`：每天北京时间 04:00（`OnCalendar=*-*-* 04:00:00 Asia/Shanghai`）。
- `/usr/local/sbin/aa-fork-dsh-restart`：读取上面的 `activity.json`；有任务运行，或无法确认空闲（无心跳、心跳超过 2 分钟、PID 与服务 MainPID 不符）时跳过，每 5 分钟重试，到 05:00 仍不空闲则当天不重启。记录见 `journalctl -t aa-fork-dsh-restart`。

## 部署步骤

1. 发布包放入 `/opt/agents-anywhere-fork-connector/releases/`（root，0644）。
2. 备份到 `/opt/agents-anywhere-fork-connector/backups/dsh-deferred-delete-<时间戳>/`：`profiles/web` 的 `package.json`、`pnpm-lock.yaml`、`cordis.patch.yml` 与现有插件目录。
3. 以 `ai-dsh` 身份解包替换 `node_modules/@agents-anywhere/dsh-bridge-next`，更新 `package.json` / `pnpm-lock.yaml` 中的包路径与校验值，在 `cordis.patch.yml` 追加 `bridgeDirectory` 一项。
4. 重启 `agents-anywhere-fork-dsh.service` 并验证；任一项失败即从备份恢复并再次重启。

回滚：从第 2 步备份恢复四项后重启服务。

## 部署结果

2026-11-23，ARM（tokyo-arm-01）。

- 包：`dsh-bridge-next-2.7.3-f6f7eabff.tgz`，sha256 `7e0bcc366b367a0d669c794b5a721d1c71ab8dc68ab2367d72dae29443b5c57f`。
- 备份：`/opt/agents-anywhere-fork-connector/backups/dsh-deferred-delete-20261123T024445Z/`（`package.json`、`pnpm-lock.yaml`、`cordis.patch.yml`、2.6.7 插件目录、旧定时重启脚本）。
- `cordis.patch.yml` 仅在末尾追加 `agents-anywhere-bridge-next` 条目的 `bridgeDirectory` 一项。
- 02:44:46 UTC 重启后验证通过：服务 active（MainPID 562834）；插件 2.7.3 且含 `bridgeDirectory` 配置代码；`activity.json` 写入状态目录，1 秒内、pid 与 MainPID 一致；DSH 进程持有一条对端为 Connector Router socket 的连接；断开链接目录未被写入。
- 当场删除：冷会话删除立即完成；02:51 删除一个已加载且空闲的会话，面板立即消失、无报错，`pending-deletions.json` 写入状态目录（`ai-dsh`，0600）并记录该会话，原生目录按设计保留到下次 DSH 启动。

### 曾出现的问题

1. 首次部署（02:13）使用未打路径补丁的包，Bridge 找不到 `connector.json`，验证失败后自动回滚，与 Connector 断开约 90 秒。由此新增 `bridgeDirectory` 配置。
2. 第二次部署预检用 `runuser -u ai-dsh -- test -r` 判断可读性，在该环境下与实际读取结果不符（ACL 授权正确、实际读取成功），预检中止且未做任何改动；改为以 `ai-dsh` 实际读取首字节后部署成功。
