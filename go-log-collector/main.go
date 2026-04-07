// go-log-collector — 轻量日志上报：可选仅关键行、边缘正则脱敏、批量 POST。
// 支持多文件、类 tail -f 持续读取（适合 Nginx access/error 日志）。
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
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

func envBool(key string) bool {
	v := strings.ToLower(strings.TrimSpace(env(key, "")))
	return v == "1" || v == "true" || v == "yes"
}

func main() {
	center := strings.TrimRight(env("SHARK_AIOPS_CENTER_URL", "http://127.0.0.1:8000"), "/")
	token := env("SHARK_AIOPS_EDGE_TOKEN", "")
	source := env("SHARK_AIOPS_LOG_SOURCE", "edge")
	pathsRaw := env("SHARK_AIOPS_LOG_PATHS", "")
	batch := 100
	severity := strings.ToLower(env("SHARK_AIOPS_LOG_SEVERITY", "error"))
	follow := envBool("SHARK_AIOPS_LOG_FOLLOW")
	fromEnd := true
	if follow {
		// 默认 1：从当前文件末尾开始只推新行；设为 0 则先把已有内容读完再跟随
		fromEnd = strings.TrimSpace(env("SHARK_AIOPS_LOG_FROM_END", "1")) != "0"
	}

	url := center + "/api/edge/logs"
	client := &http.Client{Timeout: 30 * time.Second}
	redactors := compileRedactors()

	paths := parsePaths(pathsRaw)
	if len(paths) == 0 {
		runStdin(source, url, token, client, redactors, severity, batch)
		return
	}

	if follow {
		lineCh := make(chan string, 4096)
		for _, p := range paths {
			p := p
			go tailFileForever(p, fromEnd, lineCh)
		}
		runConsumer(lineCh, source, url, token, client, redactors, severity, batch)
		return
	}

	runFilesOnce(paths, source, url, token, client, redactors, severity, batch)
}

func parsePaths(raw string) []string {
	if raw == "" {
		return nil
	}
	var out []string
	for _, part := range strings.Split(raw, ",") {
		p := strings.TrimSpace(part)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}

func runStdin(
	source, url, token string,
	client *http.Client,
	redactors []redactor,
	severity string,
	batch int,
) {
	scanner := bufio.NewScanner(os.Stdin)
	// 极长行（JSON access log）放宽 buffer
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	lines, flush := makeFlusher(source, url, token, client, batch)
	tick := time.NewTicker(5 * time.Second)
	defer tick.Stop()
	go func() {
		for range tick.C {
			flush()
		}
	}()
	for scanner.Scan() {
		line := processLine(scanner.Text(), redactors, severity)
		if line == "" {
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

func runFilesOnce(
	paths []string,
	source, url, token string,
	client *http.Client,
	redactors []redactor,
	severity string,
	batch int,
) {
	lines, flush := makeFlusher(source, url, token, client, batch)
	tick := time.NewTicker(5 * time.Second)
	defer tick.Stop()
	go func() {
		for range tick.C {
			flush()
		}
	}()

	for _, path := range paths {
		f, err := os.Open(path)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
		for sc.Scan() {
			line := processLine(sc.Text(), redactors, severity)
			if line == "" {
				continue
			}
			lines = append(lines, line)
			if len(lines) >= batch {
				flush()
			}
		}
		_ = f.Close()
		if err := sc.Err(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}
	flush()
}

func runConsumer(
	lineCh <-chan string,
	source, url, token string,
	client *http.Client,
	redactors []redactor,
	severity string,
	batch int,
) {
	lines, flush := makeFlusher(source, url, token, client, batch)
	tick := time.NewTicker(5 * time.Second)
	go func() {
		for range tick.C {
			flush()
		}
	}()
	defer tick.Stop()
	for line := range lineCh {
		line = processLine(line, redactors, severity)
		if line == "" {
			continue
		}
		lines = append(lines, line)
		if len(lines) >= batch {
			flush()
		}
	}
	flush()
}

func makeFlusher(source, url, token string, client *http.Client, batch int) (lines []string, flush func()) {
	lines = make([]string, 0, batch)
	flush = func() {
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
	return lines, flush
}

func processLine(raw string, redactors []redactor, severity string) string {
	line := applyRedaction(raw, redactors)
	if !shouldForward(line, severity) {
		return ""
	}
	return line
}

// tailFileForever 轮询文件增长，类 tail -f；简单处理截断/轮转（文件变小则从头再读）。
func tailFileForever(path string, startAtEnd bool, out chan<- string) {
	var offset int64
	first := true
	const pause = time.Second
	for {
		f, err := os.Open(path)
		if err != nil {
			time.Sleep(pause)
			continue
		}
		st, err := f.Stat()
		if err != nil {
			_ = f.Close()
			time.Sleep(pause)
			continue
		}
		sz := st.Size()
		if first && startAtEnd {
			offset = sz
			first = false
		}
		if sz < offset {
			offset = 0
		}
		if sz > offset {
			_, err = f.Seek(offset, io.SeekStart)
			if err != nil {
				_ = f.Close()
				time.Sleep(pause)
				continue
			}
			sc := bufio.NewScanner(f)
			sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
			for sc.Scan() {
				out <- sc.Text()
			}
			if err := sc.Err(); err != nil {
				fmt.Fprintf(os.Stderr, "%s: %v\n", path, err)
			}
			pos, _ := f.Seek(0, io.SeekCurrent)
			offset = pos
		}
		_ = f.Close()
		time.Sleep(pause)
	}
}

type redactor struct {
	re  *regexp.Regexp
	rep string
}

func compileRedactors() []redactor {
	custom := env("SHARK_AIOPS_REDACT_REGEX", "")
	var out []redactor
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
	return strings.Contains(low, "error") || strings.Contains(low, "fatal") ||
		strings.Contains(low, "panic")
}
