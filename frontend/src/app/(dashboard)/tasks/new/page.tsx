// @ts-nocheck — react-hook-form + shadcn Form generic type incompatibility

"use client";


// ============================================================
// src/app/(dashboard)/tasks/new/page.tsx — 新建任务（3 步骤）
// ============================================================

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Info,
  Shield,
  Box,
  Target,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";
import { useTaskStore } from "@/stores/task-store";
import { toast } from "sonner";
import type { Platform, TaskMode } from "@/types/task";

// ============================================================
// Zod Schema
// ============================================================

const newTaskSchema = z.object({
  // 步骤1：基本信息
  title: z
    .string()
    .min(2, "任务名称至少 2 个字符")
    .max(100, "任务名称不超过 100 个字符"),
  platform: z.enum(["butian", "vulbox", "custom"]),
  platformTaskId: z.string().optional(),
  targetUrl: z
    .string()
    .min(1, "请输入目标 URL")
    .url("请输入有效的 URL（https://...）"),
  tags: z.string().optional(),

  // 步骤2：测试范围
  domains: z.string().optional(),
  ipRanges: z.string().optional(),
  excludedPaths: z.string().optional(),
  allowAutoScan: z.boolean().default(true),
  allowedTools: z.string().optional(),
  notes: z.string().optional(),

  // 步骤3：扫描模式
  mode: z.enum(["auto", "guided"]),
});

type NewTaskFormValues = z.infer<typeof newTaskSchema>;

// ============================================================
// 步骤定义
// ============================================================

const STEPS = [
  { id: 1, label: "基本信息", description: "任务名称与目标" },
  { id: 2, label: "测试范围", description: "Scope 与工具配置" },
  { id: 3, label: "选择模式", description: "自动 / 引导" },
];

// ============================================================
// 平台选项
// ============================================================

const PLATFORM_OPTIONS: Array<{
  value: Platform;
  label: string;
  icon: React.ReactNode;
}> = [
  { value: "butian", label: "补天漏洞响应平台", icon: <Shield className="h-4 w-4" /> },
  { value: "vulbox", label: "漏洞盒子众测平台", icon: <Box className="h-4 w-4" /> },
  { value: "custom", label: "自定义目标", icon: <Target className="h-4 w-4" /> },
];

// ============================================================
// 主组件
// ============================================================

