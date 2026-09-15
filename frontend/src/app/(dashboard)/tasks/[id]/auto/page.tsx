"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ToolTimeline } from "@/components/auto-mode/tool-timeline";
import { VulnFindings } from "@/components/auto-mode/vuln-findings";
import { useScanStore } from "@/stores/scan-store";

export default function AutoModePage() {
  const params = useParams();
  const router = useRouter();
  const taskId = params.id as string;
  const { session, isLoading, loadSession, reset } = useScanStore();

  useEffect(() => {
    loadSession(taskId);
    return () => reset();
  }, [taskId, loadSession, reset]);

  if (isLoading) {
    return <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>;
  }

  if (!session) {
    return (
      <div className="text-center py-20">
        <p className="text-muted-foreground">扫描尚未开始，请先启动任务</p>
        <Button variant="outline" className="mt-4" onClick={() => router.push("/tasks")}>返回任务列表</Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={() => router.push(`/tasks/${taskId}`)} className="gap-1">
        <ArrowLeft className="h-4 w-4" />返回任务
      </Button>

      <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">
        <div className="xl:col-span-3">
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-sm">扫描进度 ({session.overallProgress}%)</CardTitle></CardHeader>
            <CardContent>
              <ToolTimeline tools={(session as any).tools || []} />
            </CardContent>
          </Card>
        </div>
        <div className="xl:col-span-2">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">漏洞发现 ({(session as any).vulnerabilities?.length || 0})</CardTitle>
            </CardHeader>
            <CardContent>
              <VulnFindings vulnerabilities={(session as any).vulnerabilities || []} />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
