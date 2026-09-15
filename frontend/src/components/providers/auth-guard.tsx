// ============================================================
// src/components/providers/auth-guard.tsx — 登录守卫
// 未登录跳 /login；登录后拉取用户 + 权限
// ============================================================

"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, loading, fetchUser } = useAuthStore();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("pentest-token")
        : null;

    if (!token) {
      router.replace("/login");
      return;
    }

    if (!user) {
      fetchUser().then(() => setChecked(true));
    } else {
      setChecked(true);
    }
  }, [user, fetchUser, router]);

  if (!checked) {
    return (
      <div className="flex h-screen items-center justify-center text-muted-foreground">
        加载中…
      </div>
    );
  }

  return <>{children}</>;
}