export default function NewTaskPage() {
  const router = useRouter();
  const { addTask, isCreating } = useTaskStore();
  const [step, setStep] = useState(1);

  const form = useForm<NewTaskFormValues>({
    resolver: zodResolver(newTaskSchema),
    defaultValues: {
      title: "",
      platform: "butian",
      platformTaskId: "",
      targetUrl: "",
      tags: "",
      domains: "",
      ipRanges: "",
      excludedPaths: "",
      allowAutoScan: true,
      allowedTools: "nuclei, sqlmap, xray, ffuf, nmap",
      notes: "",
      mode: "auto",
    },
    mode: "onChange",
  });

  const allowAutoScan = form.watch("allowAutoScan");

  // allowAutoScan 关闭时自动锁定 mode 为 guided
  const handleAutoScanChange = (checked: boolean) => {
    form.setValue("allowAutoScan", checked);
    if (!checked) {
      form.setValue("mode", "guided");
    }
  };

  // 步骤校验
  const validateStep = async (targetStep: number): Promise<boolean> => {
    if (targetStep === 1) {
      const valid = await form.trigger(["title", "platform", "targetUrl"]);
      return valid;
    }
    if (targetStep === 2) {
      const valid = await form.trigger(["allowAutoScan"]);
      return valid;
    }
    if (targetStep === 3) {
      const valid = await form.trigger(["mode"]);
      return valid;
    }
    return true;
  };

  // 上一步
  const handlePrev = () => {
    if (step > 1) setStep(step - 1);
  };

  // 下一步
  const handleNext = async () => {
    const ok = await validateStep(step);
    if (ok && step < 3) setStep(step + 1);
  };

  // 提交
  const onSubmit = async (values: NewTaskFormValues) => {
    try {
      const task = await addTask({
        title: values.title,
        platform: values.platform,
        mode: values.mode,
        scope: {
          targetUrl: values.targetUrl,
          allowAutoScan: values.allowAutoScan,
          allowedPaths: values.domains
            ? values.domains.split("\n").filter(Boolean)
            : ["/*"],
          excludedPaths: values.excludedPaths
            ? values.excludedPaths.split("\n").filter(Boolean)
            : [],
          notes: values.notes,
        },
        notes: [
          values.platformTaskId && `平台任务ID: ${values.platformTaskId}`,
          values.ipRanges && `IP段: ${values.ipRanges}`,
          values.tags && `标签: ${values.tags}`,
        ]
          .filter(Boolean)
          .join("\n"),
      });

      toast.success("任务创建成功");
      router.push(`/tasks/${task.id}`);
    } catch {
      toast.error("创建失败，请重试");
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* 返回 */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => router.back()}
        className="gap-1 -ml-2"
      >
        <ArrowLeft className="h-4 w-4" />
        返回
      </Button>

      {/* 步骤指示器 */}
      <div className="flex items-center gap-2">
        {STEPS.map((s, idx) => (
          <div key={s.id} className="flex items-center gap-2">
            <button
              onClick={() => {
                if (s.id < step) setStep(s.id);
              }}
              className={cn(
                "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                step === s.id
                  ? "bg-primary text-primary-foreground"
                  : step > s.id
                  ? "bg-primary/10 text-primary hover:bg-primary/20 cursor-pointer"
                  : "bg-muted text-muted-foreground"
              )}
            >
              <span
                className={cn(
                  "flex h-5 w-5 items-center justify-center rounded-full text-xs",
                  step === s.id
                    ? "bg-primary-foreground text-primary"
                    : step > s.id
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted-foreground/30 text-muted-foreground"
                )}
              >
                {step > s.id ? <Check className="h-3 w-3" /> : s.id}
              </span>
              <span className="hidden sm:inline">{s.label}</span>
            </button>
            {idx < STEPS.length - 1 && (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
          </div>
        ))}
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)}>
          <Card>
            {/* ============================================ */}
            {/* 步骤 1：基本信息                               */}
            {/* ============================================ */}
            {step === 1 && (
              <>
                <CardHeader>
                  <CardTitle className="text-lg">基本信息</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="title"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>任务名称 *</FormLabel>
                        <FormControl>
                          <Input
                            placeholder='例如："某电商平台 SQL 注入检测"'
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="platform"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>平台 *</FormLabel>
                        <Select
                          onValueChange={field.onChange}
                          defaultValue={field.value}
                        >
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="选择众测平台" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {PLATFORM_OPTIONS.map((opt) => (
                              <SelectItem key={opt.value} value={opt.value}>
                                <span className="flex items-center gap-2">
                                  {opt.icon}
                                  {opt.label}
                                </span>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="platformTaskId"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>平台任务 ID</FormLabel>
                        <FormControl>
                          <Input
                            placeholder='补天任务编号（如 "SR-2026-0891"）'
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          在平台拿到的任务编号，方便追溯
                        </FormDescription>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="targetUrl"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>目标 URL *</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="https://example.com"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="tags"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>标签</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="web, api, sql-injection（逗号分隔）"
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          用于分类和搜索
                        </FormDescription>
                      </FormItem>
                    )}
                  />
                </CardContent>
              </>
            )}

            {/* ============================================ */}
            {/* 步骤 2：测试范围                               */}
            {/* ============================================ */}
            {step === 2 && (
              <>
                <CardHeader>
                  <CardTitle className="text-lg">测试范围</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="domains"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>域名列表</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder={"example.com\napi.example.com\nadmin.example.com"}
                            rows={3}
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          每行一个域名或子域名
                        </FormDescription>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="ipRanges"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>IP 段</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="192.168.1.0/24, 10.0.0.0/16"
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          CIDR 格式，逗号分隔
                        </FormDescription>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="excludedPaths"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>排除路径</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder={"/admin/*\n/internal/*\n/payment/callback"}
                            rows={3}
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          每行一个路径，支持 * 通配符
                        </FormDescription>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="allowAutoScan"
                    render={({ field }) => (
                      <FormItem className="flex flex-row items-center justify-between rounded-lg border border-border p-4">
                        <div className="space-y-0.5">
                          <FormLabel className="text-base">
                            允许自动化扫描
                          </FormLabel>
                          <FormDescription>
                            关闭后模式将锁定为「引导模式」，需人工参与
                          </FormDescription>
                        </div>
                        <FormControl>
                          <Switch
                            checked={field.value}
                            onCheckedChange={handleAutoScanChange}
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />

                  {!allowAutoScan && (
                    <Alert>
                      <Info className="h-4 w-4" />
                      <AlertDescription>
                        已关闭自动扫描，扫描模式将自动设为「引导模式」。适用于政府网站、金融系统等禁止自动化工具的目标。
                      </AlertDescription>
                    </Alert>
                  )}

                  <FormField
                    control={form.control}
                    name="allowedTools"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>允许的工具</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="nuclei, sqlmap, xray, ffuf, nmap"
                            {...field}
                          />
                        </FormControl>
                        <FormDescription>
                          逗号分隔，留空则使用默认工具集
                        </FormDescription>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="notes"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>备注</FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder="补充说明，如：需通过堡垒机接入、工作时间限制等..."
                            rows={2}
                            {...field}
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </CardContent>
              </>
            )}

            {/* ============================================ */}
            {/* 步骤 3：选择模式                               */}
            {/* ============================================ */}
            {step === 3 && (
              <>
                <CardHeader>
                  <CardTitle className="text-lg">选择扫描模式</CardTitle>
                </CardHeader>
                <CardContent>
                  {!allowAutoScan ? (
                    /* allowAutoScan=false → 只显示引导模式 */
                    <div className="space-y-4">
                      <Alert>
                        <Info className="h-4 w-4" />
                        <AlertDescription>
                          由于禁用了自动扫描（allowAutoScan=false），只能选择「引导模式」。AI
                          将作为副驾驶，一步步指导你执行命令并分析结果。
                        </AlertDescription>
                      </Alert>

                      <div className="rounded-lg border-2 border-primary/30 bg-primary/5 p-6">
                        <div className="flex items-center gap-3 mb-3">
                          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/20">
                            <Target className="h-5 w-5 text-primary" />
                          </div>
                          <div>
                            <h3 className="font-semibold">引导模式</h3>
                            <p className="text-sm text-muted-foreground">
                              AI 副驾驶 — 人工执行 + AI 分析
                            </p>
                          </div>
                          <Badge className="ml-auto">当前选择</Badge>
                        </div>
                        <ul className="text-sm text-muted-foreground space-y-1 ml-13">
                          <li>· AI 给出要执行的命令</li>
                          <li>· 你在终端执行后粘贴结果</li>
                          <li>· AI 分析结果，给出下一步</li>
                          <li>· 兼容所有目标（含 WAF/CDN 保护）</li>
                        </ul>
                      </div>

                      <FormField
                        control={form.control}
                        name="mode"
                        render={({ field }) => (
                          <input type="hidden" {...field} value="guided" />
                        )}
                      />
                    </div>
                  ) : (
                    /* allowAutoScan=true → 显示两种模式 */
                    <FormField
                      control={form.control}
                      name="mode"
                      render={({ field }) => (
                        <FormItem>
                          <FormControl>
                            <div className="grid grid-cols-2 gap-4">
                              {/* 自动模式 */}
                              <button
                                type="button"
                                onClick={() => field.onChange("auto")}
                                className={cn(
                                  "flex flex-col items-center gap-3 p-5 rounded-lg border-2 transition-all text-left",
                                  field.value === "auto"
                                    ? "border-primary bg-primary/5"
                                    : "border-border hover:border-primary/30"
                                )}
                              >
                                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/20">
                                  <svg className="h-5 w-5 text-blue-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <polyline points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                                  </svg>
                                </div>
                                <div className="text-center">
                                  <h3 className="font-semibold">自动模式</h3>
                                  <p className="text-xs text-muted-foreground mt-1">
                                    全自动扫描→分析→报告
                                  </p>
                                </div>
                                <ul className="text-xs text-muted-foreground space-y-0.5 w-full">
                                  <li>✅ 无需人工干预</li>
                                  <li>✅ 1-6 小时完成</li>
                                  <li>⚠️ 可能触发 WAF</li>
                                </ul>
                                {field.value === "auto" && (
                                  <Badge>已选择</Badge>
                                )}
                              </button>

                              {/* 引导模式 */}
                              <button
                                type="button"
                                onClick={() => field.onChange("guided")}
                                className={cn(
                                  "flex flex-col items-center gap-3 p-5 rounded-lg border-2 transition-all text-left",
                                  field.value === "guided"
                                    ? "border-primary bg-primary/5"
                                    : "border-border hover:border-primary/30"
                                )}
                              >
                                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-500/20">
                                  <svg className="h-5 w-5 text-green-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                                    <circle cx="9" cy="7" r="4" />
                                    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                                    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                                  </svg>
                                </div>
                                <div className="text-center">
                                  <h3 className="font-semibold">引导模式</h3>
                                  <p className="text-xs text-muted-foreground mt-1">
                                    AI 副驾驶 — 人工执行
                                  </p>
                                </div>
                                <ul className="text-xs text-muted-foreground space-y-0.5 w-full">
                                  <li>✅ 兼容所有目标</li>
                                  <li>✅ 不触发 WAF</li>
                                  <li>⚠️ 需要人工参与</li>
                                </ul>
                                {field.value === "guided" && (
                                  <Badge>已选择</Badge>
                                )}
                              </button>
                            </div>
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  )}
                </CardContent>
              </>
            )}

            {/* ============================================ */}
            {/* 底部导航按钮                                   */}
            {/* ============================================ */}
            <div className="flex items-center justify-between px-6 py-4 border-t border-border">
              <Button
                type="button"
                variant="ghost"
                onClick={handlePrev}
                disabled={step === 1}
                className="gap-1"
              >
                <ChevronLeft className="h-4 w-4" />
                上一步
              </Button>

              <span className="text-xs text-muted-foreground">
                {step} / {STEPS.length}
              </span>

              {step < 3 ? (
                <Button type="button" onClick={handleNext} className="gap-1">
                  下一步
                  <ChevronRight className="h-4 w-4" />
                </Button>
              ) : (
                <Button type="submit" disabled={isCreating} className="gap-1">
                  {isCreating ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                      创建中...
                    </>
                  ) : (
                    <>
                      <Check className="h-4 w-4" />
                      创建任务
                    </>
                  )}
                </Button>
              )}
            </div>
          </Card>
        </form>
      </Form>
    </div>
  );
}
