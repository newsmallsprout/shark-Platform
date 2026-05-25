<template>
  <div class="tasks-container">
    <div class="page-header">
      <div class="header-info">
        <h2 class="page-title">Task Management</h2>
        <p class="page-subtitle">Monitor and control your data synchronization pipelines</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" size="large" @click="handleCreate" class="action-btn shadow-btn" v-if="canManage">
          <el-icon><Plus /></el-icon> New Pipeline Task
        </el-button>
      </div>
    </div>

    <!-- Dashboard Charts -->
    <div class="charts-row">
      <el-card shadow="never" class="chart-card full-width">
        <template #header>
          <div class="card-header">
            <span>Overall Task Performance</span>
          </div>
        </template>
        <div ref="eventsChartRef" class="chart-container"></div>
      </el-card>
    </div>

    <el-card shadow="never" class="table-card">
      <el-table :data="tasks" v-loading="loading" style="width: 100%" @expand-change="handleExpandChange">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expanded-chart-container">
              <div :id="'chart-' + row.task_id" class="task-mini-chart"></div>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="task_id" label="Task Identifier" min-width="180">
          <template #default="{ row }">
            <div class="task-id-cell">
              <el-icon class="task-icon"><DataLine /></el-icon>
              <span class="task-id">{{ row.task_id }}</span>
            </div>
          </template>
        </el-table-column>
        
        <el-table-column label="Status" width="140">
          <template #default="{ row }">
            <div class="status-wrapper">
              <span :class="['status-dot', row.status]"></span>
              <el-tag :type="getStatusType(row.status)" size="small" effect="light" class="status-tag">
                {{ row.status.toUpperCase() }}
              </el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="Sync Progress" min-width="240">
          <template #default="{ row }">
            <div v-if="row.metrics" class="progress-details">
              <div class="progress-stats">
                <span class="stat-item">
                  <span class="label">Processed:</span>
                  <span class="value">{{ row.metrics.processed_count?.toLocaleString() || 0 }}</span>
                </span>
                <span class="stat-item" v-if="row.metrics.phase">
                  <span class="label">Phase:</span>
                  <el-tag size="small" plain>{{ row.metrics.phase }}</el-tag>
                </span>
              </div>
              
              <div class="binlog-info" v-if="row.metrics.binlog_file">
                <el-icon><Monitor /></el-icon>
                <span>{{ row.metrics.binlog_file }} : {{ row.metrics.binlog_pos }}</span>
              </div>
              
              <div class="error-msg" v-if="row.metrics.error">
                <el-icon><Warning /></el-icon>
                <span>{{ row.metrics.error }}</span>
              </div>
            </div>
            <div v-else class="text-gray text-xs italic">No metrics available</div>
          </template>
        </el-table-column>

        <el-table-column label="Operations" width="320" fixed="right">
          <template #default="{ row }">
            <div class="action-group">
              <el-tooltip content="Start Task" v-if="(row.status === 'stopped' || row.status === 'error') && canManage">
                <el-button circle size="small" type="success" @click="handleStart(row.task_id)">
                  <el-icon><VideoPlay /></el-icon>
                </el-button>
              </el-tooltip>
              
              <el-tooltip content="Stop Task" v-if="row.status === 'running' && canManage">
                <el-button circle size="small" type="warning" @click="handleStop(row.task_id)">
                  <el-icon><VideoPause /></el-icon>
                </el-button>
              </el-tooltip>

              <el-tooltip content="View Logs">
                <el-button circle size="small" type="primary" plain @click="handleLogs(row.task_id)">
                  <el-icon><Document /></el-icon>
                </el-button>
              </el-tooltip>

              <el-tooltip content="Reset Task State" v-if="(row.status === 'stopped' || row.status === 'error') && canManage">
                <el-button circle size="small" type="danger" plain @click="handleReset(row.task_id)">
                  <el-icon><RefreshRight /></el-icon>
                </el-button>
              </el-tooltip>

              <el-tooltip content="Performance Config" v-if="canManage">
                <el-button circle size="small" type="info" plain @click="openPerfConfig(row)">
                  <el-icon><Setting /></el-icon>
                </el-button>
              </el-tooltip>

              <el-divider direction="vertical" v-if="canManage" />

              <el-button size="small" type="danger" text @click="handleDelete(row.task_id)" v-if="canManage">
                Delete
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="perfDialogVisible" title="Performance Config" width="760px">
      <div v-loading="perfLoading">
        <el-form label-width="220px">
          <el-form-item label="Task ID">
            <el-input :model-value="perfTaskId" disabled />
          </el-form-item>
          <el-form-item label="Current Status">
            <el-tag :type="getStatusType(perfTaskStatus)" effect="light">{{ (perfTaskStatus || '').toUpperCase() }}</el-tag>
          </el-form-item>
          <el-form-item label="Preset">
            <el-select v-model="perfPreset" style="width: 260px" @change="applyPerfPreset">
              <el-option label="Balanced (默认)" value="balanced" />
              <el-option label="High Throughput (追速)" value="fast" />
              <el-option label="Conservative (稳一点)" value="safe" />
            </el-select>
          </el-form-item>

          <el-divider content-position="left">Batching</el-divider>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="MySQL Fetch Batch">
                <el-input-number v-model="perfForm.mysql_fetch_batch" :min="100" :max="50000" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="Mongo Bulk Batch">
                <el-input-number v-model="perfForm.mongo_bulk_batch" :min="100" :max="50000" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="Prefetch Queue Size">
                <el-input-number v-model="perfForm.prefetch_queue_size" :min="1" :max="50" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="Progress Interval (sec)">
                <el-input-number v-model="perfForm.progress_interval" :min="1" :max="300" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-divider content-position="left">Incremental Flush</el-divider>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="Inc Flush Batch">
                <el-input-number v-model="perfForm.inc_flush_batch" :min="1000" :max="200000" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="Inc Flush Interval (sec)">
                <el-input-number v-model="perfForm.inc_flush_interval_sec" :min="1" :max="30" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="State Save Interval (sec)">
                <el-input-number v-model="perfForm.state_save_interval_sec" :min="1" :max="60" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-divider content-position="left">Rate Limit</el-divider>
          <el-form-item label="Enable Rate Limit">
            <el-switch v-model="perfForm.rate_limit_enabled" />
          </el-form-item>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="Max Load Avg Ratio">
                <el-input-number v-model="perfForm.max_load_avg_ratio" :min="0.5" :max="10" :step="0.1" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="Max Sleep (ms)">
                <el-input-number v-model="perfForm.max_sleep_ms" :min="0" :max="2000" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-divider content-position="left">Mongo Client</el-divider>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="Max Pool Size">
                <el-input-number v-model="perfForm.mongo_max_pool_size" :min="10" :max="500" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="Write Concern (w)">
                <el-input-number v-model="perfForm.mongo_write_w" :min="0" :max="5" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="Journal (j)">
            <el-switch v-model="perfForm.mongo_write_j" />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="perfDialogVisible = false">Cancel</el-button>
          <el-button type="primary" :disabled="perfTaskStatus === 'running'" :loading="perfSaving" @click="savePerfConfig">
            Save
          </el-button>
          <el-button type="warning" v-if="perfTaskStatus === 'running'" :loading="perfSaving" @click="stopSaveStart">
            Stop → Save → Start
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch, nextTick, computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import { storeToRefs } from 'pinia'
import { 
  Plus, VideoPlay, VideoPause, Document, 
  RefreshRight, DataLine, Monitor, Warning, Setting
} from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { useSystemStore } from '@/stores/system'
import { taskApi } from '@/api/task'
import { ElMessage } from 'element-plus'

