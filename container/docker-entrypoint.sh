#!/bin/sh
set -eu

is_single_container_start() {
    [ "${1:-}" = "python" ] && [ "${2:-}" = "-m" ] && [ "${3:-}" = "lexaegis.cli" ] && [ "${4:-}" = "start" ]
}

if is_single_container_start "$@"; then
    if [ -n "${LEX_EDGE_BIN:-}" ] && [ -x "${LEX_EDGE_BIN}" ] \
            && [ -n "${LEX_EDGE_GGUF:-}" ] && [ -f "${LEX_EDGE_GGUF}" ]; then
        if python -m lexaegis.cli edge --start; then
            export LEX_DEMO_LIVE_EDGE_REVIEW=1
        else
            echo "边侧未启动，工作台仍继续；演示将使用离线审核夹具。"
        fi
    else
        echo "未挂载边侧 GGUF（docker run -v ./models:/models:ro），工作台仍启动。"
    fi
fi

exec "$@"
