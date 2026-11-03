# 登记合成文档的云边联调部署

这是默认关闭的 integration 能力。原件、抽取、身份映射和回链留在边侧；独立网关沿用项目的签名、请求核验和发送账本。它不放宽 production 门禁，不发布规则包，不构成真实法学签署。

## 安装与配置

在独立检出目录安装锁定依赖，再构建前端：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock -r requirements-test.lock -c constraints/windows.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
```

将 registered-manifest.example.json 复制到仓库外的私有文件，填写已确认的**合成文档**名称、文件 SHA-256 和人工核对的允许事实列表。事实条目格式是 `[字段, 原文值]`；字段沿用 entity、relation、event、date、amount、evidence。空模板会拒绝启动，不能当作已有材料授权。不要把填好的清单或原文加入 Git。

```powershell
.\.venv\Scripts\python.exe deploy/workbench_demo/control.py init --manifest '<私有清单路径>'
.\.venv\Scripts\python.exe deploy/workbench_demo/control.py build
.\.venv\Scripts\python.exe deploy/workbench_demo/control.py start
```

默认运行目录为本检出的 `.data/workbench-demo`，默认回环端口为 58765。`--runtime-root` 可选择其他**空私有目录**；所有后续命令须传相同路径。实例名由运行目录推导，卷和容器需通过归属标签检查。不会接管另一个实例的端口、进程或持久卷。

本地模型不随源码发布。在 init 时用 `--model-assets '<ASSETS.json路径>'` 显式指定已准备的 Windows llama.cpp/MiniCPM 资产清单；启动器核对模型、归档和二进制哈希，只继承必要的系统/CUDA 环境，按 PID、创建时间和程序路径管理进程。模型固定回环 18080，8K 上下文、batch 512、ubatch 128、并发 1，关闭 OCR/语音。不配置模型时不宣称实时抽取可用。Docker Desktop 模型宿主地址默认 192.168.65.254，可在 init 用 `--model-host-ip` 指定私有 IPv4；连接器仅允许该主机的 18080 端口，移除 IPv4/IPv6 默认路由。

## 真实云调用默认关闭

默认额度为 0，不配置服务商密钥；网关按原项目允许的**无密钥 edge 角色**运行，所有云发送被拒绝。不会用假密钥绕过 cloud 角色的启动检查。

确需真实联调时，应为**已单独明确授权**的实例在 init 时设置 `--cloud-limit <授权上限>`，必要时设置 `--initial-consumed <既有占用>`。随后在运行目录的 `private/gateway.env` 填写 `LEX_CLOUD_PRIMARY_KEY` 并显式确认使用；网关按 cloud 角色启动。凭据不进入 Compose 环境、前端、模型、镜像、命令行或日志。先配置私有文件，再首次 start。

上限写入持久额度账本后不可通过重复 init 或改文件增加。已运行的实例迁移必须保留其发送账本、全局额度、结果不明和一次性许可消费记录；新建目录不产生额外调用授权。本分支不导入本机既有私有账本，也不自动修改其余额。

请求使用 deepseek-flash、JSON 输出、thinking disabled；以冻结批准的具体模型、目标和正文为准。主槽出口只允许 CONNECT api.deepseek.com:443，正常校验 TLS，不自动重试 POST，不配置备用密钥。每个外部 POST 前持久化占用，失败和结果不明不退款；重复请求由原网关返回既有回执。元数据只保留请求体哈希、模型、HTTP 状态及可取得的 token 用量，不保存正文或密钥。

## 操作与公网入口

```powershell
.\.venv\Scripts\python.exe deploy/workbench_demo/control.py status
.\.venv\Scripts\python.exe deploy/workbench_demo/control.py verify
.\.venv\Scripts\python.exe deploy/workbench_demo/control.py stop
```

Windows 也可用 scripts/windows/workbench-demo.ps1 的 `-Action` 和 `-RuntimeRoot`。日常入口统一为 control.py，不使用 archive 中的历史脚本。

账号在运行目录的 `private/accounts.json`，使用原登录和职责分离，不增加身份切换控件。新建“登记文档全流程联调”后，上传固定哈希的文档，真实抽取、逐条核校候选并确认，再创建云任务、冻结、复核、批准、发送和回链确认。候选不是已确认事实，修改事实会使旧批准失效；测试身份不记作真实法学签署。

需要临时公网访问时，在 init 显式添加 `--public`。主机、Docker、工作台和模型需保持运行。普通 start 更新原站时不把 tunnel 放入同一个 Compose up；已运行的隧道保持原容器会话。status 验证当前进程提供的域名、真实 HTTPS、TLS 证书和匿名 API 拒绝，不把容器 running 当作入口可用。repair 才允许重启失效隧道，临时网址可能改变。固定网址需要另行配置命名隧道和可管理域名。

本地入口使用独立固定目标 TCP 转发器和路由守卫，业务容器仍处于内部网络。它只转发至 public-origin:59767，守卫收据需绑定当前网络命名空间；没有业务卷、服务商密钥、正文日志或 POST 重放。生产网络隔离完整验收仍须目标环境的真实证据。

## 测试与历史源码

普通 pytest 使用临时生成的全新合成文档及 HTTP 本地桩，不需要私有清单或服务商密钥。独立 Docker 冒烟需显式设置 `LEX_RUN_WORKBENCH_DOCKER_TESTS=1` 与 `LEX_DEMO_TEST_RUNTIME_ROOT`，先为该私有测试目录完成 init/build，并按测试生成 `.artifacts/migration/public-synthetic.docx`；其模型及隧道均使用桩，不启动真实 Cloudflare 隧道，也不访问现有演示实例。

完整实测和复现命令见[本分支验证说明](../../docs/CLOUD_EDGE_BRANCH_VALIDATION.md)。历史一次性驱动以经过脱敏的 `.txt` 源码归档，不可直接运行；真实收据、案例原件、账号、模型和日志都不在仓库。
