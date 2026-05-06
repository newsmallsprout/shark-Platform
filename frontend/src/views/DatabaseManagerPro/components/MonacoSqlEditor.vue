<template>
  <div class="monaco-wrapper">
    <div ref="containerRef" class="monaco-container"></div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import loader from '@monaco-editor/loader'

type EditorSnippet = { label: string; insertText: string; detail?: string }

type SqlCompletionItem = {
  label: string
  detail?: string
  schema?: string
  table?: string
  column?: string
  kind?: string
}

const props = withDefaults(
  defineProps<{
    modelValue: string
    language?: string
    suggestions?: SqlCompletionItem[]
    extraSnippets?: EditorSnippet[]
    /** When set, completion loads asynchronously (supports table vs column mode). */
    fetchCompletions?: (keyword: string, suggestTables: boolean) => Promise<SqlCompletionItem[]>
  }>(),
  {
    language: 'sql',
    suggestions: () => [],
    extraSnippets: () => []
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const containerRef = ref<HTMLElement | null>(null)
let editor: any = null
let monacoRef: any = null
let providerDisposable: any = null
let hoverDisposable: any = null
let changeDisposable: any = null
let resizeObserver: ResizeObserver | null = null

const defaultSqlSnippets: EditorSnippet[] = [
  { label: 'SELECT 模板', insertText: 'SELECT ${1:*}\\nFROM ${2:table_name}\\nWHERE ${3:condition};', detail: '基础查询模板' },
  { label: 'UPDATE 模板', insertText: 'UPDATE ${1:table_name}\\nSET ${2:column} = ${3:value}\\nWHERE ${4:id} = ${5:1};', detail: '更新模板' },
  { label: 'DELETE 模板', insertText: 'DELETE FROM ${1:table_name}\\nWHERE ${2:id} = ${3:1};', detail: '删除模板' }
]

const activeSnippets = () => {
  const lang = props.language || 'sql'
  const base = ['sql', 'mysql', 'pgsql'].includes(lang) ? defaultSqlSnippets : []
  return [...base, ...props.extraSnippets]
}

const isSqlLikeLanguage = () => ['sql', 'mysql', 'pgsql'].includes(props.language || 'sql')

/** Text before cursor with the partial word at cursor stripped so trailing keywords match. */
function sqlPrefixBeforeCursor(model: any, position: any): string {
  const offset = model.getOffsetAt(position)
  const full = model.getValue()
  let slice = full.slice(0, offset)
  const word = model.getWordUntilPosition(position)
  if (word?.word) {
    const line = model.getLineContent(position.lineNumber)
    const suf = line.slice(0, position.column - 1)
    if (suf.endsWith(word.word)) {
      slice = slice.slice(0, slice.length - word.word.length)
    }
  }
  return slice.replace(/\s+$/, '')
}

/** True after FROM / JOIN / INTO / UPDATE etc., when user expects a table name. */
function sqlCompletionWantsTables(model: any, position: any): boolean {
  if (!isSqlLikeLanguage()) return false
  const trimmed = sqlPrefixBeforeCursor(model, position)
  const t = trimmed.toUpperCase()
  return (
    /\b(FROM|JOIN|INTO|UPDATE)\s*$/.test(t) ||
    /\b(ALTER|DROP|TRUNCATE)\s+TABLE\s*$/.test(t)
  )
}

function completionKind(monaco: any, item: SqlCompletionItem): number {
  const k = item.kind
  if (k === 'table') return monaco.languages.CompletionItemKind.Struct
  if (k === 'column') return monaco.languages.CompletionItemKind.Field
  if (k === 'keyword') return monaco.languages.CompletionItemKind.Keyword
  return monaco.languages.CompletionItemKind.Field
}

const applyMarkers = () => {
  if (!monacoRef || !editor) return
  const model = editor.getModel()
  if (!model) return
  if (!isSqlLikeLanguage()) {
    monacoRef.editor.setModelMarkers(model, 'sql-guard', [])
    return
  }
  const value = model.getValue() || ''
  const markers: any[] = []
  const openCount = (value.match(/\(/g) || []).length
  const closeCount = (value.match(/\)/g) || []).length
  if (openCount !== closeCount) {
    markers.push({
      startLineNumber: 1,
      startColumn: 1,
      endLineNumber: 1,
      endColumn: 1,
      message: '括号数量不匹配',
      severity: monacoRef.MarkerSeverity.Error
    })
  }
  if (/^\s*(update|delete)\b/i.test(value) && !/\bwhere\b/i.test(value)) {
    markers.push({
      startLineNumber: 1,
      startColumn: 1,
      endLineNumber: 1,
      endColumn: 1,
      message: 'UPDATE/DELETE 缺少 WHERE 条件',
      severity: monacoRef.MarkerSeverity.Warning
    })
  }
  monacoRef.editor.setModelMarkers(model, 'sql-guard', markers)
}

const registerCompletion = () => {
  if (!monacoRef) return
  const lang = props.language || 'sql'
  if (providerDisposable) {
    providerDisposable.dispose()
  }
  providerDisposable = monacoRef.languages.registerCompletionItemProvider(lang, {
    triggerCharacters: ['.', ' ', '_', '$', '{'],
    provideCompletionItems: async (model: any, position: any) => {
      const word = model.getWordUntilPosition(position)
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn
      }
      const wantsTables = sqlCompletionWantsTables(model, position)
      let items: SqlCompletionItem[] = []
      if (props.fetchCompletions) {
        try {
          items = await props.fetchCompletions(word.word || '', wantsTables)
        } catch {
          items = []
        }
      } else {
        items = props.suggestions || []
      }
      const snippets = wantsTables ? [] : activeSnippets()
      return {
        suggestions: [
          ...items.map((item) => ({
            label: item.label,
            kind: completionKind(monacoRef, item),
            insertText: item.label,
            detail: item.detail || '',
            documentation: item.detail || '',
            range
          })),
          ...snippets.map((item) => ({
            label: item.label,
            kind: monacoRef.languages.CompletionItemKind.Snippet,
            insertText: item.insertText,
            insertTextRules: monacoRef.languages.CompletionItemInsertTextRule.InsertAsSnippet,
            detail: item.detail,
            range
          }))
        ]
      }
    }
  })
  if (hoverDisposable) {
    hoverDisposable.dispose()
  }
  hoverDisposable = monacoRef.languages.registerHoverProvider(lang, {
    provideHover(model: any, position: any) {
      const word = model.getWordAtPosition(position)
      if (!word) return null
      const pool = props.fetchCompletions ? [] : props.suggestions || []
      const hit = pool.find((item) => item.label.toLowerCase() === word.word.toLowerCase())
      if (!hit) return null
      return {
        range: new monacoRef.Range(position.lineNumber, word.startColumn, position.lineNumber, word.endColumn),
        contents: [{ value: `**${hit.label}**` }, { value: hit.detail || '-' }]
      }
    }
  })
}

onMounted(async () => {
  monacoRef = await loader.init()
  if (!containerRef.value) return
  editor = monacoRef.editor.create(containerRef.value, {
    value: props.modelValue || '',
    language: props.language,
    theme: 'vs-dark',
    automaticLayout: true,
    minimap: { enabled: false },
    fontSize: 13,
    lineNumbersMinChars: 3,
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    tabSize: 2
  })
  changeDisposable = editor.onDidChangeModelContent(() => {
    const value = editor.getValue()
    emit('update:modelValue', value)
    applyMarkers()
  })
  registerCompletion()
  applyMarkers()
  resizeObserver = new ResizeObserver(() => editor?.layout())
  resizeObserver.observe(containerRef.value)
})

watch(() => props.modelValue, (value) => {
  if (!editor) return
  if (editor.getValue() !== value) {
    editor.setValue(value || '')
  }
})

watch(() => props.suggestions, () => {
  registerCompletion()
}, { deep: true })

watch(() => props.fetchCompletions, () => {
  registerCompletion()
})

watch(() => props.extraSnippets, () => {
  registerCompletion()
}, { deep: true })

watch(() => props.language, (lang) => {
  if (!monacoRef || !editor) return
  const model = editor.getModel()
  if (model) {
    monacoRef.editor.setModelLanguage(model, lang)
  }
  registerCompletion()
  applyMarkers()
})

onBeforeUnmount(() => {
  if (changeDisposable) changeDisposable.dispose()
  if (providerDisposable) providerDisposable.dispose()
  if (hoverDisposable) hoverDisposable.dispose()
  if (resizeObserver) resizeObserver.disconnect()
  if (editor) editor.dispose()
})
</script>

<style scoped>
.monaco-wrapper {
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.monaco-container {
  height: 360px;
  width: 100%;
}
</style>
