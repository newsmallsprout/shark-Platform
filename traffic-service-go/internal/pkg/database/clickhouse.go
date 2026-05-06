package database

import (
	"context"
	"crypto/tls"
	"fmt"
	"strings"
	"time"

	clickhouse "github.com/ClickHouse/clickhouse-go/v2"
	"github.com/ClickHouse/clickhouse-go/v2/lib/driver"
)

// ClickHouseConfig ClickHouse native 协议连接池参数（clickhouse-go v2）。
type ClickHouseConfig struct {
	Addrs           []string
	Database        string
	User            string
	Password        string
	TLS             bool
	DialTimeout     time.Duration
	MaxOpenConns    int
	ConnMaxLifetime time.Duration
}

func normalizeCHAddrs(addrs []string) []string {
	out := make([]string, 0, len(addrs))
	for _, a := range addrs {
		a = strings.TrimSpace(a)
		if a != "" {
			out = append(out, a)
		}
	}
	return out
}

// OpenClickHouse 建立 ClickHouse 连接池（Conn 接口内置连接池；PrepareBatch 批量发送）。
func OpenClickHouse(cfg ClickHouseConfig) (driver.Conn, error) {
	addrs := normalizeCHAddrs(cfg.Addrs)
	if len(addrs) == 0 {
		return nil, fmt.Errorf("clickhouse: no addresses")
	}
	db := strings.TrimSpace(cfg.Database)
	if db == "" {
		db = "traffic"
	}
	user := strings.TrimSpace(cfg.User)
	if user == "" {
		user = "default"
	}
	dial := cfg.DialTimeout
	if dial <= 0 {
		dial = 5 * time.Second
	}
	maxOpen := cfg.MaxOpenConns
	if maxOpen <= 0 {
		maxOpen = 16
	}
	life := cfg.ConnMaxLifetime
	if life <= 0 {
		life = time.Hour
	}

	opts := &clickhouse.Options{
		Addr: addrs,
		Auth: clickhouse.Auth{
			Database: db,
			Username: user,
			Password: cfg.Password,
		},
		DialTimeout:     dial,
		MaxOpenConns:    maxOpen,
		ConnMaxLifetime: life,
		Compression: &clickhouse.Compression{
			Method: clickhouse.CompressionLZ4,
		},
	}
	if cfg.TLS {
		opts.TLS = &tls.Config{
			MinVersion: tls.VersionTLS12,
		}
	}

	conn, err := clickhouse.Open(opts)
	if err != nil {
		return nil, err
	}
	pingCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := conn.Ping(pingCtx); err != nil {
		_ = conn.Close()
		return nil, err
	}
	return conn, nil
}
