// ============================================================
// src/stores/scan-store.ts — 扫描会话全局状态
// ============================================================

import { create } from "zustand";
import type { ScanSession, ScanLogEntry } from "@/types/scan";
import { getScanSession } from "@/lib/api/scans";

interface ScanStore {
  session: ScanSession | null;
  isLoading: boolean;
  loadSession: (taskId: string) => Promise<void>;
  appendLog: (entry: Omit<ScanLogEntry, "timestamp">) => void;
  reset: () => void;
}

export const useScanStore = create<ScanStore>()((set, get) => ({
  session: null,
  isLoading: false,

  loadSession: async (taskId) => {
    set({ isLoading: true });
    try {
      const session = await getScanSession(taskId);
      set({ session });
    } finally { set({ isLoading: false }); }
  },

  appendLog: (entry) => {
    const log: ScanLogEntry = { ...entry, timestamp: new Date().toISOString() };
    set((s) => ({
      session: s.session ? { ...s.session, logs: [...s.session.logs, log] } : null,
    }));
  },

  reset: () => set({ session: null, isLoading: false }),
}));
