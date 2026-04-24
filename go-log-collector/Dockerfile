# 与 docker-compose 中 log-collector 服务配合，采集 Nginx 等文件日志
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY main.go ./
RUN go mod tidy && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/aiops-log-collector .

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=build /out/aiops-log-collector /usr/local/bin/aiops-log-collector
ENTRYPOINT ["/usr/local/bin/aiops-log-collector"]
