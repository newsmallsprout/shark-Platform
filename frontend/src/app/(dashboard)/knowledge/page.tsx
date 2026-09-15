"use client";

// ============================================================
// src/app/(dashboard)/knowledge/page.tsx — 知识库
// ============================================================

import { useState } from "react";
import {
  Search,
  BookOpen,
  ExternalLink,
  Database,
  Download,
  Clock,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { formatRelativeTime } from "@/lib/utils";

// ---- Mock 知识库文章 ----

const MOCK_ARTICLES = [
  {
    id: "1",
    title: "SQL Injection Cheat Sheet",
    source: "HackTricks" as const,
    tags: ["SQL注入", "CheatSheet"],
    url: "https://book.hacktricks.xyz/pentesting-web/sql-injection",
    createdAt: "2026-07-20T10:00:00Z",
  },
  {
    id: "2",
    title: "CVE-2026-1234: Apache Tomcat RCE",
    source: "CVE" as const,
    tags: ["RCE", "Tomcat", "CVE"],
    url: "https://nvd.nist.gov/vuln/detail/CVE-2026-1234",
    createdAt: "2026-07-25T08:00:00Z",
  },
  {
    id: "3",
    title: "HackerOne Report #2456789 — SSRF to AWS Metadata",
    source: "HackerOne" as const,
    tags: ["SSRF", "AWS", "云安全"],
    url: "https://hackerone.com/reports/2456789",
    createdAt: "2026-07-31T02:00:00Z",
  },
  {
    id: "4",
    title: "OAuth 2.0 常见漏洞与利用",
    source: "自定义" as const,
    tags: ["OAuth", "认证", "Web"],
    url: "",
    createdAt: "2026-07-28T15:00:00Z",
  },
  {
    id: "5",
    title: "Nginx 配置安全最佳实践",
    source: "自定义" as const,
    tags: ["Nginx", "配置", "加固"],
    url: "",
    createdAt: "2026-07-29T11:00:00Z",
  },
];

type SourceFilter = "all" | "HackTricks" | "HackerOne" | "CVE" | "自定义";

const SOURCE_COLORS: Record<string, string> = {
  HackTricks: "bg-purple-500/15 text-purple-400",
  HackerOne: "bg-green-500/15 text-green-400",
  CVE: "bg-red-500/15 text-red-400",
  "自定义": "bg-blue-500/15 text-blue-400",
};

const STATS = {
  documentCount: 128,
  vectorCount: 45600,
  lastUpdated: "2026-07-31T06:00:00Z",
};

export default function KnowledgePage() {
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [importUrl, setImportUrl] = useState("");

  const filtered = MOCK_ARTICLES.filter((a) => {
    if (sourceFilter !== "all" && a.source !== sourceFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        a.title.toLowerCase().includes(q) ||
        a.tags.some((t) => t.toLowerCase().includes(q))
      );
    }
    return true;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">知识库</h1>
        <p className="text-sm text-muted-foreground mt-1">
          AI 安全知识库 — 漏洞利用技巧、CVE、报告参考
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：文章列表 */}
        <div className="lg:col-span-2 space-y-4">
          {/* 搜索 + 筛选 */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="搜索知识库..."
                className="pl-8"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <Select
              value={sourceFilter}
              onValueChange={(v) => setSourceFilter(v as SourceFilter)}
            >
              <SelectTrigger className="w-[120px]">
                <SelectValue placeholder="来源" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部来源</SelectItem>
                <SelectItem value="HackTricks">HackTricks</SelectItem>
                <SelectItem value="HackerOne">HackerOne</SelectItem>
                <SelectItem value="CVE">CVE</SelectItem>
                <SelectItem value="自定义">自定义</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* 文章卡片 */}
          {filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              未找到匹配的文章
            </p>
          ) : (
            <div className="space-y-2">
              {filtered.map((article) => (
                <Card
                  key={article.id}
                  className="hover:border-primary/30 transition-colors"
                >
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <Badge
                            variant="outline"
                            className={SOURCE_COLORS[article.source] ?? ""}
                          >
                            {article.source}
                          </Badge>
                          {article.tags.map((tag) => (
                            <Badge
                              key={tag}
                              variant="secondary"
                              className="text-[10px]"
                            >
                              {tag}
                            </Badge>
                          ))}
                        </div>
                        <h4 className="text-sm font-medium">
                          {article.title}
                        </h4>
                        <p className="text-[11px] text-muted-foreground mt-1">
                          <Clock className="h-3 w-3 inline mr-1" />
                          {formatRelativeTime(article.createdAt)}
                        </p>
                      </div>
                      {article.url && (
                        <a
                          href={article.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex-shrink-0"
                        >
                          <ExternalLink className="h-4 w-4 text-muted-foreground hover:text-foreground" />
                        </a>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>

        {/* 右侧边栏：数据导入 + 统计 */}
        <div className="space-y-4">
          {/* 导入配置 */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">导入数据来源</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Input
                placeholder="输入文档 URL 或 RSS 地址..."
                value={importUrl}
                onChange={(e) => setImportUrl(e.target.value)}
              />
              <Button className="w-full gap-1" size="sm">
                <Download className="h-4 w-4" />
                导入
              </Button>
              <p className="text-[10px] text-muted-foreground">
                支持 HackTricks、HackerOne 公开报告、CVE 数据库等
              </p>
            </CardContent>
          </Card>

          {/* 知识库统计 */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">知识库统计</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground flex items-center gap-2">
                  <BookOpen className="h-4 w-4" />
                  文档数量
                </span>
                <span className="text-sm font-mono font-semibold">
                  {STATS.documentCount}
                </span>
              </div>
              <Separator />
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground flex items-center gap-2">
                  <Database className="h-4 w-4" />
                  向量数量
                </span>
                <span className="text-sm font-mono font-semibold">
                  {STATS.vectorCount.toLocaleString()}
                </span>
              </div>
              <Separator />
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  最后更新
                </span>
                <span className="text-sm">
                  {formatRelativeTime(STATS.lastUpdated)}
                </span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
