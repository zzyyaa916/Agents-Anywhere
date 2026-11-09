# 官方版与改动版隔离部署

改动版使用固定 Compose 项目名 `agents-anywhere-fork`，与官方 `agents-anywhere` 分开。独立镜像、网络、PostgreSQL、Redis、附件卷和认证密钥；宿主只绑定 `127.0.0.1:18500`，由独立 HTTPS 站点代理。Compose 中包含资源上限，降低同机运行时的资源争用；宿主系统与磁盘仍然共享，不能等同于独立服务器的故障隔离。

部署时使用干净提交导出的源码与独立生成的静态 Web，不包含 `.env`、本机日志、浏览器缓存或厂商凭据。正式实例不导入演示项目与 12% 用量数据；未连接工作设备时应显示「用量不可用」。先迁移改动版空数据库，再初始化管理员并关闭邮箱及 OAuth 公开注册，最后启动 Server、开放 HTTPS。禁止迁移或写入官方数据库。

## 配置与操作

本次服务器上的目录为 `/opt/agents-anywhere-fork`：`compose.yml`、`fork.env`（0600）、`release/`、`backups/`。`fork.env` 中的 `FORK_IMAGE` 指向本次独立镜像；`FORK_DB_PASSWORD`、`FORK_AUTH_SECRET` 在服务器本机随机生成，不使用官方值。`FORK_PUBLIC_ORIGIN` 为独立 HTTPS 入口。

一键停用（保留数据）：

```sh
bash /opt/agents-anywhere-fork/disable-fork.sh
```

查看状态：

```sh
cd /opt/agents-anywhere-fork
docker compose --env-file fork.env -f compose.yml ps
```

发现问题后先停用改动版，保留数据：

```sh
cd /opt/agents-anywhere-fork
docker compose --env-file fork.env -f compose.yml down
```

此命令只停止改动版项目，不带 `--volumes`，保留改动版数据库与附件卷；官方版继续从原地址使用，无须数据库降级。停用后还应移除改动版专属 Nginx 配置并先 `nginx -t`、再 reload，保留官方站点配置。

彻底删除改动版数据前应先导出数据库和备份附件；`down --volumes` 会永久删除改动版卷，因此不作为默认回退命令。禁止运行全局 `docker system prune`、删除官方卷或覆盖官方镜像标签。

## 管理员与工作设备

管理员账号仅在服务器本机初始化；如复用官方管理员登录，仅在同一服务器内复制该管理员的密码哈希，不能将哈希输出到 SSH、日志或交付包，不同步普通用户、会话和厂商凭据。两版后续密码修改互不联动。所有厂商登录仍在工作设备本机完成。

Connector 按操作系统用户设置单实例锁；只换配置目录仍会冲突。两版并行使用必须采用不同系统用户、容器或虚拟机，并隔离 Connector 配置、状态及工作区。不要接管、停止或改写正在连接官方版的 Connector。若使用相同厂商账号，其额度仍共享，部署隔离不会增加额度。

改动版新建的会话不会自动出现在官方版；停用改动版后，也不能靠官方旧程序打开改动版数据库。正式用量及原会话续聊需使用配套分叉 Connector 实机验收，Windows/macOS 原生安装包仍须独立构建。

## 上游代码中需留意的既有行为

`server/agent_server/app.py` 的空库首次启动路径会生成并记录一次性管理员初始化令牌。本次不修改该实现，使用公开服务启动前在服务器本机初始化管理员的部署顺序，避开空库令牌日志路径。
