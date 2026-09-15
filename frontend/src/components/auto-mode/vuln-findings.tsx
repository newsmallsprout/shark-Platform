"use client";

// ============================================================
// src/components/auto-mode/vuln-findings.tsx — 漏洞发现列表
// ============================================================

import { useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink, Copy, Check } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, copyToClipboard } from "@/lib/utils";
import { SEVERITY_MAP } from "@/lib/utils";
import type { Vulnerability } from "@/types/scan";

interface VulnFindingsProps {
  vulnerabilities: Vulnerability[];
}

export function VulnFindings({ vulnerabilities }: VulnFindingsProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (vulnerabilities.length === 0) {
    return (
      <div className="text-center py-8 text-sm text-muted-foreground">
        暂未发现漏洞，扫描进行中...
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {vulnerabilities.map((vuln) => {
        const severityConfig = SEVERITY_MAP[vuln.severity];
        const isExpanded = expandedId === vuln.id;

        return (
          <div
            key={vuln.id}
            className={cn(
              "rounded-lg border transition-colors",
              severityConfig.borderClass,
              isExpanded ? severityConfig.bgClass : "bg-card"
            )}
          >
            {/* 折叠头部 */}
            <button
              onClick={() => setExpandedId(isExpanded ? null : vuln.id)}
              className="w-full flex items-center gap-3 p-3 text-left"
            >
              <span
                className={cn("h-2.5 w-2.5 rounded-full flex-shrink-0")}
                style={{ backgroundColor: severityConfig.color }}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{vuln.name}</p>
                <p className="text-[11px] text-muted-foreground truncate">
                  {vuln.endpoint} · {vuln.method}
                </p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <Badge
                  variant="outline"
                  className={cn("text-[10px]", severityConfig.textClass)}
                >
                  {severityConfig.label}
                </Badge>
                {isExpanded ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </div>
            </button>

            {/* 展开详情 */}
            {isExpanded && (
              <div className="px-3 pb-3 space-y-2 border-t border-border/50 pt-3">
                <p className="text-xs text-muted-foreground">
                  {vuln.description}
                </p>

                {vuln.evidence && (
                  <div>
                    <p className="text-[10px] font-medium text-muted-foreground mb-1">
                      验证证据
                    </p>
                    <pre className="text-[10px] bg-black/30 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
                      {vuln.evidence}
                    </pre>
                  </div>
                )}

                {vuln.payload && (
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-[10px] font-medium text-muted-foreground">
                        Payload
                      </p>
                      <CopyButton text={vuln.payload} />
                    </div>
                    <pre className="text-[10px] bg-black/30 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
                      {vuln.payload}
                    </pre>
                  </div>
                )}

                <div>
                  <p className="text-[10px] font-medium text-muted-foreground mb-1">
                    修复建议
                  </p>
                  <p className="text-xs text-green-400">{vuln.remediation}</p>
                </div>

                {vuln.references.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {vuln.references.map((ref, i) => (
                      <a
                        key={i}
                        href={ref}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-[10px] text-primary hover:underline"
                      >
                        <ExternalLink className="h-3 w-3" />
                        参考 {i + 1}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---- 复制按钮 ----

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const ok = await copyToClipboard(text);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <Button
      variant="ghost"
      size="icon"
      className="h-5 w-5"
      onClick={(e) => {
        e.stopPropagation();
        handleCopy();
      }}
    >
      {copied ? (
        <Check className="h-3 w-3 text-green-400" />
      ) : (
        <Copy className="h-3 w-3" />
      )}
    </Button>
  );
}
