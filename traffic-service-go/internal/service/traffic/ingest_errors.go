package traffic

import "errors"

// ErrIngestShuttingDown 优雅停机阶段拒绝继续入队。
var ErrIngestShuttingDown = errors.New("traffic ingest shutting down")
