"use client";

// ============================================================
// src/app/(dashboard)/platforms/page.tsx — 平台管理
// ============================================================

import { useState } from "react";
import { Shield, Box, Link2, Unlink2, RefreshCw, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

// ---- Mock 平台数据 ----

const MOCK_BUTIAN = {
  name: "补天漏洞响应平台",
  icon: <Shield className="h-5 w-5" />,
  connected: true,
  nickname: "shark",
  currentTasks: 2,
  historySubmissions: 47,
  cookie: "****-butian-cookie-****",
  token: "****-butian-token-****",
};

const MOCK_VULBOX = {
  name: "漏洞盒子众测平台",
  icon: <Box className="h-5 w-5" />,
  connected: false,
  nickname: "",
  currentTasks: 0,
  historySubmissions: 12,
  cookie: "",
  token: "",
};

export default function PlatformsPage() {
  const [butian, setButian] = useState(MOCK_BUTIAN);
  const [vulbox, setVulbox] = useState(MOCK_VULBOX);
  const [testingPlatform, setTestingPlatform] = useState<string | null>(null);

  const handleTestConnection = async (platform: string) => {
    setTestingPlatform(platform);
    // 模拟连接测试
    await new Promise((r) => setTimeout(r, 1500));
    setTestingPlatform(null);
  };

  const handleToggleConnection = (platform: string) => {
    if (platform === "butian") {
      setButian((prev) => ({ ...prev, connected: !prev.connected }));
    } else {
      setVulbox((prev) => ({ ...prev, connected: !prev.connected }));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">平台管理</h1>
        <p className="text-sm text-muted-foreground mt-1">
          配置众测平台账号连接
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* 补天 */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {butian.icon}
                <CardTitle className="text-base">{butian.name}</CardTitle>
              </div>
              <Badge
                variant={butian.connected ? "default" : "secondary"}
                className="gap-1"
              >
                {butian.connected ? (
                  <>
                    <Link2 className="h-3 w-3" />
                    已连接
                  </>
                ) : (
                  <>
                    <Unlink2 className="h-3 w-3" />
                    未连接
                  </>
                )}
              </Badge>
            </div>
            <CardDescription>
              当前任务: {butian.currentTasks} · 历史提交: {butian.historySubmissions}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5">
              <Label className="text-xs">昵称</Label>
              <Input value={butian.nickname} disabled />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Cookie</Label>
              <Input
                type="password"
                value={butian.cookie}
                onChange={(e) =>
                  setButian((prev) => ({ ...prev, cookie: e.target.value }))
                }
                placeholder="输入补天平台 Cookie"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">API Token</Label>
              <Input
                type="password"
                value={butian.token}
                onChange={(e) =>
                  setButian((prev) => ({ ...prev, token: e.target.value }))
                }
                placeholder="输入 API Token"
              />
            </div>

            <div className="flex gap-2 pt-2">
              <Button
                variant="outline"
                size="sm"
                className="gap-1"
                onClick={() => handleTestConnection("butian")}
                disabled={testingPlatform === "butian"}
              >
                {testingPlatform === "butian" ? (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    测试中...
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    测试连接
                  </>
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleToggleConnection("butian")}
              >
                {butian.connected ? "断开" : "连接"}
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* 漏洞盒子 */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {vulbox.icon}
                <CardTitle className="text-base">{vulbox.name}</CardTitle>
              </div>
              <Badge
                variant={vulbox.connected ? "default" : "secondary"}
                className="gap-1"
              >
                {vulbox.connected ? (
                  <>
                    <Link2 className="h-3 w-3" />
                    已连接
                  </>
                ) : (
                  <>
                    <Unlink2 className="h-3 w-3" />
                    未连接
                  </>
                )}
              </Badge>
            </div>
            <CardDescription>
              当前任务: {vulbox.currentTasks} · 历史提交: {vulbox.historySubmissions}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5">
              <Label className="text-xs">昵称</Label>
              <Input value={vulbox.nickname} disabled />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Cookie</Label>
              <Input
                type="password"
                value={vulbox.cookie}
                onChange={(e) =>
                  setVulbox((prev) => ({ ...prev, cookie: e.target.value }))
                }
                placeholder="输入漏洞盒子 Cookie"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">API Token</Label>
              <Input
                type="password"
                value={vulbox.token}
                onChange={(e) =>
                  setVulbox((prev) => ({ ...prev, token: e.target.value }))
                }
                placeholder="输入 API Token"
              />
            </div>

            <div className="flex gap-2 pt-2">
              <Button
                variant="outline"
                size="sm"
                className="gap-1"
                onClick={() => handleTestConnection("vulbox")}
                disabled={testingPlatform === "vulbox"}
              >
                {testingPlatform === "vulbox" ? (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    测试中...
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    测试连接
                  </>
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleToggleConnection("vulbox")}
              >
                {vulbox.connected ? "断开" : "连接"}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