const router = useRouter()
const taskStore = useTaskStore()
const systemStore = useSystemStore()
const { tasks, taskStats } = storeToRefs(taskStore)
const loading = ref(false)
const canManage = computed(() => systemStore.isAdmin || systemStore.hasPermission('manage_tasks'))
// const canView = computed(() => systemStore.isAdmin || systemStore.hasPermission('view_tasks'))

const eventsChartRef = ref<HTMLElement>()
let eventsChart: echarts.ECharts | null = null

// Store chart instances for each row
const rowCharts = new Map<string, any>()

let timer: any = null

onMounted(async () => {
  loading.value = true
  await taskStore.fetchTasks()
  loading.value = false
  
  initCharts()
  
  timer = setInterval(() => {
    taskStore.fetchTasks()
  }, 5000)
  
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('resize', handleResize)
  eventsChart?.dispose()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  for (const c of rowCharts.values()) {
    if (c && typeof c.dispose === 'function') {
      c.dispose()
    }
  }
})

const handleResize = () => {
  eventsChart?.resize()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  for (const c of rowCharts.values()) {
    if (c && typeof c.resize === 'function') {
      c.resize()
    }
  }
}

watch(tasks, () => {
  updateCharts()
  // Update all active row charts
  tasks.value.forEach(task => {
    if (rowCharts.has(task.task_id)) {
      updateRowChart(task.task_id)
    }
  })
}, { deep: true })

