# Mac Intel 安装包交付记录

用户确认仅需 Intel Mac，不再交付 Apple 芯片版本。保留版本 2.5.3，这是同一版本新增的 x64 发行产物，不改变客户端功能或接口。

## 修改范围

| 文件 | 变更 |
| --- | --- |
| `.github/workflows/fork-desktop-build.yml` | Mac 构建架构从 universal 改为 x64，产物名为 fork-test-mac-x64。 |
| `desktop-workbench/package.json` | 默认 Mac 打包目标为 x64。 |
| `desktop-workbench/scripts/dist-desktop.mjs` | 默认 dist:mac 只准备 darwin-x64 的 uv/Python 并打包 Intel Electron；保留上游显式架构参数以便合并官方更新。 |
| `desktop-workbench/scripts/cache-native-dependencies.mjs` | Fork CI 只缓存 Intel Mac 的 Electron、uv、Python 资源；打包工具仍匹配构建机器架构。 |
| CHANGELOG 与 2.5.3 发布说明 | 说明 Mac 发行包改为 Intel。 |

## 验收

- [x] 两个修改过的打包脚本语法检查通过。
- [x] 直接调用实际目标选择函数，确认 Mac 默认只选择 darwin-x64；Windows 默认仍为 win32-x64。
- [x] package.json 默认 Mac 架构为 x64，diff 格式检查通过；无运行时功能、登录、数据库或凭据改动。
- [x] Mac 原生 CI：165 项主进程测试通过、1 项 Electron 未安装探针跳过，界面测试 40/40；构建日志确认 Electron arch=x64、uv/Python targets=darwin-x64。
- [x] 下载 SHA256 与构建清单一致，DMG 尾部格式校验通过。
- [x] Intel 包发布到原有公开发布页，替换通用包；Windows 安装包保持原文件。
- [ ] Intel Mac 真机安装和任务测试待用户验收。

构建源码：`d814f50fd9f127024f8239e35396a8eba5e6e7c1`；[原生构建](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42610578885)。Windows 沿用前次发布的 2.5.3 安装包。

安装包未签名、未公证；没有删除登录/隔离逻辑或本机执行依赖来减小体积。源码中保留官方显式 arm64/universal 构建能力，但 Fork 默认和 CI 均不使用、不交付这些架构。

## 下载与体积

[Intel Mac 安装包](https://github.com/zzyyaa916/Agents-Anywhere/releases/download/v2.5.3-fork/Agents.Anywhere.Fork-2.5.3-x64.dmg)，414850066 bytes（395.63 MiB），SHA256 `98ebdf52e4eac29483d3501bb442fcb9157134fcb846277272700904d62e3c3b`。此前 universal 为 542821167 bytes（517.67 MiB），减少 127971101 bytes，约 23.6%。

此次只移除双架构交付开销，未进行更广的依赖瘦身；没有承诺体积减半。
