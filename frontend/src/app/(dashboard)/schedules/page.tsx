"use client";

// ============================================================
// src/app/(dashboard)/schedules/page.tsx — 排班
// shark Schedules/Index.vue → Next.js
// ============================================================

import { useEffect, useState } from "react";
import { platformApi } from "@/lib/api/client";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";

export default function SchedulesPage() {
  const [schedules, setSchedules] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await platformApi.get("/schedules/");
        setSchedules(data.data || data || []);
      } catch {
        toast.error("加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">排班</h1>
        <p className="text-sm text-muted-foreground">值班表、电话告警回调</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>值班表</CardTitle>
          <CardDescription>排班规则与值班人员</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>时间</TableHead>
                <TableHead>值班人</TableHead>
                <TableHead>规则 ID</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {schedules.length === 0 && (
                <TableRow><TableCell colSpan={4} className="py-8 text-center text-muted-foreground">暂无排班数据</TableCell></TableRow>
              )}
              {schedules.map((s, i) => (
                <TableRow key={s.id || i}>
                  <TableCell className="font-medium">{s.shiftDate || s.shift_date || "-"}</TableCell>
                  <TableCell>{s.startTime ? `${s.startTime} - ${s.endTime}` : "-"}</TableCell>
                  <TableCell>
                    {(s.staffList || []).map((st: any) => (
                      <Badge key={st.id} variant="secondary" className="mr-1">{st.name}</Badge>
                    ))}
                    {(!s.staffList || s.staffList.length === 0) && "-"}
                  </TableCell>
                  <TableCell>{s.ruleId ?? s.rule_id ?? "-"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
