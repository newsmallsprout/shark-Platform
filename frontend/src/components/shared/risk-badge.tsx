"use client";

// ============================================================
// src/components/shared/risk-badge.tsx — 漏洞等级 Badge
// ============================================================

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { SEVERITY_MAP } from "@/lib/utils";
import type { Severity } from "@/types/task";

interface RiskBadgeProps {
  severity: Severity;
  className?: string;
  /** 是否只显示颜色点 */
  dotOnly?: boolean;
}

const SIZE_MAP: Record<Severity, string> = {
  critical: "h-2.5 w-2.5",
  high: "h-2 w-2",
  medium: "h-2 w-2",
  low: "h-1.5 w-1.5",
  info: "h-1.5 w-1.5",
};

export function RiskBadge({ severity, className, dotOnly = false }: RiskBadgeProps) {
  const config = SEVERITY_MAP[severity];

  if (dotOnly) {
    return (
      <span
        className={cn("inline-block rounded-full", SIZE_MAP[severity])}
        style={{ backgroundColor: config.color }}
        title={config.label}
      />
    );
  }

  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 font-medium",
        config.bgClass,
        config.textClass,
        config.borderClass,
        className
      )}
    >
      <span
        className="inline-block rounded-full h-1.5 w-1.5"
        style={{ backgroundColor: config.color }}
      />
      {config.label}
    </Badge>
  );
}
