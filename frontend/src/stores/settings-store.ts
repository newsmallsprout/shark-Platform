// ============================================================
// src/stores/settings-store.ts — 设置全局状态
// ============================================================

import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

// ---- AI 配置 ----

export interface AIConfig {
  /** API Key */
  apiKey: string;
  /** 模型名称 */
  model: "gpt-4o" | "claude-3.5-sonnet" | "deepseek-v3" | "custom";
  /** 自定义模型名称（当 model === "custom"） */
  customModel?: string;
  /** API Base URL */
  baseUrl: string;
  /** 温度 0-2 */
  temperature: number;
}

// ---- 扫描配置 ----

export interface ScanConfig {
  /** 最大并发数 */
  maxConcurrency: number;
  /** 单工具超时（秒） */
  toolTimeout: number;
  /** 全任务超时（秒） */
  taskTimeout: number;
  /** 请求速率限制（请求/秒） */
  rateLimit: number;
  /** 自动验证漏洞（PoC） */
  autoVerify: boolean;
}

// ---- 平台账号配置 ----

export interface PlatformAccount {
  /** 平台标识 */
  platform: "butian" | "vulbox";
  /** Cookie */
  cookie: string;
  /** API Token */
  token: string;
  /** 账号昵称 */
  nickname: string;
  /** 是否已连接 */
  connected: boolean;
  /** 最后验证时间 */
  lastVerifiedAt?: string;
}

// ---- 通知配置 ----

export interface NotificationConfig {
  /** 任务完成时通知 */
  onTaskComplete: boolean;
  /** 发现严重/高危漏洞时通知 */
  onVulnFound: boolean;
  /** 报告提交成功时通知 */
  onReportSubmitted: boolean;
  /** 通知方式 */
  channel: "toast" | "email" | "webhook";
  /** Webhook URL（channel === "webhook"） */
  webhookUrl?: string;
}

// ---- Store 类型 ----

interface SettingsStore {
  // AI 配置
  ai: AIConfig;
  setAI: (partial: Partial<AIConfig>) => void;

  // 扫描配置
  scan: ScanConfig;
  setScan: (partial: Partial<ScanConfig>) => void;

  // 平台账号
  platforms: PlatformAccount[];
  setPlatformAccount: (account: PlatformAccount) => void;
  removePlatformAccount: (platform: "butian" | "vulbox") => void;
  getPlatformAccount: (platform: "butian" | "vulbox") => PlatformAccount | undefined;

  // 通知配置
  notifications: NotificationConfig;
  setNotifications: (partial: Partial<NotificationConfig>) => void;

  // 主题
  theme: "dark" | "light";
  toggleTheme: () => void;
}

// ---- 默认值 ----

const DEFAULT_AI: AIConfig = {
  apiKey: "",
  model: "gpt-4o",
  baseUrl: "https://api.openai.com/v1",
  temperature: 0.7,
};

const DEFAULT_SCAN: ScanConfig = {
  maxConcurrency: 5,
  toolTimeout: 3600,
  taskTimeout: 86400,
  rateLimit: 10,
  autoVerify: true,
};

const DEFAULT_PLATFORMS: PlatformAccount[] = [
  {
    platform: "butian",
    cookie: "",
    token: "",
    nickname: "",
    connected: false,
  },
  {
    platform: "vulbox",
    cookie: "",
    token: "",
    nickname: "",
    connected: false,
  },
];

const DEFAULT_NOTIFICATIONS: NotificationConfig = {
  onTaskComplete: true,
  onVulnFound: true,
  onReportSubmitted: true,
  channel: "toast",
};

// ---- Store 实现 ----

export const useSettingsStore = create<SettingsStore>()(
  devtools(
    persist(
      (set, get) => ({
        ai: { ...DEFAULT_AI },
        scan: { ...DEFAULT_SCAN },
        platforms: [...DEFAULT_PLATFORMS],
        notifications: { ...DEFAULT_NOTIFICATIONS },
        theme: "dark",

        setAI: (partial) =>
          set((s) => ({ ai: { ...s.ai, ...partial } })),

        setScan: (partial) =>
          set((s) => ({ scan: { ...s.scan, ...partial } })),

        setPlatformAccount: (account) =>
          set((s) => ({
            platforms: s.platforms.map((p) =>
              p.platform === account.platform ? { ...account } : p
            ),
          })),

        removePlatformAccount: (platform) =>
          set((s) => ({
            platforms: s.platforms.map((p) =>
              p.platform === platform
                ? { ...p, cookie: "", token: "", nickname: "", connected: false }
                : p
            ),
          })),

        getPlatformAccount: (platform) =>
          get().platforms.find((p) => p.platform === platform),

        setNotifications: (partial) =>
          set((s) => ({
            notifications: { ...s.notifications, ...partial },
          })),

        toggleTheme: () =>
          set((s) => ({
            theme: s.theme === "dark" ? "light" : "dark",
          })),
      }),
      {
        name: "pentest-settings",
        partialize: (state) => ({
          ai: state.ai,
          scan: state.scan,
          platforms: state.platforms,
          notifications: state.notifications,
          theme: state.theme,
        }),
      }
    ),
    { name: "settings-store" }
  )
);
