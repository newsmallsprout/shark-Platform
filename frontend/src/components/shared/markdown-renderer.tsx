"use client";

// ============================================================
// src/components/shared/markdown-renderer.tsx — Markdown 渲染
// ============================================================

import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

interface MarkdownRendererProps {
  content: string;
  className?: string;
  /** 是否显示流式光标（AI 回复中） */
  isStreaming?: boolean;
}

export function MarkdownRenderer({
  content,
  className,
  isStreaming = false,
}: MarkdownRendererProps) {
  return (
    <div
      className={cn(
        "markdown-body",
        // 暗色模式下 prose-invert 等效样式已在 globals.css 定义
        isStreaming && "streaming-block",
        className
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          // 覆盖链接在新窗口打开
          a: ({ href, children, ...props }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            >
              {children}
            </a>
          ),
          // 代码块添加复制按钮
          code: ({ className: codeClassName, children, ...props }) => {
            const isInline = !codeClassName;
            if (isInline) {
              return (
                <code className={codeClassName} {...props}>
                  {children}
                </code>
              );
            }
            return (
              <code className={codeClassName} {...props}>
                {children}
              </code>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>

      {/* Streaming 光标 */}
      {isStreaming && (
        <span className="streaming-cursor inline-block" />
      )}
    </div>
  );
}
