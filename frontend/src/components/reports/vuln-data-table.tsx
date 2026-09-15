"use client";

// ============================================================
// src/components/reports/vuln-data-table.tsx — 漏洞数据表格
// ============================================================

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { RiskBadge } from "@/components/shared/risk-badge";
import { cn } from "@/lib/utils";
import { SEVERITY_MAP } from "@/lib/utils";
import type { Vulnerability } from "@/types/scan";

interface VulnDataTableProps {
  vulns: Vulnerability[];
  className?: string;
}

export function VulnDataTable({ vulns, className }: VulnDataTableProps) {
  if (vulns.length === 0) {
    return (
      <div className="text-center py-8 text-sm text-muted-foreground">
        暂无漏洞
      </div>
    );
  }

  return (
    <div className={cn("rounded-md border", className)}>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-[50px] text-xs">#</TableHead>
            <TableHead className="text-xs">漏洞名称</TableHead>
            <TableHead className="w-[80px] text-xs">等级</TableHead>
            <TableHead className="w-[80px] text-xs">类型</TableHead>
            <TableHead className="w-[80px] text-xs">状态</TableHead>
            <TableHead className="w-[100px] text-xs text-right">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {vulns.map((vuln, idx) => (
            <TableRow key={vuln.id}>
              <TableCell className="text-xs text-muted-foreground">
                {idx + 1}
              </TableCell>
              <TableCell className="text-xs">
                <div>
                  <p className="font-medium">{vuln.name}</p>
                  <p className="text-[10px] text-muted-foreground truncate max-w-[300px]">
                    {vuln.endpoint}
                  </p>
                </div>
              </TableCell>
              <TableCell>
                <RiskBadge severity={vuln.severity} />
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {vuln.tags[0] ?? vuln.owaspCategory?.slice(0, 15) ?? "-"}
              </TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={cn(
                    "text-[10px]",
                    vuln.status === "new" && "border-blue-500/50 text-blue-400",
                    vuln.status === "confirmed" && "border-red-500/50 text-red-400",
                    vuln.status === "false_positive" && "border-muted text-muted-foreground"
                  )}
                >
                  {vuln.status === "new"
                    ? "新发现"
                    : vuln.status === "confirmed"
                    ? "已确认"
                    : vuln.status === "false_positive"
                    ? "误报"
                    : vuln.status}
                </Badge>
              </TableCell>
              <TableCell className="text-right">
                <Badge
                  variant="outline"
                  className="text-[10px] cursor-pointer hover:bg-muted"
                >
                  详情
                </Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
