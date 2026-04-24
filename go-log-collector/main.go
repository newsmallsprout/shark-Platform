// go-log-collector — 轻量日志上报：可选仅关键行、边缘正则脱敏、批量 POST。
// 支持多路径、通配符（glob）、类 tail -f；可按文件名推导 stream_key（如 access_api.json.log -> api）。
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
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

// 路径含 * ? [ 时按 glob 展开；逗号分隔多个 pattern
func expandPathPatterns(parts []string) []string {
	var out []string
	seen := make(map[string]struct{})
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if strings.ContainsAny(part, "*?[") {
			matches, err := filepath.Glob(part)
			if err != nil {
				fmt.Fprintln(os.Stderr, "glob:", err)
				continue
			}
			for _, m := range matches {
				if st, err := os.Stat(m); err != nil || st.IsDir() {
					continue
				}
				if _, ok := seen[m]; ok {
					continue
				}
				seen[m] = struct{}{}
				out = append(out, m)
			}
			continue
		}
		if _, ok := seen[part]; !ok {
			seen[part] = struct{}{}
			out = append(out, part)
		}
	}
	return out
}

var fallbackNoticeOnce sync.Once

// 常见误配：SHARK_AIOPS_LOG_PATHS=access_*.json.log 在宿主机上无匹配，但存在 access.log / shark_access.log
func applyNginxAccessFallback(pathsRaw string, paths []string) []string {
	if len(paths) > 0 {
		return paths
	}
	if strings.TrimSpace(pathsRaw) == "" {
		return paths
	}
	candidates := []string{
		"/var/log/nginx/shark_access.log",
		"/var/log/nginx/access.log",
	}
	seen := make(map[string]struct{})
	var out []string
	for _, c := range candidates {
		if st, err := os.Stat(c); err != nil || st.IsDir() {
			continue
		}
		if _, ok := seen[c]; !ok {
			seen[c] = struct{}{}
			out = append(out, c)
		}
	}
	if len(out) > 0 {
		fallbackNoticeOnce.Do(func() {
			fmt.Fprintf(os.Stderr, "log-collector: 0 files matched %q; using fallback: %v (or set SHARK_AIOPS_LOG_PATHS explicitly)\n", pathsRaw, out)
		})
	}
	return out
}

var reAccessJSON = regexp.MustCompile(`(?i)^access_(.+)\.json\.log$`)

// 未设置 SHARK_AIOPS_STREAM_KEY 时，从文件名推导：access_api.json.log -> api，access_web_admin.json.log -> web_admin
func deriveStreamKey(globalKey, filePath string) string {
	if strings.TrimSpace(globalKey) != "" {
		return strings.TrimSpace(globalKey)
	}
	base := filepath.Base(filePath)
	if m := reAccessJSON.FindStringSubmatch(base); len(m) > 1 {
		return m[1]
	}
	if strings.HasSuffix(strings.ToLower(base), ".json.log") {
		s := strings.TrimSuffix(strings.TrimSuffix(base, ".log"), "")
		return s
	}
	return strings.TrimSuffix(strings.TrimSuffix(base, ".log"), "")
}

func inferLogFormatForPath(globalLF, filePath string) string {
	if strings.TrimSpace(globalLF) != "" {
		return strings.TrimSpace(globalLF)
	}
	b := strings.ToLower(filepath.Base(filePath))
	if strings.HasSuffix(b, ".json.log") {
		return "nginx_json"
	}
	return "auto"
}

