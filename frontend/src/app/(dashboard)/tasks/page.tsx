"use client";

// ============================================================
// src/app/(dashboard)/tasks/page.tsx — 任务列表
// ============================================================

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Plus,
  Search,
  SlidersHorizontal,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Label } from "@/components/ui/label";
import { TaskCard } from "@/components/tasks/task-card";
import { EmptyState } from "@/components/shared/empty-state";
import { useTaskStore } from "@/stores/task-store";
import type { TaskStatus, Platform, TaskMode } from "@/types/task";
import { TASK_STATUS_CONFIG, PLATFORM_CONFIGS } from "@/types/task";
import { toast } from "sonner";

export default function TasksPage() {
  const router = useRouter();
  const {
    tasks,
    filters,
    setFilters,
    fetchTasks,
    startTask,
    cancelTask,
    removeTask,
    isLoading,
  } = useTaskStore();

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  // ---- 操作处理 ----

  const handleStart = useCallback(
    async (id: string) => {
      await startTask(id);
      toast.success("任务已开始");
      router.push(`/tasks/${id}/auto`);
    },
    [startTask, router]
  );

  const handleCancel = useCallback(
    async (id: string) => {
      await cancelTask(id);
      toast.success("任务已停止");
    },
    [cancelTask]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      await removeTask(id);
      toast.success("任务已删除");
    },
    [removeTask]
  );

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">任务列表</h1>
          <p className="text-sm text-muted-foreground mt-1">
            管理渗透测试任务
          </p>
        </div>
        <Button onClick={() => router.push("/tasks/new")} className="gap-2">
          <Plus className="h-4 w-4" />
          新建任务
        </Button>
      </div>

      {/* 搜索 + 筛选 */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="搜索任务名称或目标 URL..."
            className="pl-8"
            value={filters.search}
            onChange={(e) => setFilters({ search: e.target.value })}
          />
        </div>

        <Select
          value={filters.status}
          onValueChange={(v) =>
            setFilters({ status: v as TaskStatus | "all" })
          }
        >
          <SelectTrigger className="w-[110px]">
            <SelectValue placeholder="状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {Object.entries(TASK_STATUS_CONFIG).map(([key, cfg]) => (
              <SelectItem key={key} value={key}>
                {cfg.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={filters.platform}
          onValueChange={(v) =>
            setFilters({ platform: v as Platform | "all" })
          }
        >
          <SelectTrigger className="w-[110px]">
            <SelectValue placeholder="平台" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部平台</SelectItem>
            {PLATFORM_CONFIGS.map((p) => (
              <SelectItem key={p.name} value={p.name}>
                {p.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={filters.mode}
          onValueChange={(v) =>
            setFilters({ mode: v as TaskMode | "all" })
          }
        >
          <SelectTrigger className="w-[110px]">
            <SelectValue placeholder="模式" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部模式</SelectItem>
            <SelectItem value="auto">自动模式</SelectItem>
            <SelectItem value="guided">引导模式</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* 任务网格 */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : tasks.length === 0 ? (
        <EmptyState
          icon={AlertCircle}
          title="暂无任务"
          description="点击「新建任务」开始你的第一次渗透测试"
          actionLabel="新建任务"
          onAction={() => router.push("/tasks/new")}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {tasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              onStart={handleStart}
              onCancel={handleCancel}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}
