"use client";

// ============================================================
// src/components/guided-mode/command-card.tsx — 命令展示卡片
// ============================================================

import { useState } from "react";
import { Copy, Check, Terminal, Clock, AlertTriangle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, copyToClipboard } from "@/lib/utils";
import type { CommandBlock } from "@/types/chat";

interface CommandCardProps {
  command: CommandBlock;
}

export function CommandCard({ command }: CommandCardProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const ok = await copyToClipboard(command.command);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const statusColors: Record<string, string> = {
    pending: "border-border",
    executing: "border-blue-500/30 bg-blue-500/5",
    completed: "border-green-500/30 bg-green-500/5",
    failed: "border-red-500/30 bg-red-500/5",
  };

  const statusLabels: Record<string, string> = {
    pending: "待执行",
    executing: "执行中",
    completed: "已完成",
    failed: "执行失败",
  };

  return (
    <Card className={cn("border-2", statusColors[command.status])}>
      <CardContent className="p-3 space-y-2">
        {/* 头部 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-amber-500/20">
              <Terminal className="h-3.5 w-3.5 text-amber-400" />
            </div>
            <Badge
              variant="outline"
              className={cn(
                "text-[10px]",
                command.status === "completed" && "border-green-500/50 text-green-400",
                command.status === "failed" && "border-red-500/50 text-red-400"
              )}
            >
              {statusLabels[command.status]}
            </Badge>
            {command.duration !== undefined && command.status === "completed" && (
              <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
                <Clock className="h-3 w-3" />
                {command.duration}s
              </span>
            )}
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={handleCopy}
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-green-400" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>

        {/* 描述 */}
        <p className="text-xs text-muted-foreground">{command.description}</p>

        {/* 命令代码块 */}
        <pre className="text-xs bg-black/40 rounded-md p-2.5 overflow-x-auto font-mono text-green-400 whitespace-pre-wrap break-all">
          <code>$ {command.command}</code>
        </pre>

        {/* 执行结果 */}
        {command.result && command.status === "completed" && (
          <div>
            <p className="text-[10px] font-medium text-muted-foreground mb-1">
              执行结果
            </p>
            <pre className="text-[10px] bg-black/30 rounded p-2 max-h-40 overflow-auto font-mono whitespace-pre-wrap break-all text-muted-foreground">
              {command.result}
            </pre>
          </div>
        )}

        {/* 失败信息 */}
        {command.status === "failed" && command.result && (
          <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/10 rounded p-2">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
            {command.result}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
