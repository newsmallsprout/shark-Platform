"use client";

// ============================================================
// src/app/(dashboard)/dashboard/page.tsx — 仪表盘概览
// ============================================================

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Target,
  AlertTriangle,
  FileCheck,
  TrendingUp,
  Clock,
  ChevronRight,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/shared/status-badge";
import { RiskBadge } from "@/components/shared/risk-badge";
import { useTaskStore } from "@/stores/task-store";
import { formatRelativeTime, cn } from "@/lib/utils";
import { PLATFORM_MAP } from "@/lib/utils";
import type { Task } from "@/types/task";

// ---- 统计卡片 ----

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ReactNode;
  trend?: { value: number; label: string };
}

function StatCard({ title, value, subtitle, icon, trend }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <div className="text-muted-foreground">{icon}</div>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {subtitle && (
          <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
        )}
        {trend && (
          <div className="flex items-center gap-1 mt-2">
            <TrendingUp
              className={cn(
                "h-3 w-3",
                trend.value >= 0 ? "text-green-400" : "text-red-400"
              )}
            />
            <span
              className={cn(
                "text-xs",
                trend.value >= 0 ? "text-green-400" : "text-red-400"
              )}
            >
              {trend.value >= 0 ? "+" : ""}
              {trend.value}%
            </span>
            <span className="text-xs text-muted-foreground">{trend.label}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---- 最近活动时间线 ----

interface ActivityItem {
  id: string;
  action: string;
  target: string;
  time: string;
  severity?: string;
}

const MOCK_ACTIVITIES: ActivityItem[] = [
  {
    id: "1",
    action: "扫描完成",
    target: "某电商平台 SQL 注入检测",
    time: "2026-07-30T14:30:00Z",
  },
  {
    id: "2",
    action: "发现漏洞",
    target: "某互金平台 — CSRF in Transfer API [高危]",
    time: "2026-07-31T08:20:00Z",
    severity: "high",
  },
  {
    id: "3",
    action: "报告已提交",
    target: "某省级政务服务平台安全评估报告",
    time: "2026-07-30T10:00:00Z",
  },
  {
    id: "4",
    action: "引导会话启动",
    target: "某政务平台 — 信息收集阶段",
    time: "2026-07-31T08:35:00Z",
  },
  {
    id: "5",
    action: "任务失败",
    target: "某教育平台任意文件上传检测",
    time: "2026-07-30T14:05:00Z",
  },
];

// ---- Task 卡片（最近任务列表用） ----

function RecentTaskRow({ task }: { task: Task }) {
  const router = useRouter();

  return (
    <div
      className="flex items-center justify-between py-3 px-1 hover:bg-muted/50 rounded-md cursor-pointer transition-colors group"
      onClick={() => router.push(`/tasks/${task.id}`)}
    >
      <div className="flex items-center gap-3 min-w-0">
        <StatusBadge status={task.status} />
        <div className="min-w-0">
          <p className="text-sm font-medium truncate">{task.title}</p>
          <p className="text-xs text-muted-foreground">
            {PLATFORM_MAP[task.platform].label} ·{" "}
            {task.mode === "auto" ? "自动" : "引导"}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <div className="hidden sm:flex items-center gap-1.5">
          <RiskBadge severity="critical" dotOnly />
          <span className="text-xs tabular-nums w-4 text-right">
            {task.vulnCount.critical}
          </span>
          <RiskBadge severity="high" dotOnly />
          <span className="text-xs tabular-nums w-4 text-right">
            {task.vulnCount.high + task.vulnCount.critical}
          </span>
          <RiskBadge severity="medium" dotOnly />
          <span className="text-xs tabular-nums w-4 text-right">
            {task.vulnCount.medium}
          </span>
        </div>
        <span className="text-xs text-muted-foreground">
          {formatRelativeTime(task.updatedAt)}
        </span>
        <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
    </div>
  );
}

// ---- 主页面 ----

export default function DashboardPage() {
  const { tasks, fetchTasks, isLoading } = useTaskStore();
  const router = useRouter();

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  const now = new Date();
  const dateStr = now.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  });

  // 最近 5 个任务
  const recentTasks = [...tasks]
    .sort(
      (a, b) =>
        new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
    )
    .slice(0, 5);

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">仪表盘</h1>
        <p className="text-sm text-muted-foreground mt-1">{dateStr}</p>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {isLoading ? (
          <>
            {[1, 2, 3, 4].map((i) => (
              <Card key={i}>
                <CardContent className="pt-6">
                  <Skeleton className="h-4 w-20 mb-2" />
                  <Skeleton className="h-8 w-12" />
                </CardContent>
              </Card>
            ))}
          </>
        ) : (
          <>
            <StatCard
              title="进行中任务"
              value={(tasks.filter(t => t.status === 'running' || t.status === 'analyzing').length)}
              subtitle={`共 ${tasks.length} 个任务`}
              icon={<Target className="h-4 w-4" />}
            />
            <StatCard
              title="发现漏洞"
              value={
                tasks.reduce(
                  (sum, t) =>
                    sum +
                    t.vulnCount.critical +
                    t.vulnCount.high +
                    t.vulnCount.medium +
                    t.vulnCount.low +
                    t.vulnCount.info,
                  0
                )
              }
              subtitle={`${tasks.reduce((s, t) => s + t.vulnCount.critical + t.vulnCount.high, 0)} 个高危`}
              icon={<AlertTriangle className="h-4 w-4" />}
              trend={{ value: 12, label: "较上周" }}
            />
            <StatCard
              title="已提交报告"
              value={tasks.filter(t => t.status === 'completed').length}
              subtitle="等待平台审核"
              icon={<FileCheck className="h-4 w-4" />}
            />
            <StatCard
              title="通过率"
              value="87%"
              subtitle={`${tasks.filter(t => t.status === 'completed').length} 已通过`}
              icon={<TrendingUp className="h-4 w-4" />}
              trend={{ value: 5, label: "较上月" }}
            />
          </>
        )}
      </div>

      {/* 两栏布局 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 左侧：最近任务 */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">最近任务</CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push("/tasks")}
            >
              查看全部
              <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </CardHeader>
          <CardContent className="px-4">
            {isLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : recentTasks.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                暂无任务，点击"新建任务"开始
              </p>
            ) : (
              <div className="divide-y divide-border">
                {recentTasks.map((task) => (
                  <RecentTaskRow key={task.id} task={task} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 右侧：漏洞分布 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">漏洞等级分布</CardTitle>
          </CardHeader>
          <CardContent>
            {/* 简易统计条（无 recharts 依赖时可用纯 CSS） */}
            {(() => {
              const totals = tasks.reduce(
                (acc, t) => ({
                  critical: acc.critical + t.vulnCount.critical,
                  high: acc.high + t.vulnCount.high,
                  medium: acc.medium + t.vulnCount.medium,
                  low: acc.low + t.vulnCount.low,
                  info: acc.info + t.vulnCount.info,
                }),
                { critical: 0, high: 0, medium: 0, low: 0, info: 0 }
              );
              const allTotal =
                totals.critical +
                totals.high +
                totals.medium +
                totals.low +
                totals.info;

              if (allTotal === 0) {
                return (
                  <p className="text-sm text-muted-foreground py-8 text-center">
                    暂无漏洞数据
                  </p>
                );
              }

              const bars = [
                { label: "严重", count: totals.critical, color: "bg-red-500" },
                { label: "高危", count: totals.high, color: "bg-orange-500" },
                { label: "中危", count: totals.medium, color: "bg-yellow-500" },
                { label: "低危", count: totals.low, color: "bg-blue-500" },
                { label: "信息", count: totals.info, color: "bg-gray-500" },
              ];

              return (
                <div className="space-y-3">
                  {bars.map((bar) => (
                    <div key={bar.label} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-muted-foreground">
                          {bar.label}
                        </span>
                        <span className="font-mono">{bar.count}</span>
                      </div>
                      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                        <div
                          className={cn("h-full rounded-full", bar.color)}
                          style={{
                            width: `${(bar.count / allTotal) * 100}%`,
                            minWidth: bar.count > 0 ? "4px" : 0,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              );
            })()}
          </CardContent>
        </Card>
      </div>

      {/* 底部：最近活动 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">最近活动</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-0">
            {MOCK_ACTIVITIES.map((activity, idx) => (
              <div key={activity.id}>
                <div className="flex items-center gap-3 py-2.5">
                  <div className="flex-shrink-0">
                    <Clock className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm">
                      {activity.action}
                      {activity.severity && (
                        <Badge variant="outline" className="ml-2 text-[10px] px-1 py-0">
                          {activity.severity}
                        </Badge>
                      )}
                    </p>
                    <p className="text-xs text-muted-foreground truncate">
                      {activity.target}
                    </p>
                  </div>
                  <span className="text-xs text-muted-foreground whitespace-nowrap">
                    {formatRelativeTime(activity.time)}
                  </span>
                </div>
                {idx < MOCK_ACTIVITIES.length - 1 && <Separator />}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
