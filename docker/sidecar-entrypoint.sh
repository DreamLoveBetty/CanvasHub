#!/bin/sh
set -e

# Sidecar 不需要初始化配置，settings.json 由 server 容器管理
exec "$@"
