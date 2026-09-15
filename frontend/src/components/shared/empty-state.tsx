"use client";

// ============================================================
// src/components/shared/empty-state.tsx — 空状态占位组件
// ============================================================

import { type LucideIcon, Inbox } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  /** 图标（默认 Inbox） */
  icon?: LucideIcon;
  /** 标题 */
  title: string;
  /** 描述文本 */
  description?: string;
  /** 操作按钮文字 */
  actionLabel?: string;
  /** 操作按钮点击回调 */
  onAction?: () => void;
  className?: string;
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  actionLabel,
  onAction,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center py-16 px-4",
        "text-center",
        className
      )}
    >
      {/* 图标 */}
      <div className="rounded-full bg-muted/50 p-4 mb-4">
        <Icon className="h-8 w-8 text-muted-foreground" />
      </div>

      {/* 标题 */}
      <h3 className="text-lg font-semibold text-foreground mb-1">
        {title}
      </h3>

      {/* 描述 */}
      {description && (
        <p className="text-sm text-muted-foreground max-w-sm mb-4">
          {description}
        </p>
      )}

      {/* 操作按钮 */}
      {actionLabel && onAction && (
        <Button onClick={onAction} size="sm">
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
