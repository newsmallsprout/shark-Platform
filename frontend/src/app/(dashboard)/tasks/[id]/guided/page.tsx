"use client";

// ============================================================
// src/app/(dashboard)/tasks/[id]/guided/page.tsx — 引导模式（真实 API）
// ============================================================

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StageProgress } from "@/components/guided-mode/stage-progress";
import { GuidedChat } from "@/components/guided-mode/guided-chat";
import { generateId } from "@/lib/utils";
import { apiClient } from "@/lib/api/client";
import type { ChatMessage, GuidedStage } from "@/types/chat";
import { GUIDED_STAGE_ORDER, GUIDED_STAGE_LABELS } from "@/types/chat";

export default function GuidedModePage() {
  const params = useParams();
  const router = useRouter();
  const taskId = params.id as string;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoadingMsg, setIsLoading] = useState(false);
  const [currentStage, setCurrentStage] = useState<GuidedStage>("recon");

  // 加载历史消息
  useEffect(() => {
    apiClient.get(`/tasks/${taskId}/guided/messages?page_size=100`).then((res) => {
      setMessages(res.data.messages || []);
    }).catch(() => {});
  }, [taskId]);

  // 发送消息
  const handleSend = useCallback(async (text: string) => {
    const now = new Date().toISOString();
    const userMsg: ChatMessage = {
      id: `msg-${generateId()}`,
      sessionId: "",
      role: "user",
      content: text,
      createdAt: now,
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const token = localStorage.getItem("pentest-token");
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"}/tasks/${taskId}/guided/messages`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`,
        },
        body: JSON.stringify({ content: text }),
      });

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let aiContent = "";

      const aiMsg: ChatMessage = {
        id: `msg-${generateId()}`,
        sessionId: "",
        role: "assistant",
        content: "",
        createdAt: new Date().toISOString(),
        commands: [],
      };

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value);
          for (const line of chunk.split("\n")) {
            if (line.startsWith("data: ")) {
              const data = line.slice(6);
              if (data === "[DONE]") continue;
              try {
                const parsed = JSON.parse(data);
                if (parsed.type === "text") {
                  aiContent += parsed.content;
                  aiMsg.content = aiContent;
                  setMessages((prev) => {
                    const last = prev[prev.length - 1];
                    if (last?.role === "assistant" && last.id === aiMsg.id) {
                      return [...prev.slice(0, -1), { ...aiMsg }];
                    }
                    if (last?.role !== "assistant" || last.id !== aiMsg.id) {
                      return [...prev, { ...aiMsg }];
                    }
                    return prev;
                  });
                } else if (parsed.type === "command") {
                  aiMsg.commands = [{
                    id: `cmd-${generateId()}`,
                    command: parsed.command.command,
                    description: parsed.command.description || "",
                    status: "pending",
                    timestamp: new Date().toISOString(),
                  }];
                }
              } catch {}
            }
          }
        }
      }
    } catch {
    } finally {
      setIsLoading(false);
    }
  }, [taskId]);

  const stages = GUIDED_STAGE_ORDER.map((stage) => ({
    stage,
    status: (stage === currentStage ? "active" : GUIDED_STAGE_ORDER.indexOf(stage) < GUIDED_STAGE_ORDER.indexOf(currentStage) ? "completed" : "waiting") as "active" | "completed" | "waiting",
  }));

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)] -m-6">
      <div className="flex items-center gap-4 px-6 py-3 border-b border-border bg-card/50">
        <Button variant="ghost" size="sm" onClick={() => router.push(`/tasks/${taskId}`)} className="gap-1 flex-shrink-0">
          <ArrowLeft className="h-4 w-4" />返回
        </Button>
        <div className="flex-1 overflow-x-auto">
          <StageProgress stages={stages} currentStage={currentStage} />
        </div>
      </div>
      <div className="flex-1 overflow-hidden">
        <GuidedChat messages={messages} onSend={handleSend} isLoading={isLoadingMsg} />
      </div>
    </div>
  );
}
