// go-log-collector — tail files or stdin and batch POST lines to shark-aiops for dashboard pipelines.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"
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
	source := env("SHARK_AIOPS_LOG_SOURCE", "edge")
	paths := env("SHARK_AIOPS_LOG_PATHS", "") // comma-separated files; empty = stdin
	batch := 100
	url := center + "/api/edge/logs"
	client := &http.Client{Timeout: 30 * time.Second}

	var scanner *bufio.Scanner
	if paths == "" {
		scanner = bufio.NewScanner(os.Stdin)
	} else {
		// single file or first path for simplicity
		parts := strings.Split(paths, ",")
		f, err := os.Open(strings.TrimSpace(parts[0]))
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		defer f.Close()
		scanner = bufio.NewScanner(f)
	}

	var lines []string
	flush := func() {
		if len(lines) == 0 {
			return
		}
		body, _ := json.Marshal(map[string]any{
			"source": source,
			"lines":  lines,
		})
		req, _ := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		if token != "" {
			req.Header.Set("X-Shark-Edge-Token", token)
		}
		resp, err := client.Do(req)
		if err != nil {
			fmt.Fprintln(os.Stderr, "push:", err)
		} else {
			resp.Body.Close()
		}
		lines = lines[:0]
	}

	tick := time.NewTicker(5 * time.Second)
	defer tick.Stop()
	go func() {
		for range tick.C {
			flush()
		}
	}()

	for scanner.Scan() {
		lines = append(lines, scanner.Text())
		if len(lines) >= batch {
			flush()
		}
	}
	flush()
	if err := scanner.Err(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
