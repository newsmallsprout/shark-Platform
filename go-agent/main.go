// go-agent — AIOps Platform 边缘探针：心跳 + 轮询 Playbook 执行并回传结果。
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"runtime"
	"strings"
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
	center := strings.TrimRight(env("SHARK_AIOPS_CENTER_URL", "http://127.0.0.1:8000"), "/")
	token := env("SHARK_AIOPS_EDGE_TOKEN", "")
	nodeID := env("SHARK_AIOPS_NODE_ID", "")
	interval := env("SHARK_AIOPS_INTERVAL", "30s")
	playbookEvery := env("SHARK_AIOPS_PLAYBOOK_POLL", "5s")

	if nodeID == "" {
		hi, _ := host.Info()
		if hi != nil && hi.HostID != "" {
			nodeID = hi.HostID
		} else {
			nodeID = "unknown-host"
		}
	}
	hbDur, err := time.ParseDuration(interval)
	if err != nil {
		hbDur = 30 * time.Second
	}
	pbDur, err := time.ParseDuration(playbookEvery)
	if err != nil {
		pbDur = 5 * time.Second
	}
	if token == "" {
		fmt.Fprintln(os.Stderr, "SHARK_AIOPS_EDGE_TOKEN is empty; center will reject requests")
	}

	client := &http.Client{Timeout: 60 * time.Second}
	go heartbeatLoop(client, center, token, nodeID, hbDur)
	go playbookLoop(client, center, token, nodeID, pbDur)
	select {}
}

func setEdgeHeaders(req *http.Request, token string) {
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("X-Shark-Edge-Token", token)
	}
}

func heartbeatLoop(client *http.Client, center, token, nodeID string, d time.Duration) {
	u := center + "/api/edge/heartbeat"
	for {
		payload := collect(nodeID)
		b, _ := json.Marshal(payload)
		req, err := http.NewRequest(http.MethodPost, u, bytes.NewReader(b))
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			time.Sleep(d)
			continue
		}
		setEdgeHeaders(req, token)
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

type playbookJob struct {
	ID       string `json:"id"`
	Script   string `json:"script"`
	TicketID string `json:"ticket_id"`
}

func playbookLoop(client *http.Client, center, token, nodeID string, d time.Duration) {
	pollURL := center + "/api/edge/playbooks?" + url.Values{"node_id": {nodeID}}.Encode()
	for {
		req, err := http.NewRequest(http.MethodGet, pollURL, nil)
		if err != nil {
			time.Sleep(d)
			continue
		}
		if token != "" {
			req.Header.Set("X-Shark-Edge-Token", token)
		}
		resp, err := client.Do(req)
		if err != nil {
			fmt.Fprintln(os.Stderr, "playbooks poll:", err)
			time.Sleep(d)
			continue
		}
		var body struct {
			Jobs []playbookJob `json:"jobs"`
		}
		_ = json.NewDecoder(resp.Body).Decode(&body)
		resp.Body.Close()

		for _, j := range body.Jobs {
			runPlaybook(client, center, token, nodeID, j)
		}
		time.Sleep(d)
	}
}

func runPlaybook(client *http.Client, center, token, nodeID string, j playbookJob) {
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, "/bin/sh", "-c", j.Script)
	var outb, errb bytes.Buffer
	cmd.Stdout = &outb
	cmd.Stderr = &errb
	runErr := cmd.Run()
	ok := runErr == nil
	payload := map[string]any{
		"ok":       ok,
		"stdout":   outb.String(),
		"stderr":   errb.String(),
		"node_id":  nodeID,
		"exit_err": fmt.Sprintf("%v", runErr),
	}
	b, _ := json.Marshal(payload)
	u := fmt.Sprintf("%s/api/edge/playbooks/%s/complete", center, j.ID)
	req, err := http.NewRequest(http.MethodPost, u, bytes.NewReader(b))
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return
	}
	setEdgeHeaders(req, token)
	resp, err := client.Do(req)
	if err != nil {
		fmt.Fprintln(os.Stderr, "playbook complete:", err)
		return
	}
	resp.Body.Close()
	if resp.StatusCode >= 300 {
		fmt.Fprintf(os.Stderr, "playbook complete: HTTP %s\n", resp.Status)
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
		"node_id":      nodeID,
		"hostname":     h.Hostname,
		"os":           fmt.Sprintf("%s %s", h.OS, h.Platform),
		"kernel":       h.KernelVersion,
		"uptime_sec":   h.Uptime,
		"cpu_percent":  cpuPct,
		"mem_percent":  v.UsedPercent,
		"mem_total_mb": v.Total / 1024 / 1024,
		"load1":        l.Load1,
		"load5":        l.Load5,
		"load15":       l.Load15,
		"go_version":   runtime.Version(),
		"ts_unix":      time.Now().Unix(),
	}
	if du != nil {
		out["disk_percent"] = du.UsedPercent
		out["disk_total_gb"] = du.Total / 1024 / 1024 / 1024
	}
	return out
}
