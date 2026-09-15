"use client";

// ============================================================
// src/components/shared/status-badge.tsx — 任务状态 Badge
// ============================================================

import { Badge } from "@/components/ui/badge";
import {
  CircleDot,
  Play,
  Brain,
  CheckCircle,
  XCircle,
  Ban,
} from "lucide-react";
import type { TaskStatus } from "@/types/task";

interface StatusBadgeProps {
  status: TaskStatus;
}

const STATUS_ICON: Record<TaskStatus, React.ReactNode> = {
  pending: <CircleDot className="h-3 w-3" />,
  running: <Play className="h-3 w-3" />,
  analyzing: <Brain className="h-3 w-3" />,
  completed: <CheckCircle className="h-3 w-3" />,
  failed: <XCircle className="h-3 w-3" />,
  cancelled: <Ban className="h-3 w-3" />,
};

const STATUS_VARIANT: Record<
  TaskStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  pending: "secondary",
  running: "default",
  analyzing: "default",
  completed: "outline",
  failed: "destructive",
  cancelled: "secondary",
};

const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: "待开始",
  running: "扫描中",
  analyzing: "分析中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <Badge variant={STATUS_VARIANT[status]} className="gap-1">
      {STATUS_ICON[status]}
      {STATUS_LABEL[status]}
    </Badge>
  );
}
