# Claude 手动用量探针（唯一现行规则）

本说明替代本轮此前的自动探针方案。没有后台探针、随机调度、活动计时、打开面板探测或撞限额探测。线上部署仍暂停，代码未配置真实节点时所有探针默认禁用。

## 双源与时间

Connector 在原生 rate_limit_event / rate_limits_event 流中捕获标准化窗口后，通过 `accountUsage.event` 向 Server 推送事件数据；这不发起额外 Claude 请求。手动探针走独立 `accountUsage.probe` RPC。两路只接受 five_hour、seven_day。

Server 给每次有效接收盖时间戳，按账号、窗口分别保存 event / probe 两份最后有效数据。窗口独立选择 Server 接收时间较新的一份，在 API 中保留 event / probe 标记并返回 receivedAt 与 ageSeconds。缓存不按重置时间或年龄清空；空窗口、失败与部分更新都不能覆盖其他有效窗口。同一路较晚完成的旧写入也不能覆盖其较新接收记录。

旧缓存没有可信的 Server 接收时间时保留原值，显示“旧缓存 · 接收时间未知”，不借用设备 fetchedAt 伪造时间。新数据的观察时间一律由 Server 生成，reset_at 仍是厂商报告的重置时间。客户端只使用 Server 时间与本地单调计时的经过时长更新年龄，不用设备墙上时间比较新旧。

## 纯手动触发与单飞

打开面板只 GET 缓存。只有 Web、Windows 桌面、Android 用量视图的刷新按钮 POST `/api/v2/account-usage/refresh`，Server 才能给指定甲骨文 ARM 下发一次探针。该节点离线直接提示“探针节点离线”，不切换到其他节点。

Server 使用一条持久化全局控制记录和数据库行锁进行单飞，重复点击等待同一次在途任务，跨 worker 也不能多发 RPC。发起客户端取消或断开不会取消已发出的探针，后续点击仍等待它。进程重启遗留的在途租约超时只转入失败/退避，绝不自动补发。

两次成功探针至少间隔 300 秒。间隔内点击直接返回现有数据和原年龄，不发真实请求，也不把年龄重置为零。

## 失败与熔断

所有探针失败只改变刷新控制记录，任何已缓存窗口的数值、来源、接收时间均保持原样。

- 429 有合法 Retry-After 时优先采用：支持秒数和 HTTP-date，后者由 Server 时间解释。不会将原始头或响应正文写入缓存或日志。
- 没有有效 Retry-After 时，退避间隔翻倍：5 → 10 → 20 分钟……。超时、离线等失败也用同一退避规则。
- 429 计数仅在成功得到有效窗口后清零，其他失败不增加次数。第三次 429 触发熔断至次日 00:00 UTC；若 Retry-After 要求等待更久，仍遵守更晚期限。
- 熔断期间显示“今日探针已熔断，明日恢复”，按钮保持置灰，并展示可重试时间。熔断解除时计数清零、最小间隔恢复 5 分钟，但不会自动发请求。

界面正常按钮显示“刷新”，请求中显示加载态；失败显示“稍后重试”与重试时间。每个 Claude 账号底部只显示一行最新接收数据的本地时间与来源：“时间 更新 · 探针”或“时间 更新 · 缓存”（event 显示为缓存）。窗口仍分别使用最后有效数据。退避期间点击不会发请求，旧百分比仍显示。来源标记表示数据原始来源，探针结果经过缓存分发后仍标记“探针”，不是本次是否读取缓存的标记。

## 单节点与凭据

仅甲骨文 ARM Connector 配置以下非秘密变量；同时核对实际 Connector ID、Linux ARM 平台及 machine-id 的 SHA256：

```ini
AA_CLAUDE_USAGE_PROBE_CONNECTOR_ID=<甲骨文Connector ID>
AA_CLAUDE_USAGE_PROBE_MACHINE_ID=<去除换行的/etc/machine-id内容的SHA256>
```

Server 只配置相同的 `AA_CLAUDE_USAGE_PROBE_CONNECTOR_ID`，作为指令路由，不持有任何 Claude OAuth 文件或令牌。其他节点不配置这些变量，即使复制环境到不同机器也不能启用。

固定身份代理的 root 配置还需要合并以下字段，不能覆盖原有 roles：

```json
{"claudeUsageProbe":{"enabled":true,"connectorId":"<同一ID>","machineId":"<同一SHA256>"}}
```

助手由现有代理降权至 Claude 身份后运行，在 Linux 默认读取 `~/.claude/.credentials.json`；若原生 Claude 设置了 `CLAUDE_CONFIG_DIR`，只读取同一活动配置目录，绝不回退到其他账号。当前 Fork 固定身份使用独立的 native/claude 目录。Connector 不获得读取凭据文件的权限。令牌只留在助手进程内用于固定 Anthropic HTTPS Authorization 头，不进入参数、日志、KV、Server 或仓库，也不自动刷新或写回 OAuth 文件。

请求固定 `GET https://api.anthropic.com/api/oauth/usage`，带 `anthropic-beta: oauth-2025-04-20`。User-Agent 从该节点实际 Claude 命令的 `--version` 动态得到；没有版本号硬编码。禁止跳转及环境代理，保留系统 TLS 验证。助手成功只返回两个窗口的百分比和 resets_at，获取/接收时间由 Server 在收到结果时记录；失败只返回有限错误码和规范化 Retry-After 提示，不返回原始响应。

## 兼容与部署边界

需要配套更新 Server、Connector 和三个客户端，Server 数据库需迁移至 v2_59。只构建源码不会启用探针；升级脚本包含助手但不自动配置任何节点。历史配对、OAuth 登录和项目目录不改动。iOS 尚无该用量面板，本轮不新增入口。

长期缓存不能被当作新鲜的限额恢复依据：Claude 的“检查限额”只看已有缓存，且所有参与判断的窗口必须在本轮限额后被 Server 新接收，不能由另一窗口的更新使旧窗口变“新鲜”。
