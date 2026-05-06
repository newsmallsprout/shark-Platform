# 构建（构建上下文必须是 traffic-service-go 目录）：
#   docker build -t your-registry/traffic-service:latest traffic-service-go
FROM golang:1.23-bookworm AS builder
WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/traffic-service ./cmd/server

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /out/traffic-service /usr/local/bin/traffic-service
USER nobody:nogroup
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/traffic-service"]
