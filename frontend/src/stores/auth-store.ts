// ============================================================
// src/stores/auth-store.ts — 认证 / 权限 store
// ============================================================

"use client";

import { create } from "zustand";
import { getCurrentUser, type CurrentUser } from "@/lib/api/auth";

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  fetchUser: () => Promise<void>;
  hasPermission: (perm: string) => boolean;
  isAdmin: boolean;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  loading: true,

  fetchUser: async () => {
    try {
      const user = await getCurrentUser();
      set({ user, loading: false });
    } catch {
      set({ user: null, loading: false });
    }
  },

  hasPermission: (perm: string) => {
    const user = get().user;
    if (!user) return false;
    if (user.is_superuser) return true;
    if (user.permissions?.includes("all")) return true;
    return user.permissions?.includes(perm) ?? false;
  },

  get isAdmin() {
    const user = get().user;
    return !!user && (user.is_superuser || user.groups?.includes("Admin"));
  },

  logout: () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("pentest-token");
      localStorage.removeItem("pentest-refresh-token");
    }
    set({ user: null });
    window.location.href = "/login";
  },
}));
