// ============================================================
// src/app/(dashboard)/layout.tsx — 仪表盘布局
// ============================================================

import { SidebarProvider, SidebarInset, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { BreadcrumbNav } from "@/components/layout/breadcrumb-nav";
import { Separator } from "@/components/ui/separator";
import { AuthGuard } from "@/components/providers/auth-guard";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthGuard>
      <SidebarProvider>
        {/* 侧边栏 */}
        <AppSidebar />

        {/* 主内容区 */}
        <SidebarInset>
          {/* 顶部栏 */}
          <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
            <SidebarTrigger className="-ml-1" />
            <Separator orientation="vertical" className="mr-2 h-4" />
            <BreadcrumbNav />
          </header>

          {/* 页面内容 */}
          <main className="flex-1 overflow-auto p-6">{children}</main>
        </SidebarInset>
      </SidebarProvider>
    </AuthGuard>
  );
}