const initCharts = () => {
  if (eventsChartRef.value) {
    eventsChart = echarts.init(eventsChartRef.value)
  }
  nextTick(() => {
    if (eventsChart) {
      updateCharts()
    }
  })
}

const updateCharts = () => {
  if (!eventsChart) return

  // 1. Status Chart (Removed as requested)
  
  // 2. Events Chart (Overall) - Grouped Bar Chart by Task
  
  const taskNames = tasks.value.map(t => t.task_id)
  const insertData = tasks.value.map(t => (t.metrics?.inc_insert_count || 0) + (t.metrics?.full_insert_count || 0))
  const updateData = tasks.value.map(t => t.metrics?.update_count || 0)
  const deleteData = tasks.value.map(t => t.metrics?.delete_count || 0)

  eventsChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: '0%' },
    grid: { left: '3%', right: '4%', bottom: '10%', containLabel: true },
    xAxis: [
      {
        type: 'category',
        data: taskNames,
        axisTick: { alignWithLabel: true },
        axisLabel: { interval: 0, rotate: 30 }
      }
    ],
    yAxis: [{ type: 'value' }],
    series: [
      {
        name: 'Insert',
        type: 'bar',
        stack: 'total',
        emphasis: { focus: 'series' },
        data: insertData,
        itemStyle: { color: '#3b82f6' }
      },
      {
        name: 'Update',
        type: 'bar',
        stack: 'total',
        emphasis: { focus: 'series' },
        data: updateData,
        itemStyle: { color: '#f59e0b' }
      },
      {
        name: 'Delete',
        type: 'bar',
        stack: 'total',
        emphasis: { focus: 'series' },
        data: deleteData,
        itemStyle: { color: '#ef4444' }
      }
    ]
  })
}

const handleExpandChange = (row: any, expandedRows: any[]) => {
  const isExpanded = expandedRows.some(r => r.task_id === row.task_id)
  if (isExpanded) {
    nextTick(() => {
      initRowChart(row.task_id)
    })
  } else {
    const chart = rowCharts.get(row.task_id)
    chart?.dispose()
    rowCharts.delete(row.task_id)
  }
}

const initRowChart = (taskId: string) => {
  const el = document.getElementById(`chart-${taskId}`)
  if (!el) return
  
  const chart = echarts.init(el)
  rowCharts.set(taskId, chart)
  updateRowChart(taskId)
}

