// go-log-collector — 轻量日志上报：可选仅关键行、边缘正则脱敏、批量 POST。
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"regexp"
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
	center := strings.TrimRight(env("SHARK_AIOPS_CENTER_URL", "http://127.0.0.1:8000"), "/")
	token := env("SHARK_AIOPS_EDGE_TOKEN", "")
	source := env("SHARK_AIOPS_LOG_SOURCE", "edge")
	paths := env("SHARK_AIOPS_LOG_PATHS", "")
	batch := 100
	severity := strings.ToLower(env("SHARK_AIOPS_LOG_SEVERITY", "error"))
	// severity=error|warn|all — all 表示不过滤关键字
	url := center + "/api/edge/logs"
	client := &http.Client{Timeout: 30 * time.Second}

	redactors := compileRedactors()

	var scanner *bufio.Scanner
	if paths == "" {
		scanner = bufio.NewScanner(os.Stdin)
	} else {
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
		line := scanner.Text()
		line = applyRedaction(line, redactors)
		if !shouldForward(line, severity) {
			continue
		}
		lines = append(lines, line)
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

type redactor struct {
	re  *regexp.Regexp
	rep string
}

func compileRedactors() []redactor {
	custom := env("SHARK_AIOPS_REDACT_REGEX", "")
	var out []redactor
	// 内置：邮箱、简易卡号、Bearer Token
	builtin := []struct {
		pat, rep string
	}{
		{`[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`, `[REDACTED_EMAIL]`},
		{`\b(?:\d[ -]*?){13,16}\b`, `[REDACTED_PAN]`},
		{`(?i)bearer\s+[a-z0-9._\-]{8,}`, `Bearer [REDACTED]`},
	}
	for _, b := range builtin {
		if re, err := regexp.Compile(b.pat); err == nil {
			out = append(out, redactor{re: re, rep: b.rep})
		}
	}
	if custom != "" {
		for _, part := range strings.Split(custom, "||") {
			part = strings.TrimSpace(part)
			if part == "" {
				continue
			}
			// 格式 pattern@@@replacement
			chunks := strings.SplitN(part, "@@@", 2)
			if len(chunks) != 2 {
				continue
			}
			if re, err := regexp.Compile(strings.TrimSpace(chunks[0])); err == nil {
				out = append(out, redactor{re: re, rep: chunks[1]})
			}
		}
	}
	return out
}

func applyRedaction(line string, rs []redactor) string {
	for _, r := range rs {
		line = r.re.ReplaceAllString(line, r.rep)
	}
	return line
}

func shouldForward(line, severity string) bool {
	if severity == "all" || severity == "" {
		return true
	}
	low := strings.ToLower(line)
	if severity == "warn" {
		return strings.Contains(low, "error") || strings.Contains(low, "fatal") ||
			strings.Contains(low, "panic") || strings.Contains(low, "warn")
	}
	// error
	return strings.Contains(low, "error") || strings.Contains(low, "fatal") ||
		strings.Contains(low, "panic")
}
