# 版本 D · Apple Silicon Mac（MacBook Air M4，24GB / 512GB）

把 LexAegis 和边侧模型都跑在你自己的 Mac 上：数据不出本机，不租服务器，不需要隧道（浏览器就在本机）。只用于**合成材料**。

> 状态：脚本在模拟的 macOS 命令 + 桩模型下验证过完整流程，**没有在真实 Mac 上跑过**。下面的速度都是由内存带宽推算的上限估计，不是实测；请用 `bench` 自己量。

## 为什么原生运行，不用 Docker

Mac 上的 Docker 在 Linux 虚拟机里，**用不上 Metal GPU**，模型会退化成慢得多的 CPU 推理；也没法复刻 Linux 的 `isolate-api-route` 隔离。所以这个版本是原生运行（和 B、A 的 DSW 同类）：**没有隔离拓扑，不构成隔离收据**，`production` 环境下正式外发仍然失败关闭。

## 配置选择

| `MODEL=` | 模型 | 权重 | 占 24GB 比例 | 速度上限估计* | 建议 |
| --- | --- | --- | --- | --- | --- |
| `q4`（默认） | Qwen3.5-9B Q4_K_M | 约 5.7GB | 约 25% | 约 21 tok/s | 日常试用 |
| `q8` | Qwen3.5-9B Q8_0 | 约 9.5GB | 约 40% | 约 12 tok/s | 想要最好的抽取质量，能接受更慢 |
| `minicpm` | MiniCPM5-2B Q4_K_M（生产声明的模型） | 约 1.5GB | 约 6% | 更快 | 想和生产声明一致，或只测流程 |

\* 生成速度大致受限于内存带宽：M4 基础款约 120 GB/s，上限 ≈ 带宽 ÷ 权重大小。真实值更低；Air 无风扇，持续负载会降频。

经验规则：权重不超过统一内存的 60%，剩下留给系统、工作台和上下文缓存。24GB 下三种都放得下；`check` 会自动按这条规则报错。

边侧参数的默认值（`start` 里设置，已设置的环境变量不覆盖）：上下文 16384、每次调用超时 600 秒、每块材料 6000 字 / 6 段、单次最多输出 2048 token、最多 30 条事实。比 GPU 版保守，因为笔记本更慢；`bench` 之后再按结果调。

## 步骤

```bash
git clone <仓库地址> ~/LexAegis && cd ~/LexAegis      # 仓库未合并时加 -b <分支>；不要放在 桌面/文稿（可能被 iCloud 同步）
bash deploy/mac/mac.sh check       # 体检，不改任何东西
bash deploy/mac/mac.sh setup       # brew 装 llama.cpp / python@3.12 / node@22，建环境，构建前端，下载权重
bash deploy/mac/mac.sh bench       # 实测 1000 / 3000 / 6000 字的块各要多久
bash deploy/mac/mac.sh start       # 启动并打开浏览器，口令见 ~/lexaegis-work/workbench-password.txt
bash deploy/mac/mac.sh stop
```

- 换模型：`MODEL=q8 bash deploy/mac/mac.sh setup`，之后 `start`、`bench` 也带同样的 `MODEL=`。
- 看内置演示流程：`PROFILE=demo bash deploy/mac/mac.sh start`（演示案件不能重新抽取）。
- 下载慢：`HF_ENDPOINT=https://hf-mirror.com`、`PIP_INDEX_URL=...`、`NPM_REGISTRY=...`。
- 想改超时、分块等：直接在命令前加环境变量，例如 `LEX_EDGE_REQUEST_TIMEOUT=1200 bash deploy/mac/mac.sh start`。

## 笔记本使用注意

- **接电源**。跑模型很耗电，电池下降频更明显。
- **别合盖**。合盖会睡眠，进行中的抽取会中断（超时后需重新抽取）。`start` 用 `caffeinate` 防止空闲睡眠，但挡不住合盖。
- **无风扇会降频**。连续抽取一份长材料，后半段可能比 `bench` 的数字慢；`bench` 多跑几次看稳定值。
- **模型会闲置卸载**。默认 300 秒无请求卸载，之后第一次抽取要重新加载几十秒；用 `LEX_EDGE_IDLE_UNLOAD_SECONDS` 调整。
- 其他应用占用内存时（浏览器大量标签、虚拟机）先关掉，`q8` 尤其明显。

## 隐私与数据位置

- 数据库、上传的材料、日志都在 `~/lexaegis-work`（`WORK=` 可改）。开启 **FileVault**（`check` 会检查），否则这些以明文落盘。
- **不要**把仓库或 `WORK` 放在开了「桌面与文稿」同步的目录，也不要放进 iCloud Drive、Dropbox 之类同步盘。
- 只绑定 `127.0.0.1`，不设置 `LEX_PUBLIC_ORIGIN`；不要用内网穿透把它暴露出去。要远程访问请看版本 A / B。
- 只放合成材料。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `check` 提示不是原生 arm64 | 终端被设成了「使用 Rosetta 打开」：取消勾选，或换原生终端 |
| `8080` 被占用 | 关掉占用者，或 `LEX_EDGE_URL=http://127.0.0.1:<别的端口>/v1`（需和 llama-server 的端口一致） |
| 抽取超时 | 先看 `bench`；调大 `LEX_EDGE_REQUEST_TIMEOUT` 或调小 `LEX_EDGE_EXTRACT_CHUNK_CHARS` |
| 边侧启动失败 | 看 `lexaegis edge --start` 的输出；flash attention 不被支持时会自动关掉重试 |
| 想完全不用模型 | 不跑 `setup` 的下载步骤也行：工作台可人工录入事实，不依赖边侧 |

## 已验证 / 未验证

已验证（模拟环境）：脚本语法与 shellcheck；`check` / `setup`（真实的 pip 和前端构建）/ `start` / `bench` / `stop` 全流程；桩模型下 登录 → 新建案件 → 上传 → 抽取 → 出事实；`stop` 后进程和端口都清掉。

**未验证**：真实 Mac 上的 brew 安装与 `llama-server` 的 Metal 行为、真实 tok/s 和降频后的速度、Qwen3.5-9B 在 Q4_K_M 下的抽取质量、`enable_thinking=false` 是否生效、macOS 命令（`pmset`、`fdesetup`、`caffeinate`）的真实输出格式与脚本解析是否一致、权重文件名是否仍在 HuggingFace 仓库里（脚本下载前会校验并列出现有 gguf）。