const updateRowChart = (taskId: string) => {
  const chart = rowCharts.get(taskId)
  if (!chart) return
  
  const task = tasks.value.find(t => t.task_id === taskId)
  if (!task || !task.metrics) return

  const m = task.metrics
  const insert = (m.inc_insert_count || 0) + (m.full_insert_count || 0)
  const update = m.update_count || 0
  const del = m.delete_count || 0

  chart.setOption({
    title: { 
      text: 'Event Distribution', 
      left: 'center',
      textStyle: { fontSize: 12, color: '#64748b' }
    },
    tooltip: { trigger: 'item' },
    series: [
      {
        name: 'Events',
        type: 'pie',
        radius: ['50%', '70%'],
        avoidLabelOverlap: false,
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 14, fontWeight: 'bold' }
        },
        data: [
          { value: insert, name: 'Insert', itemStyle: { color: '#3b82f6' } },
          { value: update, name: 'Update', itemStyle: { color: '#f59e0b' } },
          { value: del, name: 'Delete', itemStyle: { color: '#ef4444' } }
        ]
      }
    ]
  })
}

const getStatusType = (status: string) => {
  switch (status) {
    case 'running': return 'success'
    case 'stopped': return 'info'
    case 'error': return 'danger'
    default: return 'info'
  }
}

const handleCreate = () => {
  router.push('/tasks/create')
}

const handleStart = (id: string) => {
  taskStore.startTask(id)
}

const handleStop = (id: string) => {
  taskStore.stopTask(id)
}

const handleDelete = (id: string) => {
  ElMessageBox.confirm('Are you sure you want to delete this task? This action cannot be undone.', 'Delete Task', {
    confirmButtonText: 'Delete',
    cancelButtonText: 'Cancel',
    type: 'error',
    buttonSize: 'default'
  }).then(() => {
    taskStore.deleteTask(id)
  })
}

const handleReset = (id: string) => {
  ElMessageBox.confirm('Warning: This will clear the sync state (e.g., binlog position) and trigger a fresh full sync. Proceed?', 'Reset Task', {
    confirmButtonText: 'Reset & Sync',
    cancelButtonText: 'Cancel',
    type: 'warning',
  }).then(() => {
    taskStore.resetTask(id)
  })
}

const handleLogs = (id: string) => {
  router.push(`/tasks/logs/${id}`)
}

const perfDialogVisible = ref(false)
const perfLoading = ref(false)
const perfSaving = ref(false)
const perfTaskId = ref('')
const perfTaskStatus = ref('')
const perfPreset = ref<'balanced' | 'fast' | 'safe'>('balanced')

const perfForm = ref({
  progress_interval: 10,
  mysql_fetch_batch: 5000,
  mongo_bulk_batch: 5000,
  inc_flush_batch: 20000,
  inc_flush_interval_sec: 2,
  state_save_interval_sec: 2,
  prefetch_queue_size: 4,
  rate_limit_enabled: true,
  max_load_avg_ratio: 2.5,
  max_sleep_ms: 80,
  mongo_max_pool_size: 100,
  mongo_write_w: 1,
  mongo_write_j: false,
})

const applyPerfPreset = () => {
  if (perfPreset.value === 'safe') {
    perfForm.value = {
      ...perfForm.value,
      progress_interval: 10,
      mysql_fetch_batch: 2000,
      mongo_bulk_batch: 2000,
      prefetch_queue_size: 2,
      inc_flush_batch: 10000,
      inc_flush_interval_sec: 2,
      state_save_interval_sec: 2,
      rate_limit_enabled: true,
      max_load_avg_ratio: 1.5,
      max_sleep_ms: 200,
      mongo_max_pool_size: 50,
      mongo_write_w: 1,
      mongo_write_j: false,
    }
    return
  }
  if (perfPreset.value === 'fast') {
    perfForm.value = {
      ...perfForm.value,
      progress_interval: 10,
      mysql_fetch_batch: 10000,
      mongo_bulk_batch: 10000,
      prefetch_queue_size: 8,
      inc_flush_batch: 50000,
      inc_flush_interval_sec: 1,
      state_save_interval_sec: 2,
      rate_limit_enabled: false,
      max_load_avg_ratio: 3.0,
      max_sleep_ms: 20,
      mongo_max_pool_size: 200,
      mongo_write_w: 1,
      mongo_write_j: false,
    }
    return
  }
  perfForm.value = {
    ...perfForm.value,
    progress_interval: 10,
    mysql_fetch_batch: 5000,
    mongo_bulk_batch: 5000,
    prefetch_queue_size: 4,
    inc_flush_batch: 20000,
    inc_flush_interval_sec: 2,
    state_save_interval_sec: 2,
    rate_limit_enabled: true,
    max_load_avg_ratio: 2.5,
    max_sleep_ms: 80,
    mongo_max_pool_size: 100,
    mongo_write_w: 1,
    mongo_write_j: false,
  }
}

