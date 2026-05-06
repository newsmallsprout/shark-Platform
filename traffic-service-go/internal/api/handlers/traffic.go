package handlers

import (
	"errors"
	"io"
	"net/http"
	"strings"

	aptraffic "github.com/shark-platform/traffic-service/internal/service/traffic"

	"github.com/gin-gonic/gin"
)

// MaxIngestBodyBytes 单次 ingest 原始 Body 上限（与 Django TRAFFIC_INGEST_MAX_BODY_LINES 互补侧）。
const MaxIngestBodyBytes = 64 << 20

type Traffic struct {
	Svc *aptraffic.Service
}

func NewTraffic(svc *aptraffic.Service) *Traffic {
	return &Traffic{Svc: svc}
}

// Ingest POST /api/traffic/ingest — 原始 Body 入队，禁止同步解析 JSON。
func (h *Traffic) Ingest(c *gin.Context) {
	src := strings.TrimSpace(c.Query("source"))
	if src == "" {
		src = strings.TrimSpace(c.GetHeader("X-Traffic-Source"))
	}

	raw, err := io.ReadAll(io.LimitReader(c.Request.Body, MaxIngestBodyBytes+1))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "read body"})
		return
	}
	if len(raw) > MaxIngestBodyBytes {
		c.JSON(http.StatusRequestEntityTooLarge, gin.H{"error": "body too large"})
		return
	}

	res, err := h.Svc.EnqueueIngest(src, raw)
	if err != nil {
		if errors.Is(err, aptraffic.ErrIngestShuttingDown) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "shutting_down"})
			return
		}
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, res)
}

// Snapshot GET /api/traffic/snapshot — 占位实现。
func (h *Traffic) Snapshot(c *gin.Context) {
	q := aptraffic.SnapshotQuery{
		Range:    c.DefaultQuery("range", "24h"),
		Source:   strings.TrimSpace(c.Query("source")),
		StartISO: strings.TrimSpace(c.Query("start")),
		EndISO:   strings.TrimSpace(c.Query("end")),
		FullData: parseBoolQuery(c.Query("full_data")),
	}

	payload, err := h.Svc.Snapshot(c.Request.Context(), q)
	if err != nil {
		var he *aptraffic.SnapshotHTTPError
		if errors.As(err, &he) {
			c.JSON(he.Code, gin.H{"error": he.Msg})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, payload)
}

func parseBoolQuery(s string) bool {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}
