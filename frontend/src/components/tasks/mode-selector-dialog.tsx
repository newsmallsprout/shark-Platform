"use client";

// ============================================================
// src/components/tasks/mode-selector-dialog.tsx — 模式选择对话框
// ============================================================

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Zap, Users, ArrowRight } from "lucide-react";
import type { TaskMode } from "@/types/task";
import { MODE_MAP } from "@/lib/utils";
import { cn } from "@/lib/utils";

interface ModeSelectorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (mode: TaskMode) => void;
}

const MODES: Array<{ mode: TaskMode; icon: React.ReactNode; pros: string[]; cons: string[] }> = [
  {
    mode: "auto",
    icon: <Zap className="h-8 w-8" />,
    pros: ["全自动扫描，无需人工干预", "速度快，1-6 小时完成", "自动生成完整报告"],
    cons: ["某些目标禁止自动化工具", "可能触发 WAF/IP 封禁"],
  },
  {
    mode: "guided",
    icon: <Users className="h-8 w-8" />,
    pros: ["兼容所有目标（包括禁止自动扫描的）", "人工判断准确率更高", "学习渗透测试流程"],
    cons: ["需要人工参与执行命令", "耗时较长（数天）"],
  },
];

export function ModeSelectorDialog({
  open,
  onOpenChange,
  onSelect,
}: ModeSelectorDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>选择测试模式</DialogTitle>
          <DialogDescription>
            根据目标要求和自身情况选择合适的测试模式
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-4 mt-2">
          {MODES.map((m) => (
            <button
              key={m.mode}
              onClick={() => onSelect(m.mode)}
              className={cn(
                "flex flex-col items-center gap-3 p-4 rounded-lg border-2 border-border",
                "hover:border-primary/50 hover:bg-primary/5 transition-all",
                "text-left"
              )}
            >
              <div className="text-primary">{m.icon}</div>
              <div>
                <h3 className="font-semibold text-sm text-center">
                  {MODE_MAP[m.mode].label}
                </h3>
                <p className="text-xs text-muted-foreground text-center mt-0.5">
                  {MODE_MAP[m.mode].description}
                </p>
              </div>

              <div className="w-full space-y-2 text-xs">
                <div>
                  <p className="text-green-400 font-medium mb-0.5">✅ 优势</p>
                  {m.pros.map((p) => (
                    <p key={p} className="text-muted-foreground">
                      · {p}
                    </p>
                  ))}
                </div>
                <div>
                  <p className="text-yellow-400 font-medium mb-0.5">⚠️ 注意</p>
                  {m.cons.map((c) => (
                    <p key={c} className="text-muted-foreground">
                      · {c}
                    </p>
                  ))}
                </div>
              </div>

              <Button variant="secondary" size="sm" className="w-full gap-1 mt-auto">
                选择
                <ArrowRight className="h-3 w-3" />
              </Button>
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
