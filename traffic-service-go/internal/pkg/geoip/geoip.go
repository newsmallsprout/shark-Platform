package geoip

import (
	"fmt"
	"net"

	"github.com/oschwald/geoip2-golang"
)

// Reader 封装 MaxMind GeoIP2（City）读取器，便于注入与 mock。
type Reader struct {
	inner *geoip2.Reader
}

// Open 打开本地 .mmdb；path 为空时返回 (nil, nil) 表示禁用 GeoIP。
func Open(path string) (*Reader, error) {
	if path == "" {
		return nil, nil
	}
	r, err := geoip2.Open(path)
	if err != nil {
		return nil, fmt.Errorf("geoip open %q: %w", path, err)
	}
	return &Reader{inner: r}, nil
}

func (r *Reader) Close() error {
	if r == nil || r.inner == nil {
		return nil
	}
	return r.inner.Close()
}

// DB 暴露底层 reader（占位；业务层再封装 Lookup）。
func (r *Reader) DB() *geoip2.Reader {
	if r == nil {
		return nil
	}
	return r.inner
}

// LookupCountryISOCode 返回 ISO 3166-1 alpha-2；解析失败或未配置时返回空串。
// geoip2.Reader 文档说明并发读安全，进程内应复用单一 Reader。
func (r *Reader) LookupCountryISOCode(ipStr string) string {
	if r == nil || r.inner == nil || ipStr == "" {
		return ""
	}
	ip := net.ParseIP(ipStr)
	if ip == nil {
		return ""
	}
	rec, err := r.inner.City(ip)
	if err != nil {
		return ""
	}
	return rec.Country.IsoCode
}
