# 容器入口

`Dockerfile` 是单容器演示入口。`docker-entrypoint.sh` 只在命令为 `lexaegis start` 时尝试拉起
Linux 边侧；Compose 覆盖为 api/worker/gateway 时不会在业务容器里再起一份模型。

把宿主机 `./models` 只读挂到 `/models` 后，同一容器读取随包 Qwen3 GGUF。未挂载时工作台仍启动。
单容器是 native，不能自证隔离。隔离形态见 `compose*.yaml`。
