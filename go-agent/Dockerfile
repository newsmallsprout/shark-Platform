# 边缘探针：心跳 + Playbook 轮询（与中心 SHARK_EDGE_TOKEN 一致）
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY main.go ./
RUN go mod tidy && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/aiops-agent .

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=build /out/aiops-agent /usr/local/bin/aiops-agent
ENTRYPOINT ["/usr/local/bin/aiops-agent"]
