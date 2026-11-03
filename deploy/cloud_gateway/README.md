# 独立云网关

本目录包含可单独构建和部署的网关、固定目标 CONNECT 出口、回环 TCP 入口及路由守卫。业务数据、原件、身份映射不挂载到网关。SQLite 账本使用单实例、本地持久卷，与凭据分开，不使用网络共享盘。

`cloud_runtime.py` 在原有 lexaegis.gateway 外增加运维额度控制；正式批准、构建身份、请求哈希、一次性许可仍由原实现核验。production 使用独立配置、签名秘密和卷，不继承 integration 授权。

```powershell
python deploy/cloud_gateway/control.py build
python deploy/cloud_gateway/control.py init --profile integration --private-config '<私有配置目录>' --ledger-source '<明确的合成网关账本>'
python deploy/cloud_gateway/control.py start --profile integration
python deploy/cloud_gateway/control.py status --profile integration
python deploy/cloud_gateway/control.py verify --profile integration
python deploy/cloud_gateway/control.py backup --profile integration
python deploy/cloud_gateway/control.py stop --profile integration
```

先查看 `control.py --help` 获取各动作参数；模板 env 文件只保存非秘密引用。新 integration 默认真实调用上限为 0，既有记录和额度不得清零。服务商凭据及明确的使用确认放在仓库外 gateway.env，HMAC 放在 gateway-secret；文件权限为私有文件，由受限 stdin 初始化至网关专属卷。模型服务商 Key 不放入操作系统环境或 Compose environment。

`ds_gateway.py` 与 `shared_budget.py` 供登记合成文档 integration 部署使用：跨网关预占同一持久额度，每次外部 POST 前占用，失败和未知不退款，重启不清零。默认零额度不持有服务商凭据，并遵守原网关的 keyless edge 角色规则；有明确额度和凭据时才使用 cloud 角色。它们拒绝 production，不构成正式案件例外。

可交互完整演示参见 `../workbench_demo/README.md`。`public_demo_control.py` 保留原来的独立只读 mock 演示，两种部署使用不同卷和不同入口，不混用账号或授权。历史本机脚本和驱动经脱敏归档于 workbench_demo/archive，不作为日常入口。

云主机迁移只传输代码、锁文件和必要包，从源码构建或校验导出的镜像。不要同步边侧 .data、原件、账号、模型或数据库。网关回环入口经受限 SSH 转发访问，校验 host key，禁止 agent forwarding；示例见 sshd-forward.conf.example。启用 production 仍需真实 verified 构建身份及当前请求所需 G 表收据、具名批准和许可。

备份不包含密钥；恢复必须保留已发送、结果不明、许可消费和额度记录，按原恢复流程使旧授权失效。本目录不自动覆盖账本、删除卷、重发未知结果或切换服务商。

源码构建上下文只包含明确允许的后端、packs、锁文件及网关脚本。镜像 config ID、仓库 digest、导出 tar 的 SHA-256 分别记录，不能互相代替。任何本地测试通过都不能代填生产隔离、正式发送或法学审核收据。