func main() {
	// 非 TTY 下 stdout 可能被全缓冲，运维诊断一律写 stderr，docker logs 能立刻看到
	fmt.Fprintln(os.Stderr, "aiops-log-collector: process boot")
	center := strings.TrimRight(env("SHARK_AIOPS_CENTER_URL", "http://127.0.0.1:8000"), "/")
	token := env("SHARK_AIOPS_EDGE_TOKEN", "")
	source := env("SHARK_AIOPS_LOG_SOURCE", "edge")
	pathsRaw := env("SHARK_AIOPS_LOG_PATHS", "")
	batch := 100
	if v := strings.TrimSpace(env("SHARK_AIOPS_LOG_BATCH_SIZE", "")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 && n <= 2000 {
			batch = n
		}
	}
	severity := strings.ToLower(env("SHARK_AIOPS_LOG_SEVERITY", "error"))
	follow := envBool("SHARK_AIOPS_LOG_FOLLOW")
	fromEnd := true
	if follow {
		fromEnd = strings.TrimSpace(env("SHARK_AIOPS_LOG_FROM_END", "1")) != "0"
	}

	url := center + "/api/edge/logs"
	client := &http.Client{Timeout: 30 * time.Second}
	redactors := compileRedactors()

	parts := parsePaths(pathsRaw)
	paths := expandPathPatterns(parts)
	paths = applyNginxAccessFallback(pathsRaw, paths)
	globalStream := strings.TrimSpace(env("SHARK_AIOPS_STREAM_KEY", ""))
	globalLF := strings.TrimSpace(env("SHARK_AIOPS_LOG_FORMAT", ""))
	printStartupBanner(center, url, pathsRaw, paths, follow, fromEnd, globalStream, globalLF, severity, batch, token != "")
	hasGlob := false
	for _, p := range parts {
		if strings.ContainsAny(p, "*?[") {
			hasGlob = true
			break
		}
	}
	// 非 follow 或纯字面路径：无文件则失败。follow + glob：无匹配时保持运行并周期性重试（避免宿主机尚未写出日志时重启风暴）
	if len(paths) == 0 && pathsRaw != "" {
		if !(follow && hasGlob) {
			fmt.Fprintln(os.Stderr, "no files match patterns:", pathsRaw)
			os.Exit(1)
		}
		fmt.Fprintf(os.Stderr, "log-collector: no files yet, retrying glob every 45s: %s\n", pathsRaw)
	}

	if len(paths) == 0 {
		if pathsRaw == "" {
			runStdin(source, url, token, client, redactors, severity, batch)
			return
		}
		if !follow || !hasGlob {
			fmt.Fprintln(os.Stderr, "no files match patterns:", pathsRaw)
			os.Exit(1)
		}
	}

	if follow {
		lineCh := make(chan tailLine, 4096)
		active := make(map[string]struct{})
		var activeMu sync.Mutex

		startTail := func(p string) {
			activeMu.Lock()
			if _, ok := active[p]; ok {
				activeMu.Unlock()
				return
			}
			active[p] = struct{}{}
			activeMu.Unlock()
			go tailFileForever(p, fromEnd, lineCh)
		}

		for _, p := range paths {
			startTail(p)
		}

		// glob：立即扫一次，再每 45s 重扫（新文件、日志尚未创建）
		if hasGlob {
			go func() {
				rescan := func() {
					exp := applyNginxAccessFallback(pathsRaw, expandPathPatterns(parts))
					for _, p := range exp {
						startTail(p)
					}
				}
				rescan()
				tick := time.NewTicker(45 * time.Second)
				defer tick.Stop()
				for range tick.C {
					rescan()
				}
			}()
		}

		runConsumerMulti(lineCh, source, url, token, client, redactors, severity, batch, globalStream, globalLF)
		return
	}

	runFilesOnceMulti(paths, source, url, token, client, redactors, severity, batch, globalStream, globalLF)
}

