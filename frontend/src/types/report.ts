// ============================================================
// src/types/report.ts — 报告类型定义
// ============================================================

import type { Severity } from "./task";
import type { Vulnerability } from "./scan";

// ---- 报告状态 ----

/** 报告状态 */
export type ReportStatus =
  | "draft"       // 草稿 — AI 生成初版，待人工复核
  | "reviewed"    // 已复核 — 工程师修改完成
  | "finalized"   // 已定稿 — 最终版，准备提交
  | "submitted"   // 已提交 — 已提交到众测平台
  | "accepted"    // 平台已接受
  | "rejected";   // 平台已驳回

// ---- 报告 ----

/** 报告摘要 */
export interface ReportSummary {
  /** 任务标题 */
  taskTitle: string;
  /** 目标 URL */
  targetUrl: string;
  /** 扫描起止时间 */
  scanPeriod: {
    startedAt: string;
    completedAt: string;
  };
  /** 扫描模式 */
  scanMode: "auto" | "guided";
  /** 总体风险评级 */
  overallSeverity: Severity;
  /** 各等级漏洞数量 */
  vulnCount: {
    critical: number;
    high: number;
    medium: number;
    low: number;
    info: number;
  };
  /** 扫描范围 */
  scope: string;
}

/** 修复时间线条目 */
export interface RemediationTimeline {
  /** 日期 */
  date: string;
  /** 事件描述 */
  event: string;
  /** 状态 */
  status: "open" | "in_progress" | "resolved";
}

/** 漏洞分组（按类型/OWASP 分类） */
export interface VulnerabilityGroup {
  /** 分组名称（如 SQL 注入） */
  name: string;
  /** OWASP 类别 */
  owaspCategory?: string;
  /** 该分组的漏洞列表 */
  vulns: Vulnerability[];
  /** 该分组漏洞总数 */
  count: number;
}

/** 完整报告 */
export interface Report {
  /** 报告唯一 ID */
  id: string;
  /** 关联的任务 ID */
  taskId: string;
  /** 报告标题 */
  title: string;
  /** 报告状态 */
  status: ReportStatus;
  /** 报告摘要 */
  summary: ReportSummary;
  /** 漏洞分组列表 */
  vulnGroups: VulnerabilityGroup[];
  /** 漏洞总数 */
  totalVulns: number;
  /** AI 生成的原始 Markdown 正文 */
  content: string;
  /** 人工编辑后的正文 */
  editedContent?: string;
  /** 修复建议 */
  remediationAdvice: string;
  /** 修复时间线 */
  remediationTimeline: RemediationTimeline[];
  /** 附录（额外信息） */
  appendix?: string;
  /** 报告创建者 */
  createdBy: string;
  /** 创建时间 */
  createdAt: string;
  /** 最后更新时间 */
  updatedAt: string;
  /** 提交到平台的时间 */
  submittedAt?: string;
  /** 平台反馈（如驳回原因） */
  platformFeedback?: string;
}

/** 创建报告请求 */
export interface CreateReportPayload {
  taskId: string;
  title: string;
  content: string;
}

/** 更新报告请求 */
export interface UpdateReportPayload {
  title?: string;
  content?: string;
  status?: ReportStatus;
}

/** 报告列表查询参数 */
export interface ReportListParams {
  page?: number;
  pageSize?: number;
  status?: ReportStatus;
  search?: string;
  sortBy?: "createdAt" | "updatedAt" | "status";
  sortOrder?: "asc" | "desc";
}

/** 报告列表响应 */
export interface ReportListResponse {
  reports: Report[];
  total: number;
  page: number;
  pageSize: number;
}

// ---- 常量 ----

/** ReportStatus 显示配置 */
export const REPORT_STATUS_CONFIG: Record<
  ReportStatus,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  draft: { label: "草稿", variant: "secondary" },
  reviewed: { label: "已复核", variant: "default" },
  finalized: { label: "已定稿", variant: "default" },
  submitted: { label: "已提交", variant: "default" },
  accepted: { label: "已接受", variant: "outline" },
  rejected: { label: "已驳回", variant: "destructive" },
};

/** 报告相关常量 */
export const REPORT_CONSTANTS = {
  /** 报告标题最大长度 */
  MAX_TITLE_LENGTH: 200,
  /** 列表每页默认条数 */
  DEFAULT_PAGE_SIZE: 20,
} as const;
