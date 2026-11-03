# 版本 B · 腾讯云 Cloud Studio（免费 T4 GPU）试用

> 三个版本的对比和怎么选见 [deploy/README.md](../README.md)。

**结论**：用腾讯云 Cloud Studio 的“免费高性能工作空间”（T4 16G）免费试用 LexAegis，边侧模型 **Qwen3.5-9B Q8_0**（约 10GB）跑在 GPU 上，浏览器通过 Cloud Studio 的预览地址直接打开工作台。只放合成材料。

> 状态：脚本流程已在无 GPU 的沙箱里验证（体检、预览地址拼接、以 Cloud Studio 预览域名访问时的登录和新建案件、其他域名被拒）。**没有在真实的 Cloud Studio 空间里跑过**：GPU 编译、模型速度、预览链接的实际行为都待实测，见文末。

## 1. 资源与限制（官方文档）

| 项 | 内容 |
| --- | --- |
| 规格 | 免费基础型：显存 16GB+、8 核 CPU、32GB 内存，一般为 T4（[购买指南](https://cloud.tencent.com/document/product/1039/33503)） |
| 免费时长 | 官方购买指南（2026-03-12 更新）写每月 1 日赠送 3600 分钟体验时长，每个空间每分钟扣 1 分钟；[简介页](https://cloud.tencent.cn/document/product/1039/94098)写每月 1 万分钟。两处不一致，**以控制台显示为准**，规划按较少的 3600 分钟（约 60 小时） |
| 关机策略 | 不操作 10 分钟自动关机；同一用户最多同时运行 2 台 |
| 存储 | 空间关机后存储保留，删除空间才释放；`/workspace` 里的模型、编译产物、Python 环境不用重装 |
| 预览地址 | `https://<空间标识>--<端口>.<区域>.<平台域名>`，服务要监听 `0.0.0.0`（[官方说明](https://cloud.tencent.com/document/product/1039/131818)） |

## 2. 步骤

1. **建空间**：Cloud Studio → 高性能工作空间 → 选标有“免费”的基础型。模板优先选带 CUDA 开发工具（`nvcc`）的；没有 `nvcc` 时 `check` 会告诉你。
2. **取代码**（终端里；仓库未合并到默认分支前加 `-b <分支>`）：

   ```bash
   git clone [-b <分支>] https://github.com/alanzhang66666/LexAegis.git && cd LexAegis
   ```

3. **体检**（不改任何东西）：

   ```bash
   bash deploy/cloudstudio/cloudstudio.sh check
   ```

   检查磁盘、GPU 与显存、CUDA 工具链是否和驱动匹配、`git` / `python3`、四个下载源是否可达、预览地址变量。有“不行”的项先解决。

4. **安装并测速**（首次约半小时以上）：

   ```bash
   bash deploy/cloudstudio/cloudstudio.sh setup
   ```

   编译 llama.cpp（CUDA）、下载 Qwen3.5-9B、准备 Python 3.12，再用 8 份短合成材料和 2000 / 6000 / 12000 字三份长材料按 worker 的真实调用方式（120 秒超时）测一遍，最后输出耗时表。`REQUIRE_GPU=1`：没有 GPU 或编不出 CUDA 版会直接报错，不会悄悄退回 CPU。

5. **启动**：

   ```bash
   bash deploy/cloudstudio/cloudstudio.sh start
   ```

   打印预览地址（`https://…--38765.….cloudstudio.club` 的形式）和登录口令文件位置，浏览器打开即可。登录用户 `admin`。
6. **用完**：在控制台点“停止”。关机后进程都会停，回来后重新运行第 5 步即可。

`PROFILE=demo` 可看项目内置的四条演示流程；`LLAMA_SERVER=/路径` 可使用自己准备好的 `llama-server`（官方 llama.cpp 不提供 Linux 的 CUDA 预编译包，第三方包请自行核对来源，本脚本不会替你下载）。

## 3. 为什么需要 `LEX_PUBLIC_ORIGIN`

工作台默认只接受本机地址（`127.0.0.1` / `localhost`），并校验写操作的 `Origin`。Cloud Studio 的预览地址是域名，不加配置会返回 `Invalid host header`。`start` 会把预览地址传给 `LEX_PUBLIC_ORIGIN`，工作台因此**额外接受这一个地址**（协议、主机、端口都要一致），其他 Host / Origin 仍被拒。不设置这个变量时行为和以前完全一致。

注意：

- 预览地址是公开可达的链接（知道地址的人都能看到登录页），工作台自己的口令登录仍然有效，但**只放合成材料**。
- Cloud Studio 预览链接是否另有腾讯云登录校验，我没有确认。

## 4. 验收

- [ ] `check` 没有“不行”的项
- [ ] `setup` 的耗时表里 Qwen3.5-9B 没有“超时/失败”，12000 字那一行也在 120 秒内
- [ ] `bench-*.json` 里 `quote_ok`、`numbers_ok` 都是 `true`
- [ ] 浏览器能打开预览地址并登录，新建案件、上传合成 Word 后出现自动抽取的候选事实
- [ ] 用完已在控制台停止空间

## 5. 已验证 / 未验证

已验证（无 GPU 沙箱）：

- `check`：GPU 缺失、磁盘、网络、预览变量缺失的报告；预览地址拼接（`production` 38765、`demo` 48765）
- `start`：把预览域名作为 Host / Origin 访问，首页、登录、新建案件都正常；其他域名返回 `Invalid host header`，其他来源返回“不允许跨站请求”
- 脚本通过 `bash -n` 和 shellcheck；`LEX_PUBLIC_ORIGIN` 有 15 个单元测试

未验证：

- 真实 Cloud Studio 空间里：`nvcc` 是否存在、CUDA 工具包与驱动是否匹配、llama.cpp 能否编出 CUDA 版、Qwen3.5-9B 的速度和抽取质量
- 预览链接经 Cloud Studio 的代理后，登录 Cookie、上传（含大文件）、事件流（SSE）是否正常
- 免费时长的真实数字，以及“不操作 10 分钟”对后台进程的具体判定
