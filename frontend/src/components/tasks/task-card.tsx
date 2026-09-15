"use client";

// ============================================================
// src/components/tasks/task-card.tsx — 任务卡片
// ============================================================

import { useRouter } from "next/navigation";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { StatusBadge } from "@/components/shared/status-badge";
import { RiskBadge } from "@/components/shared/risk-badge";
import {
  Shield,
  Box,
  Target,
  Zap,
  Users,
  ExternalLink,
  Play,
  Square,
  Eye,
  Trash2,
} from "lucide-react";
import { cn, formatRelativeTime, PLATFORM_MAP, MODE_MAP } from "@/lib/utils";
import type { Task, Severity } from "@/types/task";

interface TaskCardProps {
  task: Task;
  onStart?: (id: string) => void;
  onCancel?: (id: string) => void;
  onDelete?: (id: string) => void;
}

const PLATFORM_ICON: Record<string, React.ReactNode> = {
  butian: <Shield className="h-3.5 w-3.5" />,
  vulbox: <Box className="h-3.5 w-3.5" />,
  custom: <Target className="h-3.5 w-3.5" />,
};

const MODE_ICON: Record<string, React.ReactNode> = {
  auto: <Zap className="h-3.5 w-3.5" />,
  guided: <Users className="h-3.5 w-3.5" />,
};

export function TaskCard({ task, onStart, onCancel, onDelete }: TaskCardProps) {
  const router = useRouter();

  const isRunning = task.status === "running" || task.status === "analyzing";
  const isDone = task.status === "completed";
  const isFailed = task.status === "failed";

  const vulnSum =
    task.vulnCount.critical +
    task.vulnCount.high +
    task.vulnCount.medium +
    task.vulnCount.low +
    task.vulnCount.info;

  const handleContinue = () => {
    // allowAutoScan=false → 强制走 guided
    if (!task.scope.allowAutoScan) {
      router.push(`/tasks/${task.id}/guided`);
    } else if (task.mode === "guided") {
      router.push(`/tasks/${task.id}/guided`);
    } else {
      router.push(`/tasks/${task.id}/auto`);
    }
  };

  return (
    <Card
      className={cn(
        "hover:border-primary/30 transition-colors group",
        isRunning && "border-primary/20"
      )}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm font-medium leading-snug line-clamp-2">
            {task.title}
          </CardTitle>
        </div>

        {/* 标签行 */}
        <div className="flex flex-wrap items-center gap-1.5 mt-2">
          <Badge variant="outline" className="gap-1 text-[10px]">
            {PLATFORM_ICON[task.platform]}
            {PLATFORM_MAP[task.platform].label}
          </Badge>
          <Badge variant="secondary" className="gap-1 text-[10px]">
            {MODE_ICON[task.mode]}
            {MODE_MAP[task.mode].label}
          </Badge>
          <StatusBadge status={task.status} />
        </div>
      </CardHeader>

      <CardContent className="pb-3 space-y-3">
        {/* 目标 URL */}
        <p className="text-xs text-muted-foreground truncate">
          {task.scope.targetUrl}
        </p>

        {/* 进度条（运行中时显示） */}
        {isRunning && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>扫描进度</span>
              <span>{task.progress}%</span>
            </div>
            <Progress value={task.progress} className="h-1.5" />
          </div>
        )}

        {/* 漏洞计数 */}
        {vulnSum > 0 && (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1">
              <RiskBadge severity="critical" dotOnly />
              <span className="text-xs tabular-nums">{task.vulnCount.critical}</span>
            </div>
            <div className="flex items-center gap-1">
              <RiskBadge severity="high" dotOnly />
              <span className="text-xs tabular-nums">{task.vulnCount.high}</span>
            </div>
            <div className="flex items-center gap-1">
              <RiskBadge severity="medium" dotOnly />
              <span className="text-xs tabular-nums">{task.vulnCount.medium}</span>
            </div>
            <div className="flex items-center gap-1">
              <RiskBadge severity="low" dotOnly />
              <span className="text-xs tabular-nums">{task.vulnCount.low}</span>
            </div>
          </div>
        )}

        {/* 时间 */}
        <p className="text-[11px] text-muted-foreground">
          {formatRelativeTime(task.updatedAt)}
          {task.assignee && ` · ${task.assignee}`}
        </p>
      </CardContent>

      <CardFooter className="pt-0 gap-2">
        {isRunning && onCancel && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1"
            onClick={(e) => {
              e.stopPropagation();
              onCancel(task.id);
            }}
          >
            <Square className="h-3 w-3" />
            停止
          </Button>
        )}

        {task.status === "pending" && onStart && (
          <Button
            size="sm"
            className="gap-1"
            onClick={(e) => {
              e.stopPropagation();
              onStart(task.id);
            }}
          >
            <Play className="h-3 w-3" />
            开始
          </Button>
        )}

        {(isRunning || isDone || isFailed) && (
          <Button
            variant="secondary"
            size="sm"
            className="gap-1"
            onClick={(e) => {
              e.stopPropagation();
              handleContinue();
            }}
          >
            {isRunning ? (
              <>
                <Eye className="h-3 w-3" />
                查看
              </>
            ) : (
              <>
                <ExternalLink className="h-3 w-3" />
                详情
              </>
            )}
          </Button>
        )}

        {onDelete && (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 ml-auto text-muted-foreground hover:text-destructive"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(task.id);
            }}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
