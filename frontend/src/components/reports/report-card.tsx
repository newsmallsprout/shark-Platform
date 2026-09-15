"use client";

// ============================================================
// src/components/reports/report-card.tsx — 报告卡片
// ============================================================

import { useRouter } from "next/navigation";
import { FileText, ExternalLink, Edit3 } from "lucide-react";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RiskBadge } from "@/components/shared/risk-badge";
import { formatRelativeTime } from "@/lib/utils";
import { REPORT_STATUS_CONFIG } from "@/types/report";
import type { Report } from "@/types/report";

interface ReportCardProps {
  report: Report;
}

export function ReportCard({ report }: ReportCardProps) {
  const router = useRouter();
  const statusCfg = REPORT_STATUS_CONFIG[report.status];

  return (
    <Card className="hover:border-primary/30 transition-colors">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <FileText className="h-4 w-4 text-muted-foreground flex-shrink-0" />
            <h3 className="text-sm font-medium truncate">{report.title}</h3>
          </div>
          <Badge variant={statusCfg.variant} className="flex-shrink-0 text-[10px]">
            {statusCfg.label}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="pb-2 space-y-2">
        {/* 目标 & 等级 */}
        <div className="flex items-center gap-2">
          <RiskBadge severity={report.summary.overallSeverity} />
          <span className="text-xs text-muted-foreground truncate">
            {report.summary.targetUrl}
          </span>
        </div>

        {/* 漏洞计数 */}
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <span>漏洞: {report.totalVulns}</span>
          <span>·</span>
          <span>
            {report.summary.scanMode === "auto" ? "自动扫描" : "引导模式"}
          </span>
          <span>·</span>
          <span>{formatRelativeTime(report.updatedAt)}</span>
        </div>

        {/* 漏洞严重度概要 */}
        <div className="flex gap-1">
          {report.summary.vulnCount.critical > 0 && (
            <span className="text-[10px] text-red-400 tabular-nums">
              {report.summary.vulnCount.critical}严重
            </span>
          )}
          {report.summary.vulnCount.high > 0 && (
            <span className="text-[10px] text-orange-400 tabular-nums">
              {report.summary.vulnCount.high}高危
            </span>
          )}
          {report.summary.vulnCount.medium > 0 && (
            <span className="text-[10px] text-yellow-400 tabular-nums">
              {report.summary.vulnCount.medium}中危
            </span>
          )}
        </div>
      </CardContent>

      <CardFooter className="pt-0 gap-2">
        <Button
          variant="secondary"
          size="sm"
          className="gap-1"
          onClick={() => router.push(`/reports/${report.id}`)}
        >
          <ExternalLink className="h-3 w-3" />
          查看
        </Button>
        {report.status === "draft" && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1"
            onClick={() => router.push(`/reports/${report.id}`)}
          >
            <Edit3 className="h-3 w-3" />
            编辑
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
