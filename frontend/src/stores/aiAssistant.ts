import { ref } from 'vue'

/** 全局：是否有 LangGraph / SSE 诊断在运行（驱动顶栏与侧栏「思考」态） */
export const aiAssistantThinking = ref(false)

export function setAiAssistantThinking(v: boolean) {
  aiAssistantThinking.value = v
}
