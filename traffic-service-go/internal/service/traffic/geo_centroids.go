package traffic

import (
	"strings"
)

// centroidForCountry 对齐 Django geo_centroids.centroid_for_country。
func centroidForCountry(iso2 string) (lat, lng float64, ok bool) {
	code := strings.TrimSpace(iso2)
	if code == "" {
		return 0, 0, false
	}
	code = strings.ToUpper(code)
	if len(code) > 2 {
		code = code[:2]
	}
	if code == "LAN" || code == "??" {
		return 0, 0, false
	}
	ll, ok := iso2Centroids[code]
	if !ok {
		return 0, 0, false
	}
	return ll[0], ll[1], true
}

// 自 shark-platform/traffic/services/geo_centroids.py ISO2_CENTROIDS 复制。
var iso2Centroids = map[string][2]float64{
	"CN": {35.0, 105.0}, "US": {38.0, -97.0}, "JP": {36.0, 138.0}, "DE": {51.0, 10.0},
	"GB": {54.0, -2.0}, "FR": {46.0, 2.0}, "IN": {22.0, 79.0}, "BR": {-10.0, -55.0},
	"RU": {60.0, 100.0}, "KR": {36.0, 128.0}, "CA": {60.0, -95.0}, "AU": {-25.0, 134.0},
	"SG": {1.35, 103.82}, "HK": {22.3, 114.17}, "TW": {23.7, 121.0}, "NL": {52.0, 5.0},
	"IT": {42.8, 12.6}, "ES": {40.0, -4.0}, "MX": {23.0, -102.0}, "ID": {-2.0, 118.0},
	"TR": {39.0, 35.0}, "SA": {24.0, 45.0}, "ZA": {-29.0, 25.0}, "AR": {-34.0, -64.0},
	"PL": {52.0, 19.0}, "SE": {62.0, 15.0}, "CH": {47.0, 8.0}, "BE": {50.5, 4.5},
	"AT": {47.5, 14.5}, "NO": {62.0, 10.0}, "FI": {64.0, 26.0}, "DK": {56.0, 10.0},
	"IE": {53.0, -8.0}, "PT": {39.5, -8.0}, "TH": {15.0, 101.0}, "VN": {16.0, 108.0},
	"MY": {4.2, 101.7}, "PH": {13.0, 122.0}, "AE": {24.0, 54.0}, "IL": {31.5, 34.8},
	"NZ": {-42.0, 174.0}, "UA": {49.0, 32.0}, "CZ": {49.75, 15.5}, "HU": {47.2, 19.5},
	"RO": {46.0, 25.0}, "GR": {39.0, 22.0}, "??": {0.0, 0.0},
}
