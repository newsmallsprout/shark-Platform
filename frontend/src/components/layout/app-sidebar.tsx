"use client";

// ============================================================
// src/components/layout/app-sidebar.tsx — 主侧边栏（精简后）
// 安全测试(pentest) + 日志监控 + 排班 + 权限管理
// ============================================================

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import {
  LayoutDashboard,
  Target,
  FileText,
  BookOpen,
  Globe,
  Settings,
  Shield,
  Monitor,
  Calendar,
  Lock,
  LogOut,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";

interface NavItem {
  title: string;
  href: string;
  icon: any;
  perm?: string; // 无 perm 则登录即可见
}

// 安全测试 (pentest)
const SECURITY_ITEMS: NavItem[] = [
  { title: "安全总览", href: "/dashboard", icon: LayoutDashboard },
  { title: "渗透任务", href: "/tasks", icon: Target },
  { title: "测试报告", href: "/reports", icon: FileText },
  { title: "安全知识库", href: "/knowledge", icon: BookOpen },
  { title: "平台管理", href: "/platforms", icon: Globe },
  { title: "系统设置", href: "/settings", icon: Settings },
];

// 运维平台 (shark 在用功能)
const OPS_ITEMS: NavItem[] = [
  { title: "日志监控", href: "/logs", icon: Monitor, perm: "view_logs" },
  { title: "排班管理", href: "/schedules", icon: Calendar },
  { title: "权限管理", href: "/permissions", icon: Lock, perm: "manage_users" },
];

export function AppSidebar() {
  const pathname = usePathname();
  const { user, hasPermission, logout } = useAuthStore();

  const renderGroup = (label: string, items: NavItem[]) => {
    const visible = items.filter((i) => !i.perm || hasPermission(i.perm));
    if (visible.length === 0) return null;
    return (
      <SidebarGroup key={label}>
        <SidebarGroupLabel>{label}</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            {visible.map((item) => {
              const isActive =
                pathname === item.href || pathname.startsWith(item.href + "/");
              return (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    isActive={isActive}
                    tooltip={item.title}
                    render={
                      <Link href={item.href}>
                        <item.icon />
                        <span>{item.title}</span>
                      </Link>
                    }
                  />
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    );
  };

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              size="lg"
              render={
                <Link href="/dashboard">
                  <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                    <Shield className="size-4" />
                  </div>
                  <div className="flex flex-col gap-0.5 leading-none">
                    <span className="font-semibold">Shark Platform</span>
                    <span className="text-[10px] text-muted-foreground">
                      安全测试 + 运维平台
                    </span>
                  </div>
                </Link>
              }
            />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        {renderGroup("安全测试", SECURITY_ITEMS)}
        {renderGroup("运维平台", OPS_ITEMS)}
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              tooltip="退出登录"
              render={
                <button onClick={logout} className="w-full">
                  <LogOut />
                  <span>{user?.username ?? "未登录"}</span>
                </button>
              }
            />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
