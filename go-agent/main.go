// go-agent — edge system probe for shark-aiops control plane.
// Push host metrics / heartbeat; extend payload for future PML-driven collectors.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"runtime"
	"time"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/host"
	"github.com/shirou/gopsutil/v4/load"
	"github.com/shirou/gopsutil/v4/mem"
)

func env(key, def string) string {
	v := os.Getenv(key)
	if v == "" {
		return def
	}
	return v
}

func main() {
	center := env("SHARK_AIOPS_CENTER_URL", "http://127.0.0.1:8000")
	token := env("SHARK_AIOPS_EDGE_TOKEN", "")
	nodeID := env("SHARK_AIOPS_NODE_ID", "")
	interval := env("SHARK_AIOPS_INTERVAL", "30s")
	if nodeID == "" {
		hi, _ := host.Info()
		if hi != nil && hi.HostID != "" {
			nodeID = hi.HostID
		} else {
			nodeID = "unknown-host"
		}
	}
	d, err := time.ParseDuration(interval)
	if err != nil {
		d = 30 * time.Second
	}
	url := center + "/api/edge/heartbeat"
	if token == "" {
		fmt.Fprintln(os.Stderr, "SHARK_AIOPS_EDGE_TOKEN is empty; requests will be rejected by center")
	}

	client := &http.Client{Timeout: 15 * time.Second}
	for {
		payload := collect(nodeID)
		b, _ := json.Marshal(payload)
		req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(b))
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			time.Sleep(d)
			continue
		}
		req.Header.Set("Content-Type", "application/json")
		if token != "" {
			req.Header.Set("X-Shark-Edge-Token", token)
		}
		resp, err := client.Do(req)
		if err != nil {
			fmt.Fprintln(os.Stderr, "heartbeat:", err)
		} else {
			resp.Body.Close()
			if resp.StatusCode >= 300 {
				fmt.Fprintf(os.Stderr, "heartbeat: HTTP %s\n", resp.Status)
			}
		}
		time.Sleep(d)
	}
}

func collect(nodeID string) map[string]any {
	h, _ := host.Info()
	v, _ := mem.VirtualMemory()
	l, _ := load.Avg()
	cpus, _ := cpu.Percent(time.Second, false)
	var cpuPct float64
	if len(cpus) > 0 {
		cpuPct = cpus[0]
	}
	du, _ := disk.Usage("/")
	out := map[string]any{
		"node_id":       nodeID,
		"hostname":      h.Hostname,
		"os":            fmt.Sprintf("%s %s", h.OS, h.Platform),
		"kernel":        h.KernelVersion,
		"uptime_sec":    h.Uptime,
		"cpu_percent":   cpuPct,
		"mem_percent":   v.UsedPercent,
		"mem_total_mb":  v.Total / 1024 / 1024,
		"load1":         l.Load1,
		"load5":         l.Load5,
		"load15":        l.Load15,
		"go_version":    runtime.Version(),
		"ts_unix":       time.Now().Unix(),
	}
	if du != nil {
		out["disk_percent"] = du.UsedPercent
		out["disk_total_gb"] = du.Total / 1024 / 1024 / 1024
	}
	return out
}
