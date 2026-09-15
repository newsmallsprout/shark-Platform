"use client";

// ============================================================
// src/app/(dashboard)/settings/page.tsx — 系统设置
// ============================================================

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Save, Bot, Globe, Bell, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { useSettingsStore } from "@/stores/settings-store";
import { toast } from "sonner";

// ---- Schema ----

const settingsSchema = z.object({
  // AI
  apiKey: z.string().optional(),
  model: z.string(),
  baseUrl: z.string().url(),
  temperature: z.number().min(0).max(2),

  // Scan
  maxConcurrency: z.number().min(1).max(50),
  toolTimeout: z.number().min(60).max(86400),
  rateLimit: z.number().min(1).max(100),

  // Notifications
  onTaskComplete: z.boolean(),
  onVulnFound: z.boolean(),
  onReportSubmitted: z.boolean(),
});

export default function SettingsPage() {
  const { ai, scan, notifications, setAI, setScan, setNotifications } =
    useSettingsStore();

  const form = useForm<z.infer<typeof settingsSchema>>({
    resolver: zodResolver(settingsSchema),
    defaultValues: {
      apiKey: ai.apiKey,
      model: ai.model,
      baseUrl: ai.baseUrl,
      temperature: ai.temperature,
      maxConcurrency: scan.maxConcurrency,
      toolTimeout: scan.toolTimeout,
      rateLimit: scan.rateLimit,
      onTaskComplete: notifications.onTaskComplete,
      onVulnFound: notifications.onVulnFound,
      onReportSubmitted: notifications.onReportSubmitted,
    },
  });

  const onSubmit = (values: z.infer<typeof settingsSchema>) => {
    setAI({
      apiKey: values.apiKey ?? "",
      model: values.model as "gpt-4o" | "claude-3.5-sonnet" | "deepseek-v3" | "custom",
      baseUrl: values.baseUrl,
      temperature: values.temperature,
    });
    setScan({
      maxConcurrency: values.maxConcurrency,
      toolTimeout: values.toolTimeout,
      rateLimit: values.rateLimit,
    });
    setNotifications({
      onTaskComplete: values.onTaskComplete,
      onVulnFound: values.onVulnFound,
      onReportSubmitted: values.onReportSubmitted,
    });
    toast.success("设置已保存");
  };

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">系统设置</h1>
        <p className="text-sm text-muted-foreground mt-1">
          配置 AI、扫描参数和通知
        </p>
      </div>

      <Tabs defaultValue="ai">
        <TabsList>
          <TabsTrigger value="ai" className="gap-1.5">
            <Bot className="h-4 w-4" />
            AI 配置
          </TabsTrigger>
          <TabsTrigger value="scan" className="gap-1.5">
            <Zap className="h-4 w-4" />
            扫描配置
          </TabsTrigger>
          <TabsTrigger value="notifications" className="gap-1.5">
            <Bell className="h-4 w-4" />
            通知配置
          </TabsTrigger>
        </TabsList>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="mt-4">
            {/* AI 配置 */}
            <TabsContent value="ai">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">AI 模型配置</CardTitle>
                  <CardDescription>
                    选择用于分析漏洞和生成报告的 AI 模型
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="apiKey"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>API Key</FormLabel>
                        <FormControl>
                          <Input
                            type="password"
                            placeholder="sk-..."
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="model"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>模型</FormLabel>
                        <Select
                          onValueChange={field.onChange}
                          defaultValue={field.value}
                        >
                          <FormControl>
                            <SelectTrigger>
                              <SelectValue placeholder="选择模型" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="gpt-4o">GPT-4o</SelectItem>
                            <SelectItem value="claude-3.5-sonnet">
                              Claude 3.5 Sonnet
                            </SelectItem>
                            <SelectItem value="deepseek-v3">
                              DeepSeek V3
                            </SelectItem>
                            <SelectItem value="custom">自定义</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="baseUrl"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>API Base URL</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="https://api.openai.com/v1"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="temperature"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          温度 ({field.value})
                        </FormLabel>
                        <FormControl>
                          <Slider
                            min={0}
                            max={2}
                            step={0.1}
                            value={[field.value]}
                            onValueChange={(v) => field.onChange(Array.isArray(v) ? v[0] : v)}
                          />
                        </FormControl>
                        <FormDescription>
                          越低越严谨，越高越有创造性
                        </FormDescription>
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>
            </TabsContent>

            {/* 扫描配置 */}
            <TabsContent value="scan">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">扫描参数</CardTitle>
                  <CardDescription>
                    配置工具并发数、超时和速率限制
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="maxConcurrency"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          最大并发数 ({field.value})
                        </FormLabel>
                        <FormControl>
                          <Slider
                            min={1}
                            max={50}
                            step={1}
                            value={[field.value]}
                            onValueChange={(v) => field.onChange(Array.isArray(v) ? v[0] : v)}
                          />
                        </FormControl>
                        <FormDescription>
                          同时运行的扫描工具数量
                        </FormDescription>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="toolTimeout"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          工具超时（{Math.floor(field.value / 60)} 分钟）
                        </FormLabel>
                        <FormControl>
                          <Slider
                            min={60}
                            max={86400}
                            step={60}
                            value={[field.value]}
                            onValueChange={(v) => field.onChange(Array.isArray(v) ? v[0] : v)}
                          />
                        </FormControl>
                        <FormDescription>
                          单个工具最大运行时间
                        </FormDescription>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="rateLimit"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          速率限制 ({field.value} 请求/秒)
                        </FormLabel>
                        <FormControl>
                          <Slider
                            min={1}
                            max={100}
                            step={1}
                            value={[field.value]}
                            onValueChange={(v) => field.onChange(Array.isArray(v) ? v[0] : v)}
                          />
                        </FormControl>
                        <FormDescription>
                          避免触发 WAF 的请求频率上限
                        </FormDescription>
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>
            </TabsContent>

            {/* 通知配置 */}
            <TabsContent value="notifications">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">通知偏好</CardTitle>
                  <CardDescription>
                    选择在哪些事件发生时接收通知
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FormField
                    control={form.control}
                    name="onTaskComplete"
                    render={({ field }) => (
                      <FormItem className="flex items-center justify-between rounded-lg border border-border p-3">
                        <div>
                          <FormLabel className="text-sm">任务完成通知</FormLabel>
                          <FormDescription>
                            扫描任务完成时推送通知
                          </FormDescription>
                        </div>
                        <FormControl>
                          <Switch
                            checked={field.value}
                            onCheckedChange={field.onChange}
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="onVulnFound"
                    render={({ field }) => (
                      <FormItem className="flex items-center justify-between rounded-lg border border-border p-3">
                        <div>
                          <FormLabel className="text-sm">漏洞发现通知</FormLabel>
                          <FormDescription>
                            发现严重/高危漏洞时实时推送
                          </FormDescription>
                        </div>
                        <FormControl>
                          <Switch
                            checked={field.value}
                            onCheckedChange={field.onChange}
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="onReportSubmitted"
                    render={({ field }) => (
                      <FormItem className="flex items-center justify-between rounded-lg border border-border p-3">
                        <div>
                          <FormLabel className="text-sm">报告提交通知</FormLabel>
                          <FormDescription>
                            报告成功提交到平台后通知
                          </FormDescription>
                        </div>
                        <FormControl>
                          <Switch
                            checked={field.value}
                            onCheckedChange={field.onChange}
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </CardContent>
              </Card>
            </TabsContent>

            {/* 保存按钮 */}
            <div className="flex justify-end mt-6">
              <Button type="submit" className="gap-2">
                <Save className="h-4 w-4" />
                保存设置
              </Button>
            </div>
          </form>
        </Form>
      </Tabs>
    </div>
  );
}
