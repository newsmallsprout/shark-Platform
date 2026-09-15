"use client";

// ============================================================
// src/components/layout/breadcrumb-nav.tsx — 动态面包屑
// ============================================================

import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";

// ---- 路径 → 中文标签映射 ----

const PATH_LABELS: Record<string, string> = {
  dashboard: "仪表盘",
  tasks: "任务列表",
  new: "新建任务",
  reports: "测试报告",
  knowledge: "知识库",
  platforms: "平台管理",
  settings: "系统设置",
  auto: "自动模式",
  guided: "引导模式",
};

export function BreadcrumbNav() {
  const pathname = usePathname();

  const segments = pathname
    .split("/")
    .filter((s) => s && !s.startsWith("("));

  if (
    segments.length === 0 ||
    (segments.length === 1 && segments[0] === "dashboard")
  ) {
    return null;
  }

  return (
    <Breadcrumb>
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbLink render={<Link href="/dashboard">仪表盘</Link>} />
        </BreadcrumbItem>

        {segments.map((segment, idx) => {
          const isLast = idx === segments.length - 1;
          const href = "/" + segments.slice(0, idx + 1).join("/");
          const label =
            PATH_LABELS[segment] ||
            (segment.length > 20 ? `${segment.slice(0, 20)}...` : segment);

          return (
            <BreadcrumbItem key={idx}>
              <BreadcrumbSeparator />
              {isLast ? (
                <BreadcrumbPage>{label}</BreadcrumbPage>
              ) : (
                <BreadcrumbLink render={<Link href={href}>{label}</Link>} />
              )}
            </BreadcrumbItem>
          );
        })}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
