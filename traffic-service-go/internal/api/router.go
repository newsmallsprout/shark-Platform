package api

import (
	"net/http"

	"github.com/shark-platform/traffic-service/internal/api/handlers"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

type RouterDeps struct {
	Traffic *handlers.Traffic
}

// NewRouter 构建 Gin 引擎（不含 Run）。
func NewRouter(deps RouterDeps) *gin.Engine {
	r := gin.New()
	r.Use(gin.Recovery())

	// 结构化日志可按环境替换为 zap / slog
	r.Use(gin.Logger())

	r.GET("/healthz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})

	v1 := r.Group("/api/traffic")
	{
		v1.POST("/ingest", deps.Traffic.Ingest)
		v1.GET("/snapshot", deps.Traffic.Snapshot)
	}

	r.GET("/metrics", gin.WrapH(promhttp.Handler()))

	return r
}
