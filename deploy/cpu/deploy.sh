#!/usr/bin/env bash
# CPU 版一键部署：等价于 bash deploy/aliyun/deploy.sh --cpu "$@"（Ubuntu 22.04 / 24.04，x86_64，无需 GPU）。
# 可选环境变量见 deploy/aliyun/deploy.sh 开头；其余说明见 deploy/cpu/README.md。
exec bash "$(dirname "$0")/../aliyun/deploy.sh" --cpu "$@"