const openPerfConfig = async (row: any) => {
  perfTaskId.value = row.task_id
  perfTaskStatus.value = row.status
  perfPreset.value = 'balanced'
  applyPerfPreset()
  perfDialogVisible.value = true
  perfLoading.value = true
  try {
    const res = await taskApi.getTaskPerfConfig(row.task_id)
    const p = res.perf || {}
    perfForm.value = { ...perfForm.value, ...p }
  } catch (e: any) {
    ElMessage.error(String(e?.message || e || 'Failed to load config'))
  } finally {
    perfLoading.value = false
  }
}

const savePerfConfig = async () => {
  if (!perfTaskId.value) return
  perfSaving.value = true
  try {
    await taskApi.updateTaskPerfConfig(perfTaskId.value, perfForm.value)
    ElMessage.success('Updated')
    perfDialogVisible.value = false
    await taskStore.fetchTasks()
  } catch (e: any) {
    ElMessage.error(String(e?.response?.data?.detail || e?.message || e || 'Update failed'))
  } finally {
    perfSaving.value = false
  }
}

const stopSaveStart = async () => {
  if (!perfTaskId.value) return
  perfSaving.value = true
  try {
    await taskStore.stopTask(perfTaskId.value)
    await taskApi.updateTaskPerfConfig(perfTaskId.value, perfForm.value)
    await taskStore.startTask(perfTaskId.value)
    ElMessage.success('Applied and restarted')
    perfDialogVisible.value = false
  } catch (e: any) {
    ElMessage.error(String(e?.response?.data?.detail || e?.message || e || 'Operation failed'))
  } finally {
    perfSaving.value = false
  }
}
</script>

<style scoped>
.tasks-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 4px 0;
}

.page-subtitle {
  font-size: 14px;
  color: #64748b;
  margin: 0;
}

/* Charts Area */
.charts-row {
  display: block;
}

.chart-card.full-width {
  width: 100%;
}

.task-mini-chart {
  height: 200px;
  width: 100%;
}

.expanded-chart-container {
  padding: 10px 40px;
  background-color: #f8fafc;
}

.card-header {
  font-weight: 600;
  font-size: 14px;
  color: #475569;
}

.chart-container {
  height: 250px;
  width: 100%;
}

.table-card {
  border: 1px solid #f1f5f9 !important;
  border-radius: 12px !important;
}

.task-id-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.task-icon {
  font-size: 18px;
  color: #3b82f6;
}

.task-id {
  font-weight: 600;
  color: #334155;
}

.status-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-dot.running { background: #10b981; box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.1); }
.status-dot.stopped { background: #94a3b8; }
.status-dot.error { background: #ef4444; box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.1); }

.status-tag {
  border-radius: 6px;
  font-weight: 600;
  font-size: 10px;
}

.progress-details {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.progress-stats {
  display: flex;
  gap: 16px;
  align-items: center;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.stat-item .label {
  font-size: 12px;
  color: #94a3b8;
}

.stat-item .value {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}

.binlog-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #64748b;
  background: #f8fafc;
  padding: 4px 8px;
  border-radius: 4px;
  width: fit-content;
}

.error-msg {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #ef4444;
}

.action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.shadow-btn {
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}

.text-xs { font-size: 12px; }
.text-gray { color: #94a3b8; }
</style>
