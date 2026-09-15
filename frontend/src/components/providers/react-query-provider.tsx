"use client";

// ============================================================
// src/components/providers/react-query-provider.tsx
// React Query Provider — 客户端数据管理
// ============================================================

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

// ---- QueryClient 配置 ----

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // 数据保持新鲜 30 秒，之后自动 refetch
        staleTime: 30 * 1000,
        // 缓存保留 5 分钟
        gcTime: 5 * 60 * 1000,
        // 失败后重试 2 次
        retry: 2,
        // 窗口重新聚焦时自动 refetch
        refetchOnWindowFocus: true,
        // 断网重连时自动 refetch
        refetchOnReconnect: true,
      },
      mutations: {
        // 失败后重试 1 次
        retry: 1,
      },
    },
  });
}

// ---- Provider 组件 ----

let browserQueryClient: QueryClient | undefined;

function getQueryClient() {
  // 服务端：每次请求新建
  if (typeof window === "undefined") {
    return makeQueryClient();
  }
  // 客户端：复用同一个实例
  if (!browserQueryClient) {
    browserQueryClient = makeQueryClient();
  }
  return browserQueryClient;
}

export function ReactQueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(getQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}
