"use client";

// ============================================================
// src/components/auto-mode/scan-dashboard.tsx — 主控面板
// ============================================================

import { Pause, Play, Square, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { cn, formatDuration } from "@/lib/utils";
import type { ScanSession, StageProgress } from "@/types/scan";
import { SCAN_STAGE_LABELS } from "@/types/scan";

interface ScanDashboardProps {
  session: ScanSession;
  isRunning: boolean;
  onPauseResume: () => void;
  onStop: () => void;
}

export function ScanDashboard({
  session,
  isRunning,
  onPauseResume,
  onStop,
}: ScanDashboardProps) {
  const currentStageLabel =
    SCAN_STAGE_LABELS[session.currentStage] ?? session.currentStage;

  // 计算已过时间
  const elapsed = session.startedAt
    ? Math.floor(
        (Date.now() - new Date(session.startedAt).getTime()) / 1000
      )
    : 0;

  return (
    <div className="space-y-4 p-4 rounded-lg border border-border bg-card">
      {/* 状态栏 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {/* 脉冲指示器 */}
          {isRunning && <span className="scan-indicator" />}
          <div>
            <h2 className="font-semibold text-sm">
              {isRunning ? "扫描进行中" : "扫描已暂停"}
            </h2>
            <p className="text-xs text-muted-foreground">
              当前阶段: {currentStageLabel} · 已运行 {formatDuration(elapsed)}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onPauseResume}
          >
            {isRunning ? (
              <>
                <Pause className="h-3.5 w-3.5 mr-1" />
                暂停
              </>
            ) : (
              <>
                <Play className="h-3.5 w-3.5 mr-1" />
                继续
              </>
            )}
          </Button>
          <Button variant="outline" size="sm" onClick={onStop}>
            <Square className="h-3.5 w-3.5 mr-1" />
            停止
          </Button>
        </div>
      </div>

      {/* 全局进度 */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>总体进度</span>
          <span className="font-mono">{session.overallProgress}%</span>
        </div>
        <Progress value={session.overallProgress} className="h-2" />
      </div>

      {/* 各阶段状态 */}
      <div className="grid grid-cols-7 gap-1">
        {session.stages.map((s) => (
          <StageDot key={s.stage} stage={s} />
        ))}
      </div>

      {/* 阶段标签 */}
      <div className="flex justify-between text-[10px] text-muted-foreground">
        {session.stages.map((s) => (
          <span key={s.stage} className="text-center w-full">
            {SCAN_STAGE_LABELS[s.stage]?.slice(0, 2) ?? s.stage}
          </span>
        ))}
      </div>
    </div>
  );
}

// ---- 阶段圆点 ----

function StageDot({ stage }: { stage: StageProgress }) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <div
        className={cn(
          "h-2.5 w-full rounded-sm",
          stage.status === "completed"
            ? "bg-green-500"
            : stage.status === "running"
            ? "bg-primary animate-scan-pulse"
            : stage.status === "failed"
            ? "bg-red-500"
            : "bg-muted"
        )}
      />
    </div>
  );
}
