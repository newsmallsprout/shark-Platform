// ============================================================
// src/types/task.ts — 任务相关类型定义
// ============================================================

/** 众测平台 */
export type Platform = "butian" | "vulbox" | "custom";

/** 扫描模式 */
export type TaskMode = "auto" | "guided";

/** 漏洞等级 */
export type Severity = "critical" | "high" | "medium" | "low" | "info";

/** 任务状态 */
export type TaskStatus =
  | "pending"    // 待开始
  | "running"    // 扫描中
  | "analyzing"  // AI 分析中
  | "completed"  // 已完成
  | "failed"     // 失败
  | "cancelled"; // 已取消

/** 任务范围 / Scope */
export interface Scope {
  /** 目标 URL */
  targetUrl: string;
  /** 是否允许自动扫描（false → 只能走 guided 模式） */
  allowAutoScan: boolean;
  /** 允许扫描的路径（白名单） */
  allowedPaths: string[];
  /** 排除的路径（黑名单） */
  excludedPaths: string[];
  /** 额外的 scope 说明（如「禁止扫描 /admin 子域」） */
  notes?: string;
}

/** 各等级漏洞数量 */
export interface VulnCount {
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
}

/** 任务 */
export interface Task {
  /** 任务唯一 ID */
  id: string;
  /** 任务标题 */
  title: string;
  /** 所属平台 */
  platform: Platform;
  /** 扫描模式 */
  mode: TaskMode;
  /** 任务状态 */
  status: TaskStatus;
  /** 任务范围 */
  scope: Scope;
  /** 扫描进度 0-100 */
  progress: number;
  /** 发现的漏洞统计 */
  vulnCount: VulnCount;
  /** 分配给的安全工程师 */
  assignee?: string;
  /** 创建时间 (ISO 8601) */
  createdAt: string;
  /** 最后更新时间 (ISO 8601) */
  updatedAt: string;
  /** 完成时间 (ISO 8601) */
  completedAt?: string;
  /** 任务备注 */
  notes?: string;
}

/** 创建任务请求体 */
export interface CreateTaskPayload {
  title: string;
  platform: Platform;
  mode: TaskMode;
  scope: Scope;
  platformTaskId?: string;
  tags?: string[];
  notes?: string;
}

/** 更新任务请求体 */
export interface UpdateTaskPayload {
  title?: string;
  status?: TaskStatus;
  notes?: string;
}

/** 任务列表查询参数 */
export interface TaskListParams {
  page?: number;
  pageSize?: number;
  status?: TaskStatus;
  platform?: Platform;
  mode?: TaskMode;
  search?: string;
  sortBy?: "createdAt" | "updatedAt" | "status";
  sortOrder?: "asc" | "desc";
}

/** 任务列表响应 */
export interface TaskListResponse {
  tasks: Task[];
  total: number;
  page: number;
  pageSize: number;
}

/** 平台配置信息 */
export interface PlatformConfig {
  name: Platform;
  label: string;
  description: string;
  /** 平台 icon (lucide 图标名) */
  icon: string;
  /** 是否需要额外 API Key */
  requiresApiKey: boolean;
  /** 平台官网 URL */
  websiteUrl: string;
}

/** 预置的平台列表 */
export const PLATFORM_CONFIGS: PlatformConfig[] = [
  {
    name: "butian",
    label: "补天",
    description: "补天漏洞响应平台",
    icon: "shield",
    requiresApiKey: true,
    websiteUrl: "https://www.butian.net",
  },
  {
    name: "vulbox",
    label: "漏洞盒子",
    description: "漏洞盒子众测平台",
    icon: "box",
    requiresApiKey: true,
    websiteUrl: "https://www.vulbox.com",
  },
  {
    name: "custom",
    label: "自定义",
    description: "手动指定目标范围",
    icon: "target",
    requiresApiKey: false,
    websiteUrl: "",
  },
];

/** Severity 显示配置 */
export const SEVERITY_CONFIG: Record<
  Severity,
  { label: string; color: string; bgColor: string; order: number }
> = {
  critical: {
    label: "严重",
    color: "text-red-400",
    bgColor: "bg-red-500/10",
    order: 0,
  },
  high: {
    label: "高危",
    color: "text-orange-400",
    bgColor: "bg-orange-500/10",
    order: 1,
  },
  medium: {
    label: "中危",
    color: "text-yellow-400",
    bgColor: "bg-yellow-500/10",
    order: 2,
  },
  low: {
    label: "低危",
    color: "text-blue-400",
    bgColor: "bg-blue-500/10",
    order: 3,
  },
  info: {
    label: "信息",
    color: "text-muted-foreground",
    bgColor: "bg-muted/50",
    order: 4,
  },
};

/** TaskStatus 显示配置 */
export const TASK_STATUS_CONFIG: Record<
  TaskStatus,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  pending: { label: "待开始", variant: "secondary" },
  running: { label: "扫描中", variant: "default" },
  analyzing: { label: "分析中", variant: "default" },
  completed: { label: "已完成", variant: "outline" },
  failed: { label: "失败", variant: "destructive" },
  cancelled: { label: "已取消", variant: "secondary" },
};
