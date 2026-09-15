"use client";

// ============================================================
// src/components/reports/severity-chart.tsx — 漏洞严重度柱状图
// ============================================================

import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

interface SeverityChartProps {
  data: {
    critical: number;
    high: number;
    medium: number;
    low: number;
    info: number;
  };
}

const chartConfig: ChartConfig = {
  count: { label: "漏洞数量" },
};

export function SeverityChart({ data }: SeverityChartProps) {
  const chartData = [
    { severity: "严重", count: data.critical, fill: "#ef4444" },
    { severity: "高危", count: data.high, fill: "#f97316" },
    { severity: "中危", count: data.medium, fill: "#eab308" },
    { severity: "低危", count: data.low, fill: "#3b82f6" },
    { severity: "信息", count: data.info, fill: "#6b7280" },
  ];

  const total =
    data.critical + data.high + data.medium + data.low + data.info;

  if (total === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        暂无漏洞数据
      </div>
    );
  }

  return (
    <ChartContainer config={chartConfig} className="h-48 w-full">
      <BarChart data={chartData} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-border" />
        <XAxis
          dataKey="severity"
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 11, fill: "#9ca3af" }}
        />
        <ChartTooltip content={<ChartTooltipContent />} />
        <Bar dataKey="count" radius={[4, 4, 0, 0]} barSize={36}>
          {chartData.map((entry, index) => (
            <rect key={`cell-${index}`} fill={entry.fill} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}
