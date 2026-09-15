// ============================================================
// src/app/page.tsx — 首页 → 重定向到 /dashboard
// ============================================================

import { redirect } from "next/navigation";

export default function HomePage() {
  redirect("/dashboard");
}
