"use client";

// ============================================================
// src/components/auto-mode/tool-timeline.tsx — 工具执行时间线
// ============================================================

import {
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import { cn, formatDuration } from "@/lib/utils";
import type { ScanTool, ToolStatus } from "@/types/scan";
import { SCAN_TOOL_LABELS } from "@/types/scan";

interface ToolTimelineProps {
  tools: ScanTool[];
}

const STATUS_ICON: Record<ToolStatus, React.ReactNode> = {
  pending: <Clock className="h-3.5 w-3.5 text-muted-foreground" />,
  running: <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin" />,
  completed: <CheckCircle2 className="h-3.5 w-3.5 text-green-400" />,
  failed: <XCircle className="h-3.5 w-3.5 text-red-400" />,
  timeout: <AlertTriangle className="h-3.5 w-3.5 text-yellow-400" />,
};

export function ToolTimeline({ tools }: ToolTimelineProps) {
  return (
    <div className="space-y-0">
      {tools.map((tool, idx) => {
        const isLast = idx === tools.length - 1;
        const duration =
          tool.startedAt && tool.completedAt
            ? Math.floor(
                (new Date(tool.completedAt).getTime() -
                  new Date(tool.startedAt).getTime()) /
                  1000
              )
            : undefined;

        return (
          <div key={tool.id} className="flex gap-3">
            {/* 时间线竖线 */}
            <div className="flex flex-col items-center">
              <div className="mt-1">{STATUS_ICON[tool.status]}</div>
              {!isLast && (
                <div
                  className={cn(
                    "w-px flex-1 min-h-[20px]",
                    tool.status === "completed"
                      ? "bg-green-500/30"
                      : "bg-border"
                  )}
                />
              )}
            </div>

            {/* 工具信息 */}
            <div className={cn("pb-3 flex-1 min-w-0", isLast && "pb-0")}>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">
                  {SCAN_TOOL_LABELS[tool.type] ?? tool.name}
                </span>
                {duration !== undefined && (
                  <span className="text-[10px] text-muted-foreground font-mono">
                    {formatDuration(duration)}
                  </span>
                )}
              </div>
              {tool.command && (
                <p className="text-[11px] text-muted-foreground font-mono truncate mt-0.5">
                  $ {tool.command}
                </p>
              )}
              {(tool.assetsFound > 0 || tool.vulnsFound > 0) && (
                <div className="flex gap-3 mt-1 text-[11px]">
                  {tool.assetsFound > 0 && (
                    <span className="text-blue-400">
                      资产: {tool.assetsFound}
                    </span>
                  )}
                  {tool.vulnsFound > 0 && (
                    <span className="text-red-400">
                      漏洞: {tool.vulnsFound}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
