// ============================================================
// src/types/scan.ts — 扫描会话、工具、资产、漏洞类型定义
// ============================================================

import type { Severity } from "./task";

// ---- 扫描阶段 ----

/** 扫描阶段 */
export type ScanStage =
  | "init"           // 初始化（加载 scope、配置工具）
  | "recon"          // 信息收集（子域枚举、端口扫描）
  | "discovery"      // 资产发现（识别服务、指纹）
  | "vuln_scan"      // 漏洞扫描（nuclei/sqlmap/xray）
  | "exploit"        // 漏洞利用验证（PoC）
  | "post_exploit"   // 后渗透（横向移动、权限维持跳过）
  | "reporting";     // 生成报告

/** 每个扫描阶段的进度 */
export interface StageProgress {
  stage: ScanStage;
  /** 当前阶段状态 */
  status: "waiting" | "running" | "completed" | "skipped" | "failed";
  /** 当前阶段进度 0-100 */
  progress: number;
  /** 阶段开始时间 */
  startedAt?: string;
  /** 阶段完成时间 */
  completedAt?: string;
  /** 阶段日志摘要 */
  summary?: string;
}

// ---- 扫描工具 ----

/** 扫描工具类型 */
export type ScanToolType =
  | "nmap"
  | "nuclei"
  | "sqlmap"
  | "xray"
  | "burp"
  | "ffuf"
  | "gobuster"
  | "amass"
  | "subfinder"
  | "httpx"
  | "custom";

/** 扫描工具运行状态 */
export type ToolStatus = "pending" | "running" | "completed" | "failed" | "timeout";

/** 单个扫描工具实例 */
export interface ScanTool {
  /** 工具唯一 ID */
  id: string;
  /** 工具类型 */
  type: ScanToolType;
  /** 工具显示名称 */
  name: string;
  /** 运行状态 */
  status: ToolStatus;
  /** 启动时间 */
  startedAt?: string;
  /** 完成时间 */
  completedAt?: string;
  /** 执行的命令 */
  command?: string;
  /** 工具输出（摘要） */
  output?: string;
  /** 错误信息 */
  error?: string;
  /** 发现的资产数 */
  assetsFound: number;
  /** 发现的漏洞数 */
  vulnsFound: number;
}

/** 工具配置 */
export interface ToolConfig {
  type: ScanToolType;
  enabled: boolean;
  /** 超时时间（秒） */
  timeout: number;
  /** 额外参数 */
  extraArgs?: string;
}

// ---- 资产 ----

/** 资产类型 */
export type AssetType =
  | "ip"
  | "domain"
  | "subdomain"
  | "url"
  | "port"
  | "service"
  | "certificate"
  | "email"
  | "other";

/** 发现的资产 */
export interface Asset {
  /** 资产唯一 ID */
  id: string;
  /** 资产类型 */
  type: AssetType;
  /** 资产值（IP / 域名 / URL） */
  value: string;
  /** 端口（如有） */
  port?: number;
  /** 服务名（如 http, ssh, mysql） */
  service?: string;
  /** 服务版本 */
  version?: string;
  /** HTTP 状态码 */
  statusCode?: number;
  /** HTTP 响应标题 */
  title?: string;
  /** SSL/TLS 证书信息 */
  certificate?: {
    issuer: string;
    subject: string;
    validFrom: string;
    validTo: string;
  };
  /** 发现该资产的工具 */
  discoveredBy: string;
  /** 发现时间 */
  discoveredAt: string;
}

// ---- 漏洞 ----

/** 漏洞状态 */
export type VulnerabilityStatus =
  | "new"            // 新发现
  | "confirmed"      // 已验证
  | "false_positive" // 误报
  | "duplicate"      // 重复
  | "accepted"       // 已接受风险
  | "fixed";         // 已修复

/** 漏洞详情 */
export interface Vulnerability {
  /** 漏洞唯一 ID */
  id: string;
  /** 漏洞名称 */
  name: string;
  /** 漏洞等级 */
  severity: Severity;
  /** CVE 编号（如有） */
  cveId?: string;
  /** CVSS 评分 0-10 */
  cvssScore?: number;
  /** 漏洞描述 */
  description: string;
  /** 漏洞所在资产 */
  asset: Pick<Asset, "id" | "type" | "value">;
  /** 漏洞 URL / 端点 */
  endpoint: string;
  /** 请求方法 */
  method?: string;
  /** 攻击 Payload */
  payload?: string;
  /** 漏洞证明（PoC） */
  evidence?: string;
  /** 修复建议 */
  remediation: string;
  /** 参考链接 */
  references: string[];
  /** 漏洞状态 */
  status: VulnerabilityStatus;
  /** 发现该漏洞的工具 */
  discoveredBy: string;
  /** 发现时间 */
  discoveredAt: string;
  /** 关联的 OWASP Top 10 类别 */
  owaspCategory?: string;
  /** 标签 */
  tags: string[];
}

// ---- 扫描会话 ----

/** 扫描会话 */
export interface ScanSession {
  /** 会话唯一 ID */
  id: string;
  /** 关联的任务 ID */
  taskId: string;
  /** 各阶段进度 */
  stages: StageProgress[];
  /** 当前阶段 */
  currentStage: ScanStage;
  /** 全局扫描进度 0-100 */
  overallProgress: number;
  /** 启用的工具列表 */
  tools: ScanTool[];
  /** 发现的资产列表 */
  assets: Asset[];
  /** 发现的漏洞列表 */
  vulnerabilities: Vulnerability[];
  /** 扫描开始时间 */
  startedAt?: string;
  /** 扫描完成时间 */
  completedAt?: string;
  /** 预估剩余时间（秒） */
  estimatedTimeRemaining?: number;
  /** 扫描日志（最近 500 条） */
  logs: ScanLogEntry[];
}

/** 扫描日志条目 */
export interface ScanLogEntry {
  /** 时间戳 */
  timestamp: string;
  /** 日志级别 */
  level: "info" | "warn" | "error" | "debug" | "success";
  /** 日志来源（工具名 / 系统） */
  source: string;
  /** 日志内容 */
  message: string;
}

// ---- 扫描阶段常量 ----

/** 扫描阶段顺序 */
export const SCAN_STAGE_ORDER: ScanStage[] = [
  "init",
  "recon",
  "discovery",
  "vuln_scan",
  "exploit",
  "post_exploit",
  "reporting",
];

/** 扫描阶段中文名称 */
export const SCAN_STAGE_LABELS: Record<ScanStage, string> = {
  init: "初始化",
  recon: "信息收集",
  discovery: "资产发现",
  vuln_scan: "漏洞扫描",
  exploit: "漏洞验证",
  post_exploit: "后渗透",
  reporting: "生成报告",
};

/** 工具类型中文名称 */
export const SCAN_TOOL_LABELS: Record<ScanToolType, string> = {
  nmap: "Nmap",
  nuclei: "Nuclei",
  sqlmap: "SQLMap",
  xray: "Xray",
  burp: "Burp Suite",
  ffuf: "FFUF",
  gobuster: "Gobuster",
  amass: "Amass",
  subfinder: "Subfinder",
  httpx: "HTTPx",
  custom: "自定义工具",
};
