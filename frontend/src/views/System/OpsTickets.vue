<template>
  <div class="ops-tickets-page">
    <div class="page-header">
      <h2 class="page-title">系统运维工单</h2>
      <p class="page-subtitle">由巡检报告发起的工单，供运维人工跟进与闭环。</p>
      <el-button type="primary" @click="load">刷新</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="items" v-loading="loading" style="width: 100%">
        <el-table-column prop="id" label="#" width="70" />
        <el-table-column prop="title" label="标题" min-width="200" />
        <el-table-column prop="inspection_report_id" label="巡检报告" width="130" />
        <el-table-column prop="severity" label="严重度" width="100">
          <template #default="{ row }">
            <el-tag :type="severityTag(row.severity)" size="small">{{ row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_by_username" label="创建人" width="120" />
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">处理</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="drawerVisible" title="工单处理" size="420px" destroy-on-close>
      <template v-if="active">
        <el-descriptions :column="1" border size="small" class="mb-16">
          <el-descriptions-item label="标题">{{ active.title }}</el-descriptions-item>
          <el-descriptions-item label="巡检">{{ active.inspection_report_id }}</el-descriptions-item>
        </el-descriptions>
        <div class="desc-block">
          <div class="label">描述</div>
          <pre class="desc-pre">{{ active.description || '-' }}</pre>
        </div>
        <el-form label-position="top" class="mt-16">
          <el-form-item label="状态">
            <el-select v-model="form.status" style="width: 100%">
              <el-option label="待处理 open" value="open" />
              <el-option label="处理中 in_progress" value="in_progress" />
              <el-option label="已解决 resolved" value="resolved" />
              <el-option label="已关闭 closed" value="closed" />
              <el-option label="已取消 cancelled" value="cancelled" />
            </el-select>
          </el-form-item>
          <el-form-item label="严重度">
            <el-select v-model="form.severity" style="width: 100%">
              <el-option label="低 low" value="low" />
              <el-option label="中 medium" value="medium" />
              <el-option label="高 high" value="high" />
              <el-option label="紧急 critical" value="critical" />
            </el-select>
          </el-form-item>
          <el-form-item label="处理说明 / 结论">
            <el-input v-model="form.resolution_notes" type="textarea" :rows="5" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" @click="save">保存</el-button>
          </el-form-item>
        </el-form>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { opsTicketsApi, type OpsTicketItem } from '@/api/ops_tickets'

const loading = ref(false)
const items = ref<OpsTicketItem[]>([])
const drawerVisible = ref(false)
const active = ref<OpsTicketItem | null>(null)
const saving = ref(false)

const form = reactive({
  status: 'open',
  severity: 'medium',
  resolution_notes: '',
})

function severityTag(s: string) {
  if (s === 'critical') return 'danger'
  if (s === 'high') return 'danger'
  if (s === 'medium') return 'warning'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    const res = await opsTicketsApi.list()
    items.value = res.items || []
  } finally {
    loading.value = false
  }
}

function openEdit(row: OpsTicketItem) {
  active.value = row
  form.status = row.status
  form.severity = row.severity
  form.resolution_notes = row.resolution_notes || ''
  drawerVisible.value = true
}

async function save() {
  if (!active.value) return
  saving.value = true
  try {
    await opsTicketsApi.patch(active.value.id, {
      status: form.status,
      severity: form.severity,
      resolution_notes: form.resolution_notes,
    })
    ElMessage.success('已保存')
    drawerVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.ops-tickets-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
  flex: 1 0 auto;
}
.page-subtitle {
  width: 100%;
  margin: 0;
  color: #64748b;
  font-size: 13px;
}
.desc-block {
  margin-top: 8px;
}
.desc-block .label {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 6px;
}
.desc-pre {
  margin: 0;
  padding: 12px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.mb-16 {
  margin-bottom: 16px;
}
.mt-16 {
  margin-top: 16px;
}
</style>
