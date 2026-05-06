package database

import (
	"fmt"
	"time"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// OpenPostgres 打开 PostgreSQL 连接池（业务逻辑未启用时可仅用于健康检查占位）。
func OpenPostgres(dsn string, maxOpen, maxIdle int, logLevel logger.LogLevel) (*gorm.DB, error) {
	if dsn == "" {
		return nil, fmt.Errorf("postgres DSN is empty")
	}
	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{
		Logger: logger.Default.LogMode(logLevel),
	})
	if err != nil {
		return nil, err
	}
	sqlDB, err := db.DB()
	if err != nil {
		return nil, err
	}
	sqlDB.SetMaxOpenConns(maxOpen)
	sqlDB.SetMaxIdleConns(maxIdle)
	sqlDB.SetConnMaxLifetime(time.Hour)
	return db, nil
}