func printStartupBanner(center, postURL, pathsRaw string, paths []string, follow, fromEnd bool, streamKey, logFormat, severity string, batch int, hasToken bool) {
	// 全部写 stderr，避免管道全缓冲时 docker logs 长时间空白
	f := os.Stderr
	fmt.Fprintln(f, "aiops-log-collector: starting")
	fmt.Fprintf(f, "  POST %s\n", postURL)
	fmt.Fprintf(f, "  center: %s\n", center)
	fmt.Fprintf(f, "  stream_key: %q  log_format: %q  severity: %s  batch: %d\n", streamKey, logFormat, severity, batch)
	fmt.Fprintf(f, "  X-Shark-Edge-Token set: %v (must match center SHARK_EDGE_TOKEN)\n", hasToken)
	fmt.Fprintf(f, "  follow: %v  from_end: %v  (set LOG_FROM_END=0 to ship existing tail once)\n", follow, fromEnd)
	fmt.Fprintf(f, "  SHARK_AIOPS_LOG_PATHS: %q\n", pathsRaw)
	fmt.Fprintf(f, "  file count (after glob+fallback): %d\n", len(paths))
	if len(paths) > 0 && len(paths) <= 20 {
		for _, p := range paths {
			fmt.Fprintf(f, "    - %s\n", p)
		}
	} else if len(paths) > 20 {
		for i := 0; i < 20; i++ {
			fmt.Fprintf(f, "    - %s\n", paths[i])
		}
		fmt.Fprintln(f, "    ...")
	}
	if len(paths) == 0 && pathsRaw != "" {
		fmt.Fprintln(f, "  NOTE: 0 files — e.g. use /var/log/nginx/access.log or see fallback message above on next rescan (45s).")
	}
	if strings.TrimSpace(pathsRaw) == "" {
		fmt.Fprintln(f, "  mode: no LOG_PATHS -> stdin in non-file mode only")
	}
	fmt.Fprintln(f, "aiops-log-collector: 60s stats on stderr; push HTTP errors on stderr")
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

type tailLine struct {
	path string
	line string
}

func runStdin(
	source, url, token string,
	client *http.Client,
	redactors []redactor,
	severity string,
	batch int,
) {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	sink := newBatchSink(source, url, token, client, batch, env("SHARK_AIOPS_STREAM_KEY", ""), env("SHARK_AIOPS_LOG_FORMAT", ""), "")
	tick := time.NewTicker(5 * time.Second)
	defer tick.Stop()
	go func() {
		for range tick.C {
			sink.flushAll()
		}
	}()
	for scanner.Scan() {
		line := processLine(scanner.Text(), redactors, severity)
		if line == "" {
			continue
		}
		sink.push(line)
	}
	sink.flushAll()
	if err := scanner.Err(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func runFilesOnceMulti(
	paths []string,
	source, url, token string,
	client *http.Client,
	redactors []redactor,
	severity string,
	batch int,
	globalStream, globalLF string,
) {
	sink := newBatchSink(source, url, token, client, batch, globalStream, globalLF, "")
	tick := time.NewTicker(5 * time.Second)
	defer tick.Stop()
	go func() {
		for range tick.C {
			sink.flushAll()
		}
	}()

	for _, path := range paths {
		sk := deriveStreamKey(globalStream, path)
		lf := inferLogFormatForPath(globalLF, path)
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
			sink.pushWithMeta(sk, lf, path, line)
		}
		_ = f.Close()
		if err := sc.Err(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}
	sink.flushAll()
}

func runConsumerMulti(
	lineCh <-chan tailLine,
	source, url, token string,
	client *http.Client,
	redactors []redactor,
	severity string,
	batch int,
	globalStream, globalLF string,
) {
	sink := newBatchSink(source, url, token, client, batch, globalStream, globalLF, "")
	tick := time.NewTicker(5 * time.Second)
	go func() {
		for range tick.C {
			sink.flushAll()
		}
	}()
	defer tick.Stop()

	var nDeq, nFwd, nSev int64
	go func() {
		hb := time.NewTicker(60 * time.Second)
		defer hb.Stop()
		for range hb.C {
			d := atomic.SwapInt64(&nDeq, 0)
			f := atomic.SwapInt64(&nFwd, 0)
			s := atomic.SwapInt64(&nSev, 0)
			if d == 0 && f == 0 && s == 0 {
				fmt.Fprintln(os.Stderr, "aiops-log-collector: last 60s: no log lines (empty glob? or LOG_FROM_END=1 and no new HTTP requests yet)")
				continue
			}
			fmt.Fprintf(os.Stderr, "aiops-log-collector: last 60s dequeued=%d dropped_filter=%d lines_sent_to_buffer=%d\n", d, s, f)
		}
	}()

	for tl := range lineCh {
		atomic.AddInt64(&nDeq, 1)
		line := processLine(tl.line, redactors, severity)
		if line == "" {
			atomic.AddInt64(&nSev, 1)
			continue
		}
		atomic.AddInt64(&nFwd, 1)
		sk := deriveStreamKey(globalStream, tl.path)
		lf := inferLogFormatForPath(globalLF, tl.path)
		sink.pushWithMeta(sk, lf, tl.path, line)
	}
	sink.flushAll()
}

type streamBatch struct {
	lines      []string
	logFormat  string
	sourceFile string
}

type batchSink struct {
	mu         sync.Mutex
	buckets    map[string]*streamBatch
	sourceTag  string
	url        string
	token      string
	client     *http.Client
	batchSize  int
	globalSk   string
	globalLF   string
	stdinLabel string
	firstOK    sync.Once
}

func newBatchSink(sourceTag, url, token string, client *http.Client, batchSize int, globalSk, globalLF, stdinLabel string) *batchSink {
	return &batchSink{
		buckets:    make(map[string]*streamBatch),
		sourceTag:  sourceTag,
		url:        url,
		token:      token,
		client:     client,
		batchSize:  batchSize,
		globalSk:   globalSk,
		globalLF:   globalLF,
		stdinLabel: stdinLabel,
	}
}

func (s *batchSink) bucketFor(streamKey, logFormat, sourceFile string) *streamBatch {
	b := s.buckets[streamKey]
	if b == nil {
		b = &streamBatch{lines: make([]string, 0, s.batchSize), logFormat: logFormat, sourceFile: sourceFile}
		s.buckets[streamKey] = b
	}
	return b
}

func (s *batchSink) push(line string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	sk := strings.TrimSpace(s.globalSk)
	if sk == "" {
		sk = "stdin"
	}
	lf := strings.TrimSpace(s.globalLF)
	if lf == "" {
		lf = "auto"
	}
	b := s.bucketFor(sk, lf, s.stdinLabel)
	b.lines = append(b.lines, line)
	if len(b.lines) >= s.batchSize {
		s.flushOneUnlocked(sk, b)
		delete(s.buckets, sk)
	}
}

func (s *batchSink) pushWithMeta(streamKey, logFormat, sourceFile, line string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b := s.bucketFor(streamKey, logFormat, sourceFile)
	b.lines = append(b.lines, line)
	if len(b.lines) >= s.batchSize {
		s.flushOneUnlocked(streamKey, b)
		delete(s.buckets, streamKey)
	}
}

func (s *batchSink) flushOneUnlocked(streamKey string, b *streamBatch) {
	if len(b.lines) == 0 {
		return
	}
	payload := map[string]any{
		"source":      s.sourceTag,
		"lines":       b.lines,
		"stream_key":  streamKey,
		"log_format":  b.logFormat,
		"source_file": b.sourceFile,
	}
	body, _ := json.Marshal(payload)
	req, _ := http.NewRequest(http.MethodPost, s.url, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if s.token != "" {
		req.Header.Set("X-Shark-Edge-Token", s.token)
	}
	resp, err := s.client.Do(req)
	if err != nil {
		fmt.Fprintln(os.Stderr, "push:", err)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		var tail [512]byte
		n, _ := io.ReadFull(resp.Body, tail[:])
		msg := string(tail[:n])
		if n == len(tail) {
			msg += "…"
		}
		fmt.Fprintf(os.Stderr, "push: HTTP %s %s\n", resp.Status, strings.TrimSpace(msg))
		return
	}
	nLines := len(b.lines)
	s.firstOK.Do(func() {
		fmt.Fprintf(os.Stderr, "aiops-log-collector: first batch accepted by center HTTP %s (%d lines, stream_key=%s)\n", resp.Status, nLines, streamKey)
	})
}

func (s *batchSink) flushAll() {
	s.mu.Lock()
	defer s.mu.Unlock()
	for sk, b := range s.buckets {
		if len(b.lines) == 0 {
			continue
		}
		s.flushOneUnlocked(sk, b)
		b.lines = b.lines[:0]
	}
}

func processLine(raw string, redactors []redactor, severity string) string {
	line := applyRedaction(raw, redactors)
	if !shouldForward(line, severity) {
		return ""
	}
	return line
}

func tailFileForever(path string, startAtEnd bool, out chan<- tailLine) {
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
			firstLine := true
			for sc.Scan() {
				if firstLine {
					fmt.Fprintf(os.Stderr, "aiops-log-collector: first line from %s\n", path)
					firstLine = false
				}
				out <- tailLine{path: path, line: sc.Text()}
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
