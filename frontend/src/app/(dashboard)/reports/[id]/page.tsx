"use client";

// ============================================================
// src/app/(dashboard)/reports/[id]/page.tsx — 报告详情（真实 API）
// ============================================================

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Send, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { RiskBadge } from "@/components/shared/risk-badge";
import { REPORT_STATUS_CONFIG } from "@/types/report";
import type { Report } from "@/types/report";
import { getReportById } from "@/lib/api/reports";

export default function ReportDetailPage() {
  const params = useParams();
  const router = useRouter();
  const reportId = params.id as string;

  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getReportById(reportId).then(setReport).finally(() => setLoading(false));
  }, [reportId]);

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>;
  if (!report) return <div className="text-center py-20"><p className="text-muted-foreground">报告不存在</p></div>;

  const statusCfg = REPORT_STATUS_CONFIG[report.status];
  const content = (report as any).edited_content || report.content || "";

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <Button variant="ghost" size="sm" onClick={() => router.push("/reports")} className="gap-1">
        <ArrowLeft className="h-4 w-4" />返回
      </Button>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{report.title}</h1>
          <p className="text-sm text-muted-foreground mt-1">总体评级</p>
        </div>
        <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Card><CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">评级</CardTitle></CardHeader>
          <CardContent><RiskBadge severity={(report as any).severity || "info"} /></CardContent></Card>
        <Card><CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">漏洞</CardTitle></CardHeader>
          <CardContent><span className="text-2xl font-bold">{report.totalVulns}</span></CardContent></Card>
        <Card><CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground">状态</CardTitle></CardHeader>
          <CardContent><Badge variant={statusCfg.variant}>{statusCfg.label}</Badge></CardContent></Card>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-sm">报告正文</CardTitle></CardHeader>
        <CardContent><MarkdownRenderer content={content} /></CardContent>
      </Card>
    </div>
  );
}
