"use client";

// ============================================================
// src/components/guided-mode/stage-progress.tsx — 阶段进度条
// ============================================================

import { cn } from "@/lib/utils";
import { Check, Loader2 } from "lucide-react";
import type { GuidedStage } from "@/types/chat";
import { GUIDED_STAGE_LABELS } from "@/types/chat";

interface StageProgressProps {
  stages: Array<{
    stage: GuidedStage;
    status: "waiting" | "active" | "completed" | "skipped";
  }>;
  currentStage: GuidedStage;
}

export function StageProgress({ stages, currentStage }: StageProgressProps) {
  return (
    <div className="flex items-center gap-0 w-full">
      {stages.map((s, idx) => {
        const isActive = s.stage === currentStage || s.status === "active";
        const isCompleted = s.status === "completed";
        const isLast = idx === stages.length - 1;

        return (
          <div key={s.stage} className="flex items-center flex-1">
            {/* 圆点 + 标签 */}
            <div className="flex flex-col items-center gap-1 min-w-0">
              <div
                className={cn(
                  "flex items-center justify-center h-7 w-7 rounded-full text-xs font-medium transition-colors",
                  isCompleted &&
                    "bg-green-500/20 text-green-400 border border-green-500/30",
                  isActive &&
                    "bg-primary/20 text-primary border border-primary/30",
                  !isCompleted &&
                    !isActive &&
                    "bg-muted text-muted-foreground border border-border"
                )}
              >
                {isCompleted ? (
                  <Check className="h-3.5 w-3.5" />
                ) : isActive ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  idx + 1
                )}
              </div>
              <span
                className={cn(
                  "text-[9px] text-center leading-tight",
                  isActive
                    ? "text-primary font-medium"
                    : isCompleted
                    ? "text-green-400"
                    : "text-muted-foreground"
                )}
              >
                {GUIDED_STAGE_LABELS[s.stage] ?? s.stage}
              </span>
            </div>

            {/* 连接线 */}
            {!isLast && (
              <div
                className={cn(
                  "h-0.5 flex-1 mx-1 -mt-3",
                  isCompleted ? "bg-green-500/30" : "bg-border"
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
