"use client";

// ============================================================
// src/app/(dashboard)/logs/page.tsx — 日志监控
// shark LogMonitor/Index.vue → Next.js
// ============================================================

import { useEffect, useState } from "react";
import { platformApi } from "@/lib/api/client";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";

export default function LogsPage() {
  const [tasks, setTasks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<any>(null);
  const [files, setFiles] = useState<any[]>([]);
  const [content, setContent] = useState("");

  const loadTasks = async () => {
    try {
      const { data } = await platformApi.get("/monitor/tasks");
      setTasks(Array.isArray(data) ? data : data.tasks || []);
    } catch {
      toast.error("加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTasks();
  }, []);

  const selectTask = async (t: any) => {
    setSelected(t);
    try {
      const { data } = await platformApi.get("/monitor/logs", { params: { task_id: t.id } });
      setFiles(data.files || []);
    } catch {
      setFiles([]);
    }
  };

  const viewLog = async (filename: string) => {
    try {
      const { data } = await platformApi.get("/monitor/logs/view", {
        params: { task_id: selected.id, filename },
        timeout: 120000,
      });
      setContent(data.content || "");
    } catch (e: any) {
      toast.error(e?.response?.data?.error || "读取失败");
    }
  };

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">日志监控</h1>
        <p className="text-sm text-muted-foreground">K8s Pod 日志扫描、告警</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>监控任务</CardTitle>
            <CardDescription>选择任务查看日志文件</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow><TableHead>名称</TableHead><TableHead>命名空间</TableHead><TableHead>状态</TableHead><TableHead>操作</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {tasks.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">{t.name}</TableCell>
                    <TableCell>{t.k8s_namespace}</TableCell>
                    <TableCell>
                      <Badge variant={t.enabled ? "default" : "secondary"}>{t.enabled ? "启用" : "停用"}</Badge>
                    </TableCell>
                    <TableCell>
                      <Button size="sm" variant="outline" onClick={() => selectTask(t)}>查看日志</Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>日志文件{selected ? ` — ${selected.name}` : ""}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="max-h-64 space-y-1 overflow-auto rounded border p-2">
              {files.length === 0 && <p className="text-sm text-muted-foreground">请先选择左侧任务</p>}
              {files.map((f) => (
                <button
                  key={f.filename || f}
                  onClick={() => viewLog(f.filename || f)}
                  className="block w-full rounded px-2 py-1 text-left text-sm hover:bg-muted"
                >
                  {f.filename || f}
                </button>
              ))}
            </div>
            <Textarea value={content} readOnly rows={12} placeholder="日志内容..." className="font-mono text-xs" />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
