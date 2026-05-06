package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/shark-platform/traffic-service/internal/api"
	"github.com/shark-platform/traffic-service/internal/api/handlers"
	"github.com/shark-platform/traffic-service/internal/config"
	appmetrics "github.com/shark-platform/traffic-service/internal/pkg/metrics"
	appdb "github.com/shark-platform/traffic-service/internal/pkg/database"
	appgeoip "github.com/shark-platform/traffic-service/internal/pkg/geoip"
	aptraffic "github.com/shark-platform/traffic-service/internal/service/traffic"

	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func main() {
	cfg := config.Load()
	gin.SetMode(cfg.GinMode)

	var db *gorm.DB
	if cfg.PostgresDSN != "" {
		var err error
		db, err = appdb.OpenPostgres(cfg.PostgresDSN, cfg.DBMaxOpenConn, cfg.DBMaxIdleConn, logger.Warn)
		if err != nil {
			log.Fatalf("postgres: %v", err)
		}
		log.Printf("postgres connected (pool open=%d idle=%d)", cfg.DBMaxOpenConn, cfg.DBMaxIdleConn)
	} else {
		log.Print("warning: DATABASE_URL empty — snapshot PG fallback disabled until configured")
	}

	geoReader, err := appgeoip.Open(cfg.GeoIPDBPath)
	if err != nil {
		log.Fatalf("geoip: %v", err)
	}
	if geoReader != nil {
		defer func() { _ = geoReader.Close() }()
	}

	var chConn driver.Conn
	if cfg.ClickHouseEnabled() {
		chConn, err = appdb.OpenClickHouse(appdb.ClickHouseConfig{
			Addrs:           cfg.ClickHouseAddrList(),
			Database:        cfg.ClickHouseDatabase,
			User:            cfg.ClickHouseUser,
			Password:        cfg.ClickHousePassword,
			TLS:             cfg.ClickHouseTLS,
			MaxOpenConns:    cfg.ClickHouseMaxOpenConn,
			ConnMaxLifetime: time.Hour,
		})
		if err != nil {
			log.Fatalf("clickhouse: %v", err)
		}
		log.Printf("clickhouse connected addrs=%v db=%s raw_table=%s rollup_table=%s",
			cfg.ClickHouseAddrList(), cfg.ClickHouseDatabase, cfg.ClickHouseTable, cfg.ClickHouseRollupTable)
	}

	ingestCfg := aptraffic.IngestPipelineConfig{
		QueueDepth: cfg.IngestQueueDepth,
		Workers:    cfg.IngestWorkerCount,
	}
	snapEnv := aptraffic.SnapshotEnv{
		Blackbox: aptraffic.BlackboxConfig{
			PrometheusURL: cfg.PrometheusURL,
			PromQL:        cfg.BlackboxPromQL,
		},
		AccessLogMode:       cfg.AccessLogMode,
		LogConfigured:       cfg.LogConfigured(),
		RollupIngestEnabled: cfg.RollupIngestEnabled,
	}
	svc := aptraffic.New(db, geoReader, ingestCfg, snapEnv, chConn, cfg)

	appmetrics.RegisterLogQueueGaugeFunc(svc)

	hTraffic := handlers.NewTraffic(svc)

	engine := api.NewRouter(api.RouterDeps{Traffic: hTraffic})

	srv := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           engine,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		log.Printf("listening %s", cfg.HTTPAddr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("server: %v", err)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Print("shutdown signal received, draining ingest queue and flushing ClickHouse…")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("http shutdown: %v", err)
	}

	doneDrain := make(chan struct{})
	go func() {
		svc.ShutdownGraceful()
		close(doneDrain)
	}()

	select {
	case <-doneDrain:
	case <-shutdownCtx.Done():
		log.Print("warning: graceful drain timed out; some buffered ingest rows may be lost")
	}

	log.Print("traffic-service stopped")
}
