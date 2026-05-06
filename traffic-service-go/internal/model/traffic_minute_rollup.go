package model

import (
	"time"

	"gorm.io/datatypes"
)

// TrafficMinuteRollup 对齐 Django traffic.TrafficMinuteRollup（共享 PostgreSQL 时使用默认表名）。
// 参见 shark-platform/traffic/models.py
type TrafficMinuteRollup struct {
	ID uint64 `gorm:"column:id;primaryKey;autoIncrement"`

	BucketStart time.Time `gorm:"column:bucket_start;not null;uniqueIndex:uniq_bucket_source;comment:UTC minute start (inclusive)"`
	SourceID    string    `gorm:"column:source_id;type:varchar(64);not null;default:'';uniqueIndex:uniq_bucket_source"`

	Requests       uint   `gorm:"column:requests;not null;default:0"`
	SumLatencyMs   uint64 `gorm:"column:sum_latency_ms;not null;default:0"`
	CountLatency   uint   `gorm:"column:count_latency;not null;default:0"`
	Status2xx      uint   `gorm:"column:status_2xx;not null;default:0"`
	Status4xx      uint   `gorm:"column:status_4xx;not null;default:0"`
	Status5xx      uint   `gorm:"column:status_5xx;not null;default:0"`
	P50Ms          *float64 `gorm:"column:p50_ms"`
	P95Ms          *float64 `gorm:"column:p95_ms"`
	P99Ms          *float64 `gorm:"column:p99_ms"`
	GeoCounts datatypes.JSON `gorm:"column:geo_counts;type:jsonb"`
	TopPaths  datatypes.JSON `gorm:"column:top_paths;type:jsonb"`

	UpdatedAt time.Time `gorm:"column:updated_at;autoUpdateTime"`
}

func (TrafficMinuteRollup) TableName() string {
	// Django 默认: app_label + "_" + model_name.lower()
	return "traffic_trafficminuterollup"
}
