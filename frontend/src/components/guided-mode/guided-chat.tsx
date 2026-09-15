"use client";

// ============================================================
// src/components/guided-mode/guided-chat.tsx — 引导对话界面
// ============================================================

import { useEffect, useRef, useState } from "react";
import { Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { MarkdownRenderer } from "@/components/shared/markdown-renderer";
import { CommandCard } from "@/components/guided-mode/command-card";
import { ResultInput } from "@/components/guided-mode/result-input";
import type { ChatMessage } from "@/types/chat";

interface GuidedChatProps {
  messages: ChatMessage[];
  onSend: (text: string) => void;
  isLoading: boolean;
}

export function GuidedChat({ messages, onSend, isLoading }: GuidedChatProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  return (
    <div className="flex flex-col h-full">
      {/* 消息列表 */}
      <div ref={scrollRef} className="flex-1 overflow-auto p-4 space-y-4">
        {messages
          .filter((m) => m.role !== "system")
          .map((msg) => (
            <ChatBubble key={msg.id} message={msg} isStreaming={msg.status === "streaming"} />
          ))}

        {/* Loading 占位 */}
        {isLoading && (
          <div className="flex items-start gap-3">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/20 flex-shrink-0 mt-0.5">
              <Bot className="h-4 w-4 text-primary" />
            </div>
            <div className="flex-1 rounded-lg bg-muted/50 px-4 py-3">
              <span className="streaming-cursor text-sm text-muted-foreground" />
            </div>
          </div>
        )}
      </div>

      {/* 底部输入 */}
      <ResultInput onSend={onSend} isLoading={isLoading} />
    </div>
  );
}

// ---- 聊天气泡 ----

function ChatBubble({
  message,
  isStreaming = false,
}: {
  message: ChatMessage;
  isStreaming?: boolean;
}) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  return (
    <div
      className={cn(
        "flex items-start gap-3",
        isUser && "flex-row-reverse"
      )}
    >
      {/* 头像 */}
      <div
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-full flex-shrink-0 mt-0.5",
          isUser
            ? "bg-blue-500/20"
            : "bg-primary/20"
        )}
      >
        {isUser ? (
          <User className="h-3.5 w-3.5 text-blue-400" />
        ) : (
          <Bot className="h-3.5 w-3.5 text-primary" />
        )}
      </div>

      {/* 消息内容 */}
      <div
        className={cn(
          "flex-1 min-w-0 max-w-[85%]",
          isUser && "flex flex-col items-end"
        )}
      >
        <div
          className={cn(
            "rounded-lg px-4 py-3 text-sm",
            isUser
              ? "bg-blue-500/15 text-foreground"
              : "bg-muted/50 text-foreground"
          )}
        >
          {isAssistant ? (
            <MarkdownRenderer content={message.content} isStreaming={isStreaming} />
          ) : (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          )}
        </div>

        {/* 命令卡片（assistant 消息附带） */}
        {isAssistant &&
          message.commands &&
          message.commands.length > 0 && (
            <div className="mt-2 space-y-2">
              {message.commands.map((cmd) => (
                <CommandCard key={cmd.id} command={cmd} />
              ))}
            </div>
          )}
      </div>
    </div>
  );
}
