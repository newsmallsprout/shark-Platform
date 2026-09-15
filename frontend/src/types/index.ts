// ============================================================
// src/types/index.ts — 类型统一导出入口
// ============================================================

export type {
  Platform,
  TaskMode,
  Severity,
  TaskStatus,
  Scope,
  VulnCount,
  Task,
  CreateTaskPayload,
  UpdateTaskPayload,
  TaskListParams,
  TaskListResponse,
  PlatformConfig,
} from "./task";
export {
  PLATFORM_CONFIGS,
  SEVERITY_CONFIG,
  TASK_STATUS_CONFIG,
} from "./task";

export type {
  ScanStage,
  StageProgress,
  ScanToolType,
  ToolStatus,
  ScanTool,
  ToolConfig,
  AssetType,
  Asset,
  VulnerabilityStatus,
  Vulnerability,
  ScanSession,
  ScanLogEntry,
} from "./scan";
export {
  SCAN_STAGE_ORDER,
  SCAN_STAGE_LABELS,
  SCAN_TOOL_LABELS,
} from "./scan";

export type {
  MessageRole,
  MessageStatus,
  CommandBlock,
  ChatMessage,
  GuidedStage,
  StageSnapshot,
  GuidedSession,
  StreamChunk,
  SendMessagePayload,
} from "./chat";
export {
  GUIDED_STAGE_LABELS,
  GUIDED_STAGE_ORDER,
} from "./chat";

export type {
  ReportStatus,
  ReportSummary,
  RemediationTimeline,
  VulnerabilityGroup,
  Report,
  CreateReportPayload,
  UpdateReportPayload,
  ReportListParams,
  ReportListResponse,
} from "./report";
export {
  REPORT_STATUS_CONFIG,
  REPORT_CONSTANTS,
} from "./report";
