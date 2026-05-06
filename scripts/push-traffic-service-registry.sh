#!/usr/bin/env bash
# 构建 traffic-service-go 镜像并推送到私有仓库（沿用 ops 镜像名可自行改 IMAGE_NAME）。
#
# 用法（在仓库根目录）:
#   ./scripts/push-traffic-service-registry.sh <版本号>
# 示例:
#   ./scripts/push-traffic-service-registry.sh 20260506
#   IMAGE_NAME=ops ./scripts/push-traffic-service-registry.sh 20260506
#
# 环境变量（可选）:
#   REGISTRY   默认 192.168.12.74:80/bitnamilegacy
#   IMAGE_NAME 默认 traffic-service（设为 ops 则标签为 ops:v<版本>）

set -euo pipefail

VERSION="${1:?用法: $0 <版本号，不含前缀 v，例如 20260506>}"
REGISTRY="${REGISTRY:-192.168.12.74:80/bitnamilegacy}"
IMAGE_NAME="${IMAGE_NAME:-traffic-service}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

git pull

LOCAL_TAG="${IMAGE_NAME}:v${VERSION}"
REMOTE_TAG="${REGISTRY}/${IMAGE_NAME}:v${VERSION}"

docker build -t "$LOCAL_TAG" -f traffic-service-go/Dockerfile traffic-service-go
docker tag "$LOCAL_TAG" "$REMOTE_TAG"
docker push "$REMOTE_TAG"

echo ">>> 已推送: $REMOTE_TAG"
