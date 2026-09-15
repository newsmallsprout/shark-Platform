// ============================================================
// src/types/chat.ts — 引导模式对话 / AI 副驾驶类型定义
// ============================================================

// ---- 消息 ----

/** 消息角色 */
export type MessageRole = "user" | "assistant" | "system" | "tool";

/** 消息状态（仅 assistant 消息） */
export type MessageStatus = "pending" | "streaming" | "done" | "error";

/** 命令块（AI 让工程师执行的命令） */
export interface CommandBlock {
  /** 命令块唯一 ID（用于引用） */
  id: string;
  /** 要执行的命令 */
  command: string;
  /** 命令说明 */
  description: string;
  /** 预期输出说明 */
  expectedOutput?: string;
  /** 命令执行状态 */
  status: "pending" | "executing" | "completed" | "failed";
  /** 工程师粘贴的实际输出 */
  result?: string;
  /** 执行耗时（秒） */
  duration?: number;
  /** 时间戳 */
  timestamp: string;
}

/** 对话消息 */
export interface ChatMessage {
  /** 消息唯一 ID */
  id: string;
  /** 所属会话 ID */
  sessionId: string;
  /** 消息角色 */
  role: MessageRole;
  /** 消息内容（Markdown） */
  content: string;
  /** Assistant 消息状态 */
  status?: MessageStatus;
  /** 消息中包含的命令块（仅 assistant 消息） */
  commands?: CommandBlock[];
  /** 引用的上一条命令 */
  replyToCommandId?: string;
  /** 时间戳 */
  createdAt: string;
}

// ---- 引导阶段 ----

/** 引导模式阶段 */
export type GuidedStage =
  | "briefing"       // AI 讲解 scope / 目标
  | "recon"          // 信息收集 — AI 指导执行命令
  | "enumeration"    // 资产枚举
  | "vuln_analysis"  // 漏洞分析
  | "exploit"        // 漏洞利用
  | "post_exploit"   // 后渗透（可选）
  | "summary";       // AI 总结 / 下一步建议

/** 阶段快照（记录每个阶段做了什么） */
export interface StageSnapshot {
  stage: GuidedStage;
  status: "waiting" | "active" | "completed" | "skipped";
  /** 该阶段执行的命令数 */
  commandsExecuted: number;
  /** 该阶段发现的漏洞数 */
  vulnsFound: number;
  /** 阶段开始时间 */
  startedAt?: string;
  /** 阶段完成时间 */
  completedAt?: string;
}

// ---- 引导会话 ----

/** 引导模式会话 */
export interface GuidedSession {
  /** 会话唯一 ID */
  id: string;
  /** 关联的任务 ID */
  taskId: string;
  /** 当前阶段 */
  currentStage: GuidedStage;
  /** 各阶段快照 */
  stages: StageSnapshot[];
  /** 对话消息列表 */
  messages: ChatMessage[];
  /** 上下文窗口中的漏洞列表 */
  vulnsFound: Array<{
    name: string;
    severity: string;
    endpoint: string;
    description: string;
  }>;
  /** 会话开始时间 */
  startedAt: string;
  /** 最后活跃时间 */
  lastActiveAt: string;
  /** 会话是否已结束 */
  isCompleted: boolean;
}

// ---- SSE / Stream 相关 ----

/** AI 流式响应的 chunk */
export interface StreamChunk {
  type: "text" | "command" | "done" | "error";
  /** 文本增量 */
  content?: string;
  /** 命令块 */
  command?: Omit<CommandBlock, "id" | "status" | "timestamp">;
  /** 错误信息 */
  error?: string;
}

/** 发送给 AI 的消息 */
export interface SendMessagePayload {
  sessionId: string;
  content: string;
  /** 如果是回复某条命令，带上命令 ID 和结果 */
  commandResult?: {
    commandId: string;
    output: string;
  };
}

// ---- 常量 ----

/** 引导阶段中文名称 */
export const GUIDED_STAGE_LABELS: Record<GuidedStage, string> = {
  briefing: "任务简报",
  recon: "信息收集",
  enumeration: "资产枚举",
  vuln_analysis: "漏洞分析",
  exploit: "漏洞利用",
  post_exploit: "后渗透",
  summary: "总结建议",
};

/** 引导阶段顺序 */
export const GUIDED_STAGE_ORDER: GuidedStage[] = [
  "briefing",
  "recon",
  "enumeration",
  "vuln_analysis",
  "exploit",
  "post_exploit",
  "summary",
];
