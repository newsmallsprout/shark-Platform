"use client";

// ============================================================
// src/components/auto-mode/scan-terminal.tsx — xterm.js 终端
// ============================================================

import { useEffect, useRef } from "react";
import type { ScanLogEntry } from "@/types/scan";

interface ScanTerminalProps {
  logs: ScanLogEntry[];
  maxHeight?: string;
}

const LEVEL_COLORS: Record<string, string> = {
  info: "#6b7280",
  warn: "#f59e0b",
  error: "#ef4444",
  debug: "#8b5cf6",
  success: "#22c55e",
};

function formatLog(entry: ScanLogEntry): string {
  const time = new Date(entry.timestamp).toLocaleTimeString("zh-CN", {
    hour12: false,
  });
  const color = LEVEL_COLORS[entry.level] ?? "#6b7280";
  return `[${time}] [${entry.source}] ${entry.message}`;
}

export function ScanTerminal({ logs, maxHeight = "400px" }: ScanTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div
      ref={containerRef}
      className="xterm-container font-mono-terminal"
      style={{ maxHeight }}
    >
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border/50 bg-muted/30">
        <span className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-yellow-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-green-500/70" />
        <span className="text-[10px] text-muted-foreground ml-2">
          终端输出 — scan-terminal
        </span>
      </div>

      <div
        ref={scrollRef}
        className="overflow-auto p-3"
        style={{ maxHeight: `calc(${maxHeight} - 28px)` }}
      >
        <pre className="text-xs leading-relaxed whitespace-pre-wrap break-all text-muted-foreground font-mono">
          {logs.length === 0 ? (
            <span className="text-muted-foreground/50">
              等待扫描开始...
            </span>
          ) : (
            logs.map((log, idx) => (
              <div
                key={idx}
                className="hover:bg-muted/20 px-1 -mx-1 rounded"
                style={{
                  color:
                    log.level === "success"
                      ? "#22c55e"
                      : log.level === "warn"
                      ? "#f59e0b"
                      : log.level === "error"
                      ? "#ef4444"
                      : "#9ca3af",
                }}
              >
                {formatLog(log)}
              </div>
            ))
          )}
        </pre>
      </div>
    </div>
  );
}
