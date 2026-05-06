<template>
  <div class="monitor-container">
    <div class="page-header">
      <div class="header-info">
        <h2 class="page-title">Log Monitor</h2>
        <p class="page-subtitle">K8s Log Monitoring & Local Logs</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" :icon="Plus" @click="createNewTask" v-if="canManage">New Task</el-button>
        <el-button @click="handleRefresh" :icon="Refresh" circle />
      </div>
    </div>

    <!-- Mode: K8s Monitor Tasks -->
    <el-card shadow="never" class="main-card">
      <div class="main-body">
        <!-- Task List (Left) -->
        <div class="task-list">
          <div class="list-header">
            <span>Monitor Tasks</span>
            <el-button type="primary" link :icon="Plus" @click="createNewTask" v-if="canManage" />
          </div>
          <div v-loading="loading" class="list-content">
            <div 
              v-for="task in tasks" 
              :key="task.id"
              class="task-item"
              :class="{ active: selectedTaskId === task.id }"
              @click="selectTask(task)"
            >
              <div class="task-icon">
                <el-icon v-if="task.enabled" color="#10b981"><VideoPlay /></el-icon>
                <el-icon v-else color="#94a3b8"><VideoPause /></el-icon>
              </div>
              <div class="task-info">
                <div class="task-name">{{ task.name }}</div>
                <div class="task-meta">{{ task.k8s_namespace }} • {{ task.alert_keywords?.length || 0 }} Keywords</div>
              </div>
              <div class="task-actions" v-if="selectedTaskId === task.id && canManage">
                 <el-button type="primary" link :icon="Setting" @click.stop="openConfig(task)" />
              </div>
            </div>
            <div v-if="tasks.length === 0" class="empty-list">
              No tasks found
            </div>
          </div>
        </div>

        <!-- Task Detail (Right) -->
        <div class="task-detail" v-if="selectedTask">
          <!-- Config Drawer/Dialog for Editing -->
          <el-dialog v-model="showConfigDialog" title="Task Configuration" width="600px">
              <el-form :model="form" label-position="top">
                  <el-row :gutter="20">
                    <el-col :span="12">
                      <el-form-item label="Task Name">
                        <el-input v-model="form.name" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="K8s Namespace">
                        <el-input v-model="form.k8s_namespace" placeholder="default" />
                      </el-form-item>
                    </el-col>
                  </el-row>

                  <el-form-item label="Kubeconfig (YAML)">
                    <el-input
                      v-model="form.k8s_kubeconfig"
                      type="textarea"
                      :rows="4"
                      :placeholder="form.k8s_kubeconfig_set ? '凭据已保存：留空表示不修改；更换请粘贴完整 kubeconfig' : '留空则使用集群内 ServiceAccount（in-cluster）'"
                    />
                  </el-form-item>

                  <el-divider>Alert Rules</el-divider>

                  <el-form-item label="Global Settings">
                     <el-switch v-model="form.alert_enabled" active-text="Enable Alert Sending" style="margin-right: 20px" />
                     <el-input v-model="form.slack_webhook_url" placeholder="Slack Webhook URL" style="width: 300px" />
                  </el-form-item>

                  <el-tabs type="border-card" class="alert-tabs">
                    <el-tab-pane label="Threshold Alert">
                      <div class="tab-tip">Alert when error count exceeds threshold in time window</div>
                      <el-row :gutter="20">
                        <el-col :span="8">
                          <el-form-item label="Threshold Count">
                            <el-input-number v-model="form.alert_threshold_count" :min="1" />
                          </el-form-item>
                        </el-col>
                        <el-col :span="8">
                          <el-form-item label="Time Window (sec)">
                            <el-input-number v-model="form.alert_threshold_window" :min="10" />
                          </el-form-item>
                        </el-col>
                        <el-col :span="8">
                          <el-form-item label="Silence (min)">
                             <el-tooltip content="Silence duplicate alerts for N minutes" placement="top">
                                <el-input-number v-model="form.alert_silence_minutes" :min="0" />
                             </el-tooltip>
                          </el-form-item>
                        </el-col>
                      </el-row>
                      <el-form-item label="Keywords (One per line)">
                        <el-input v-model="keywordsStr" type="textarea" :rows="4" placeholder="ERROR&#10;Exception" />
                      </el-form-item>
                    </el-tab-pane>

                    <el-tab-pane label="Immediate Alert">
                      <div class="tab-tip">Alert immediately on first occurrence</div>
                      <el-form-item label="Keywords (One per line)">
                        <el-input v-model="immediateStr" type="textarea" :rows="6" placeholder="Critical&#10;Fatal" />
                      </el-form-item>
                    </el-tab-pane>

                    <el-tab-pane label="Ignore">
                      <div class="tab-tip">Completely ignore logs containing these keywords</div>
                      <el-form-item label="Keywords (One per line)">
                        <el-input v-model="ignoreStr" type="textarea" :rows="6" placeholder="HealthCheck&#10;Debug" />
                      </el-form-item>
                    </el-tab-pane>

                    <el-tab-pane label="Record Only">
                      <div class="tab-tip">Record to file but DO NOT send alert</div>
                      <el-form-item label="Keywords (One per line)">
                        <el-input v-model="recordStr" type="textarea" :rows="6" placeholder="Warning&#10;Deprecated" />
                      </el-form-item>
                    </el-tab-pane>
                  </el-tabs>

                  <el-divider>Archiving & Retention</el-divider>

                  <el-row :gutter="20">
                    <el-col :span="6">
                      <el-form-item label="Retention Days">
                         <el-input-number v-model="form.retention_days" :min="1" :max="365" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="6">
                      <el-form-item label="Enable S3 Archive">
                         <el-switch v-model="form.s3_archive_enabled" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="S3 Bucket">
                        <el-input v-model="form.s3_bucket" :disabled="!form.s3_archive_enabled" />
                      </el-form-item>
                    </el-col>
                  </el-row>

                  <el-row :gutter="20">
                    <el-col :span="8">
                      <el-form-item label="S3 Region">
                        <el-input v-model="form.s3_region" :disabled="!form.s3_archive_enabled" placeholder="us-east-1" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="16">
                      <el-form-item label="S3 Endpoint (Optional)">
                        <el-input v-model="form.s3_endpoint" :disabled="!form.s3_archive_enabled" placeholder="https://s3.amazonaws.com 或 MinIO/OSS endpoint" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <el-row :gutter="20">
                    <el-col :span="12">
                      <el-form-item label="S3 Access Key">
                        <el-input v-model="form.s3_access_key" :disabled="!form.s3_archive_enabled" placeholder="AKIA... / 留空不修改" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="S3 Secret Key">
                        <el-input v-model="form.s3_secret_key" :disabled="!form.s3_archive_enabled" type="password" show-password placeholder="****（编辑时留空表示不修改）" />
                      </el-form-item>
                    </el-col>
                  </el-row>
              </el-form>
              <template #footer>
                <div class="dialog-footer">
                  <el-button type="danger" plain @click="deleteTask" v-if="form.id">Delete</el-button>
                  <el-button @click="showConfigDialog = false">Cancel</el-button>
                  <el-button type="primary" @click="saveTask">Save</el-button>
                </div>
              </template>
          </el-dialog>

          <el-dialog v-model="historyVisible" title="历史索引" width="980px" top="5vh">
            <div class="history-body">
              <div class="history-filters">
                <el-form label-width="120px">
                  <el-row :gutter="16">
                    <el-col :span="12">
                      <el-form-item label="时间范围">
                        <el-date-picker
                          v-model="historyRange"
                          type="datetimerange"
                          range-separator="至"
                          start-placeholder="开始时间"
                          end-placeholder="结束时间"
                          value-format="YYYY-MM-DDTHH:mm:ss"
                          style="width: 100%"
                        />
                      </el-form-item>
                    </el-col>
                    <el-col :span="6">
                      <el-form-item label="状态">
                        <el-select v-model="historyLogType" style="width: 100%">
                          <el-option label="正常" value="raw" />
                          <el-option label="错误" value="error" />
                        </el-select>
                      </el-form-item>
                    </el-col>
                    <el-col :span="6">
                      <el-form-item label="文件名关键字">
                        <el-input v-model="historyKeyword" placeholder="可选" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                </el-form>
                <div class="history-actions">
                  <el-button type="primary" :loading="historyLoading" @click="searchHistory">搜索</el-button>
                </div>
              </div>

              <div class="history-results" v-loading="historyLoading">
                <el-row :gutter="16">
                  <el-col :span="10">
                    <el-card shadow="never">
                      <template #header>
                        <span>索引列表</span>
                      </template>
                      <div v-if="historyItems.length === 0" class="empty-viewer">
                        <el-empty description="点击「搜索」后展示历史索引" />
                      </div>
                      <el-table v-else :data="historyItems" size="small" style="width: 100%" @row-click="selectHistoryIndex">
                        <el-table-column prop="window_start" label="窗口开始" min-width="180">
                          <template #default="{ row }">{{ formatIso(row.window_start) }}</template>
                        </el-table-column>
                        <el-table-column prop="window_end" label="窗口结束" min-width="180">
                          <template #default="{ row }">{{ formatIso(row.window_end) }}</template>
                        </el-table-column>
                        <el-table-column prop="size" label="Size" width="90">
                          <template #default="{ row }">{{ formatBytes(row.size) }}</template>
                        </el-table-column>
                      </el-table>
                    </el-card>
                  </el-col>
                  <el-col :span="14">
                    <el-card shadow="never">
                      <template #header>
                        <span>索引详情</span>
                      </template>
                      <div v-if="historyDetailFiles.length === 0" class="empty-viewer">
                        <el-empty description="点击左侧某条索引查看详情" />
                      </div>
                      <el-table v-else :data="historyDetailFiles" size="small" style="width: 100%">
                        <el-table-column prop="name" label="File" min-width="360" />
                        <el-table-column prop="size" label="Size" width="90">
                          <template #default="{ row }">{{ formatBytes(row.size) }}</template>
                        </el-table-column>
                        <el-table-column prop="mtime" label="Time" width="180">
                          <template #default="{ row }">{{ formatEpoch(row.mtime) }}</template>
                        </el-table-column>
                        <el-table-column label="操作" width="90" fixed="right">
                          <template #default="{ row }">
                            <el-button link type="primary" @click.stop="openFileFromHistory(row.name)">查看</el-button>
                          </template>
                        </el-table-column>
                      </el-table>
                    </el-card>
                  </el-col>
                </el-row>
              </div>
            </div>
          </el-dialog>

          <!-- Main Log Explorer for Task -->
          <div class="saved-container">
                <!-- File List -->
                <div class="saved-file-list">
                  <div class="list-header">
                    <el-input 
                      v-model="fileSearchQuery" 
                      placeholder="Filter files..." 
                      size="small"
                      :prefix-icon="Search"
                      clearable
                      style="width: 100%"
                    />
                  </div>
                  <div class="list-toolbar">
                    <span class="file-count">{{ savedFileTotal }} Files</span>
                    <div class="toolbar-actions">
                      <el-radio-group
                        v-if="selectedTask?.s3_archive_enabled"
                        v-model="savedLogType"
                        size="small"
                        class="log-type-toggle"
                        @change="handleSavedLogTypeChange"
                      >
                        <el-radio-button label="raw">正常</el-radio-button>
                        <el-radio-button label="error">错误</el-radio-button>
                      </el-radio-group>
                      <el-button v-if="selectedTask?.s3_archive_enabled" size="small" class="history-btn" @click="openHistory">历史</el-button>
                      <el-tooltip content="Task Config" placement="top" v-if="canManage">
                        <el-button link :icon="Setting" @click="selectedTask && openConfig(selectedTask)" />
                      </el-tooltip>
                      <el-dropdown trigger="click" @command="handleSortCommand">
                        <span class="el-dropdown-link" style="cursor: pointer; display: flex; align-items: center; color: #64748b; font-size: 12px; margin-right: 4px">
                          <el-icon><Sort /></el-icon>
                        </span>
                        <template #dropdown>
                          <el-dropdown-menu>
                            <el-dropdown-item command="mtime:desc">Date (Newest)</el-dropdown-item>
                            <el-dropdown-item command="mtime:asc">Date (Oldest)</el-dropdown-item>
                            <el-dropdown-item command="name:asc">Name (A-Z)</el-dropdown-item>
                            <el-dropdown-item command="size:desc">Size (Large)</el-dropdown-item>
                          </el-dropdown-menu>
                        </template>
                      </el-dropdown>
                      <el-select v-model="savedFilePageSize" size="small" style="width: 70px" @change="fetchSavedLogs(1)">
                        <el-option :value="10" label="10" />
                        <el-option :value="20" label="20" />
                        <el-option :value="50" label="50" />
                      </el-select>
                    </div>
                  </div>
                  <div v-loading="savedLoading" class="list-content">
                    <div 
                      v-for="file in filteredSavedLogFiles" 
                      :key="file.name"
                      class="file-item"
                      :class="{ active: savedLogFile === file.name }"
                      @click="selectSavedFile(file.name)"
                    >
                      <div class="file-checkbox" @click.stop>
                        <el-checkbox 
                          :model-value="selectedFiles.includes(file.name)"
                          @change="toggleFileSelection(file.name)"
                        />
                      </div>
                      <div class="file-icon"><el-icon><Document /></el-icon></div>
                      <div class="file-info">
                        <div class="file-name" :title="file.name">{{ file.name }}</div>
                        <div class="file-meta">{{ (file.size / 1024 / 1024).toFixed(2) }} MB • {{ new Date(file.mtime * 1000).toLocaleString() }}</div>
                      </div>
                    </div>
                    <div v-if="savedLogFiles.length === 0" class="empty-list">No logs found</div>
                  </div>
                  <div class="list-pagination">
                     <el-pagination 
                       small 
                       layout="prev, next" 
                       :total="savedFileTotal" 
                       :page-size="savedFilePageSize"
                       v-model:current-page="savedFilePage"
                       @current-change="fetchSavedLogs"
                     />
                  </div>
                </div>

                <!-- Log Viewer / Search Results -->
                <div class="saved-log-viewer" v-loading="savedContentLoading">
                  <div class="viewer-header">
                    <div class="header-left">
                      <span v-if="isBatchSearch">Batch Search Results ({{ batchSearchResults.length }})</span>
                      <span v-else-if="savedLogFile">{{ savedLogFile.length > 50 ? '...' + savedLogFile.slice(-47) : savedLogFile }}</span>
                      <span v-else>No File Selected</span>
                    </div>
                    <div class="header-right" v-if="savedLogFile && !isBatchSearch">
                       <el-select v-model="savedLogPageSize" size="small" style="width: 100px; margin-right: 8px" @change="fetchSavedLogContent(1)">
                        <el-option :value="500" label="500 lines" />
                        <el-option :value="1000" label="1k lines" />
                        <el-option :value="5000" label="5k lines" />
                      </el-select>
                      <el-pagination 
                         small
                         layout="prev, pager, next"
                         :total="savedLogTotal"
                         :page-size="savedLogPageSize"
                         v-model:current-page="savedLogPage"
                         @current-change="fetchSavedLogContent"
                         style="display: inline-flex; margin-right: 12px"
                      />
                      <el-button size="small" :icon="Download" circle @click="downloadSavedFile" title="Download" />
                      <el-button size="small" :icon="Refresh" circle @click="fetchSavedLogContent(savedLogPage)" />
                    </div>
                    <div class="header-right" v-if="savedLogFile || selectedFiles.length > 0">
                       <el-input 
                          v-model="savedSearchQuery" 
                          :placeholder="selectedFiles.length > 0 ? 'Search in selected files...' : 'Search in current file...'" 
                          size="small" 
                          style="width: 250px"
                          @keyup.enter="handleSavedSearch"
                       >
                          <template #append><el-button :icon="Search" @click="handleSavedSearch"/></template>
                       </el-input>
                    </div>
                  </div>

                  <div class="search-results-panel" v-if="isBatchSearch">
                    <div v-if="batchSearchResults.length === 0" class="empty-viewer">
                      <el-empty description="No matches found" />
                    </div>
                    <div v-else>
                      <div v-for="(group, file) in _.groupBy(batchSearchResults, 'file')" :key="file" class="search-result-group">
                        <div class="group-header">
                          <span>{{ file }}</span>
                          <el-button link size="small" @click="jumpToBatchResult(String(file))">View File</el-button>
                        </div>
                        <div class="group-matches">
                          <div v-for="(match, idx) in group" :key="idx" class="match-item" @click="jumpToBatchResult(String(file))">
                            <span class="match-line-num">{{ match.line + 1 }}</span>
                            <span class="match-content">{{ match.content }}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div class="log-lines" v-else-if="savedLogFile">
                    <pre class="log-raw">{{ savedLogContent }}</pre>
                  </div>
                  <div v-else class="empty-viewer">
                    <el-empty description="Select a log file to view" />
                  </div>
                </div>
              </div>
        </div>

        <div class="empty-detail" v-else>
          <el-empty description="Select a task to view logs" />
        </div>
      </div>
    </el-card>

  </div>
</template>

<script setup lang="ts">
import _ from 'lodash'
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { monitorApi, type MonitorTask } from '@/api/monitor'
import { taskApi } from '@/api/task'
import { Refresh, Plus, VideoPlay, VideoPause, Document, Search, Download, Setting, Sort } from '@element-plus/icons-vue'
import { useSystemStore } from '@/stores/system'

const route = useRoute()
const systemStore = useSystemStore()
const canManage = computed(() => systemStore.isAdmin || systemStore.hasPermission('manage_log_monitor'))

const loading = ref(false)
const viewMode = ref('k8s') // 'k8s' | 'local'

// --- K8s Mode State ---
const tasks = ref<MonitorTask[]>([])
const selectedTaskId = ref<number | null>(null)
const selectedTask = ref<MonitorTask | null>(null)
const showConfigDialog = ref(false)
const historyVisible = ref(false)
const historyLoading = ref(false)
const historyRange = ref<[string, string] | null>(null)
const historyKeyword = ref('')
const historyLogType = ref<'raw' | 'error'>('raw')
const historyItems = ref<any[]>([])
const historyDetailFiles = ref<any[]>([])
const historySelectedKey = ref<string>('')
const form = ref<Partial<MonitorTask>>({})
const k8sPods = ref<any[]>([])
const selectedPod = ref('')
const k8sLogContent = ref('')
const logLoading = ref(false)

// --- Saved Logs State ---
const savedLoading = ref(false)
const savedContentLoading = ref(false)
const savedLogFiles = ref<any[]>([])
const fileSearchQuery = ref('')
const savedLogType = ref<'raw' | 'error'>('raw')

const isErrorLogName = (name: string) => {
  const n = (name || '').toLowerCase()
  if (n.includes('/error/')) return true
  if (n.endsWith('_error.log')) return true
  if (n.includes('task_errors_')) return true
  return false
}

const filteredSavedLogFiles = computed(() => {
  const base = savedLogFiles.value.filter(f => {
    const isErr = isErrorLogName(f.name)
    return savedLogType.value === 'error' ? isErr : !isErr
  })
  if (!fileSearchQuery.value) return base
  const q = fileSearchQuery.value.toLowerCase()
  return base.filter(f => f.name.toLowerCase().includes(q))
})

const savedLogFile = ref('')
const savedLogContent = ref('')
const savedFilePage = ref(1)
const savedFilePageSize = ref(10)
const savedFileTotal = ref(0)
const savedLogPage = ref(1)
const savedLogPageSize = ref(500) // Default to 500 lines as requested
const savedLogTotal = ref(0)
const savedSearchQuery = ref('')
const selectedFiles = ref<string[]>([])
const batchSearchResults = ref<any[]>([])
const isBatchSearch = ref(false)

const keywordsStr = computed({
  get: () => form.value.alert_keywords?.join('\n') || '',
  set: (val) => {
    form.value.alert_keywords = val.split('\n').filter(k => k.trim())
  }
})

const immediateStr = computed({
  get: () => form.value.immediate_keywords?.join('\n') || '',
  set: (val) => {
    form.value.immediate_keywords = val.split('\n').filter(k => k.trim())
  }
})

const ignoreStr = computed({
  get: () => form.value.ignore_keywords?.join('\n') || '',
  set: (val) => {
    form.value.ignore_keywords = val.split('\n').filter(k => k.trim())
  }
})

const recordStr = computed({
  get: () => form.value.record_only_keywords?.join('\n') || '',
  set: (val) => {
    form.value.record_only_keywords = val.split('\n').filter(k => k.trim())
  }
})

// --- Local Mode State ---
const logFiles = ref<any[]>([])
const selectedFile = ref('')
const logContent = ref<string[]>([])
const filePage = ref(1)
const filePageSize = ref(10)
const fileTotal = ref(0)
const logPage = ref(1)
const logPageSize = ref(1000)
const logTotal = ref(0)
const contentLoading = ref(false)
const globalSearchQuery = ref('')
const searchResults = ref<any[]>([])

// --- Actions ---

const handleRefresh = () => {
  if (viewMode.value === 'k8s') fetchTasks()
  else fetchLocalFiles(1)
}

// Monitor Tasks
const fetchTasks = async () => {
  loading.value = true
  try {
    tasks.value = await monitorApi.getTasks()
  } finally {
    loading.value = false
  }
}

const selectTask = (task: MonitorTask) => {
  selectedTaskId.value = task.id!
  selectedTask.value = { ...task }
  form.value = { ...task }
  if (task.k8s_kubeconfig_set) {
    form.value.k8s_kubeconfig = ''
  }
  fetchSavedLogs(1)
  // if (task.k8s_namespace) fetchPods() // Removed
}

const openConfig = (task: MonitorTask) => {
    form.value = { ...task }
    if (form.value.s3_secret_key === undefined || form.value.s3_secret_key === null) {
      form.value.s3_secret_key = ''
    }
    if (task.k8s_kubeconfig_set) {
      form.value.k8s_kubeconfig = ''
    }
    showConfigDialog.value = true
}

const createNewTask = () => {
  selectedTaskId.value = null
  selectedTask.value = { 
    name: 'New Monitor Task', 
    enabled: true,
    k8s_namespace: 'default',
    k8s_kubeconfig: '',
    alert_keywords: ['ERROR'],
    immediate_keywords: [],
    ignore_keywords: [],
    record_only_keywords: [],
    alert_threshold_count: 5,
    alert_threshold_window: 60,
    alert_silence_minutes: 60,
    s3_archive_enabled: false,
    s3_bucket: '',
    s3_region: 'us-east-1',
    s3_access_key: '',
    s3_secret_key: '',
    s3_endpoint: '',
    retention_days: 7,
    alert_enabled: true
  } as any
  form.value = { ...selectedTask.value }
  showConfigDialog.value = true
}

const saveTask = async () => {
  try {
    if (form.value.id) {
      await monitorApi.updateTask(form.value.id, form.value)
      ElMessage.success('Task updated')
    } else {
      await monitorApi.createTask(form.value)
      ElMessage.success('Task created')
    }
    showConfigDialog.value = false
    fetchTasks()
  } catch (e) {
    ElMessage.error('Failed to save task')
  }
}

const deleteTask = async () => {
  if (!selectedTaskId.value) return
  try {
    await ElMessageBox.confirm('Are you sure you want to delete this task?', 'Warning', { type: 'warning' })
    await monitorApi.deleteTask(selectedTaskId.value)
    ElMessage.success('Task deleted')
    selectedTaskId.value = null
    selectedTask.value = null
    fetchTasks()
  } catch (e) {}
}

const fetchPods = async () => {
  const ns = form.value.k8s_namespace || 'default'
  try {
    const res = await taskApi.getK8sPods(ns)
    k8sPods.value = res.pods || []
  } catch (e) { console.error(e) }
}

const fetchK8sLogs = async () => {
  if (!selectedPod.value) return
  logLoading.value = true
  try {
    const logs = await taskApi.getK8sLogs({
      namespace: form.value.k8s_namespace || 'default',
      pod_name: selectedPod.value,
      tail_lines: 100
    })
    k8sLogContent.value = logs
  } catch (e) {
    k8sLogContent.value = `Error: ${e}`
  } finally {
    logLoading.value = false
  }
}

// Saved Logs Actions
const savedFileSortBy = ref('mtime')
const savedFileOrder = ref('desc')

const fetchSavedLogs = async (page = 1) => {
  if (!selectedTaskId.value) return
  savedFilePage.value = page
  savedLoading.value = true
  try {
    if (!selectedTask.value?.s3_archive_enabled && savedLogType.value !== 'error') {
      savedLogType.value = 'error'
    }
    const res = await monitorApi.getLogs(selectedTaskId.value, { 
        page, 
        page_size: savedFilePageSize.value,
        sort_by: savedFileSortBy.value,
        order: savedFileOrder.value,
        log_type: savedLogType.value,
        realtime: selectedTask.value?.s3_archive_enabled ? 1 : 0
    })
    savedLogFiles.value = res.files
    savedFileTotal.value = res.total
  } catch (e) {
    savedLogFiles.value = []
    savedFileTotal.value = 0
  } finally {
    savedLoading.value = false
  }
}

const handleSortCommand = (command: string) => {
    // command: "mtime:desc"
    const [field, order] = command.split(':')
    savedFileSortBy.value = field
    savedFileOrder.value = order
    fetchSavedLogs(1)
}

const handleSavedLogTypeChange = () => {
  selectedFiles.value = []
  isBatchSearch.value = false
  if (savedLogFile.value && !filteredSavedLogFiles.value.some(f => f.name === savedLogFile.value)) {
    savedLogFile.value = ''
    savedLogContent.value = ''
    savedLogTotal.value = 0
    savedLogPage.value = 1
  }
  if (selectedTaskId.value) {
    fetchSavedLogs(1)
  }
}

const formatIso = (s: string) => {
  if (!s) return '-'
  try {
    const d = new Date(s)
    return isNaN(d.getTime()) ? s : d.toLocaleString()
  } catch (e) {
    return s
  }
}

const formatEpoch = (sec: number) => {
  if (!sec) return '-'
  try {
    const d = new Date(Number(sec) * 1000)
    return isNaN(d.getTime()) ? String(sec) : d.toLocaleString()
  } catch (e) {
    return String(sec)
  }
}

const formatBytes = (n: number) => {
  const v = Number(n || 0)
  if (v <= 0) return '0 B'
  if (v < 1024) return `${v} B`
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(2)} KB`
  if (v < 1024 * 1024 * 1024) return `${(v / 1024 / 1024).toFixed(2)} MB`
  return `${(v / 1024 / 1024 / 1024).toFixed(2)} GB`
}

const openHistory = () => {
  historyVisible.value = true
  historyItems.value = []
  historyDetailFiles.value = []
  historySelectedKey.value = ''
  historyLogType.value = savedLogType.value
}

const searchHistory = async () => {
  if (!selectedTaskId.value) return
  if (!historyRange.value || historyRange.value.length !== 2) {
    ElMessage.warning('请选择时间范围')
    return
  }
  historyLoading.value = true
  historyItems.value = []
  historyDetailFiles.value = []
  historySelectedKey.value = ''
  try {
    const res = await monitorApi.getIndexHistory(selectedTaskId.value, {
      log_type: historyLogType.value,
      start: historyRange.value[0],
      end: historyRange.value[1],
      keyword: historyKeyword.value || ''
    })
    historyItems.value = res.items || []
  } catch (e) {
    ElMessage.error(`历史查询失败: ${e}`)
  } finally {
    historyLoading.value = false
  }
}

const selectHistoryIndex = async (row: any) => {
  if (!selectedTaskId.value) return
  if (!row?.key) return
  historySelectedKey.value = row.key
  historyLoading.value = true
  try {
    const detail = await monitorApi.getIndexDetail(selectedTaskId.value, row.key)
    historyDetailFiles.value = detail?.files || []
  } catch (e) {
    historyDetailFiles.value = []
    ElMessage.error(`加载索引详情失败: ${e}`)
  } finally {
    historyLoading.value = false
  }
}

const openFileFromHistory = (key: string) => {
  if (!key) return
  historyVisible.value = false
  selectSavedFile(key)
}

const selectSavedFile = (name: string) => {
  savedLogFile.value = name
  savedLogContent.value = ''
  isBatchSearch.value = false
  // Reset pagination to first page (latest logs)
  savedLogPage.value = 1
  fetchSavedLogContent(1)
}

const fetchSavedLogContent = async (page = 1) => {
  if (!selectedTaskId.value || !savedLogFile.value) return
  savedLogPage.value = page
  savedContentLoading.value = true
  try {
    const res = await monitorApi.viewLog(selectedTaskId.value, savedLogFile.value, { 
      page, 
      page_size: savedLogPageSize.value,
      reverse: true // Always default to reverse (latest first)
    })
    savedLogContent.value = res.content
    savedLogTotal.value = res.total
  } catch (e) {
    savedLogContent.value = `Error loading file: ${e}`
  } finally {
    savedContentLoading.value = false
  }
}

const downloadSavedFile = () => {
  if (!selectedTaskId.value || !savedLogFile.value) return
  window.open(monitorApi.downloadLog(selectedTaskId.value, savedLogFile.value), '_blank')
}

const handleSavedSearch = async () => {
  if (!selectedTaskId.value || !savedSearchQuery.value) return
  
  savedContentLoading.value = true
  batchSearchResults.value = []
  
  try {
    // If files selected, perform batch search
    if (selectedFiles.value.length > 0) {
      isBatchSearch.value = true
      const res = await monitorApi.batchViewLogs(selectedTaskId.value, selectedFiles.value, savedSearchQuery.value)
      batchSearchResults.value = res.results
    } else if (savedLogFile.value) {
      // Single file search
      isBatchSearch.value = false
      const res = await monitorApi.viewLog(selectedTaskId.value, savedLogFile.value, { keyword: savedSearchQuery.value })
      savedLogContent.value = res.content
    }
  } catch (e) {
    if (!isBatchSearch.value) {
       savedLogContent.value = `Search failed: ${e}`
    } else {
       ElMessage.error(`Batch search failed: ${e}`)
    }
  } finally {
    savedContentLoading.value = false
  }
}

const toggleFileSelection = (filename: string) => {
  const idx = selectedFiles.value.indexOf(filename)
  if (idx > -1) {
    selectedFiles.value.splice(idx, 1)
  } else {
    selectedFiles.value.push(filename)
  }
}

const jumpToBatchResult = (filename: string) => {
  // Switch to single file view
  isBatchSearch.value = false
  selectSavedFile(filename)
  // Optional: Highlight logic could be added here
}

// watch(activeTab, (tab) => {
//   if (tab === 'saved' && selectedTaskId.value) {
//     fetchSavedLogs(1)
//   }
// })

// Local Logs
const fetchLocalFiles = async (page = 1) => {
  filePage.value = page
  loading.value = true
  try {
    const res = await taskApi.getLogFiles({ page, page_size: filePageSize.value })
    logFiles.value = res.files
    fileTotal.value = res.total
  } finally {
    loading.value = false
  }
}

const selectFile = (name: string) => {
  selectedFile.value = name
  searchResults.value = []
  fetchLogContent(1)
}

const fetchLogContent = async (page = 1) => {
  if (!selectedFile.value) return
  logPage.value = page
  contentLoading.value = true
  try {
    const taskId = selectedFile.value.replace('.log', '')
    const res = await taskApi.getTaskLogs(taskId, { page, page_size: logPageSize.value })
    logContent.value = res.lines
    logTotal.value = res.total // Ensure backend returns total lines
  } finally {
    contentLoading.value = false
  }
}

const downloadFile = () => {
  if (!selectedFile.value) return
  window.open(taskApi.downloadLog(selectedFile.value), '_blank')
}

const handleGlobalSearch = async () => {
  if (!globalSearchQuery.value) return
  contentLoading.value = true
  selectedFile.value = ''
  try {
    const res = await taskApi.searchLogs(globalSearchQuery.value)
    searchResults.value = res
  } finally {
    contentLoading.value = false
  }
}

const jumpToLog = (filename: string) => {
  selectFile(filename)
}

watch(viewMode, (val) => {
  if (val === 'k8s') fetchTasks()
  else fetchLocalFiles(1)
})

onMounted(async () => {
  await fetchTasks()
  
  // Auto-open from query params
  const tId = route.query.taskId
  const fName = route.query.filename
  
  if (tId) {
    const task = tasks.value.find(t => t.id === Number(tId))
    if (task) {
      selectedTaskId.value = task.id!
      selectedTask.value = { ...task }
      form.value = { ...task }
      if (!selectedTask.value.s3_archive_enabled) {
        savedLogType.value = 'error'
      }
      
      await fetchSavedLogs(1)
      
      if (fName) {
        savedLogType.value = isErrorLogName(String(fName)) ? 'error' : 'raw'
        selectSavedFile(String(fName))
      }
    }
  }
})
</script>

<style scoped>
.monitor-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: calc(100vh - 100px);
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
  margin: 0;
}

.page-subtitle {
  font-size: 14px;
  color: #64748b;
  margin: 0;
}

.main-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.main-card :deep(.el-card__body) {
  flex: 1;
  padding: 0;
  display: flex;
  overflow: hidden;
}

.main-body {
  display: flex;
  width: 100%;
  height: 100%;
}

/* Task List / File List */
.task-list, .file-list {
  width: 280px;
  border-right: 1px solid var(--app-border-color);
  display: flex;
  flex-direction: column;
  background: transparent; /* Was #f8fafc */
}

.list-header {
  padding: 8px 16px;
  border-bottom: 1px solid var(--app-border-color);
  display: flex;
  align-items: center;
  height: 50px;
}

.list-toolbar {
  padding: 8px 16px;
  background: transparent; /* Was #fff */
  border-bottom: 1px solid var(--app-border-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--app-text-muted);
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.log-type-toggle {
  display: inline-flex;
  align-items: center;
}

.toolbar-actions :deep(.el-radio-button__inner) {
  height: 24px;
  line-height: 22px;
  padding: 0 10px;
  border-color: var(--app-border-color);
  background: rgba(148, 163, 184, 0.08);
  color: var(--app-text-muted);
}

.toolbar-actions :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-top-left-radius: 6px;
  border-bottom-left-radius: 6px;
}

.toolbar-actions :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-top-right-radius: 6px;
  border-bottom-right-radius: 6px;
}

.toolbar-actions :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: rgba(var(--el-color-primary-rgb), 0.12);
  border-color: rgba(var(--el-color-primary-rgb), 0.45);
  color: var(--el-color-primary);
  box-shadow: none;
}

.toolbar-actions :deep(.el-radio-button__inner:hover) {
  color: var(--app-text-main);
}

.toolbar-actions :deep(.el-button--small) {
  height: 24px;
}

.list-content {
  flex: 1;
  overflow-y: auto;
}

.list-pagination {
  padding: 8px;
  border-top: 1px solid var(--app-border-color);
  display: flex;
  justify-content: center;
}

.task-item, .file-item {
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  gap: 12px;
  border-bottom: 1px solid var(--app-border-color);
  transition: all 0.2s;
  align-items: center;
}

.task-item:hover, .file-item:hover { background: rgba(0,0,0,0.05); }
.task-item.active, .file-item.active { background: rgba(var(--el-color-primary-rgb), 0.1); border-left: 3px solid #3b82f6; }

.task-info, .file-info { flex: 1; overflow: hidden; }
.task-name, .file-name { font-weight: 600; color: var(--app-text-main); margin-bottom: 2px; font-size: 13px; }
.task-meta, .file-meta { font-size: 11px; color: var(--app-text-muted); }
.empty-list { padding: 20px; text-align: center; color: var(--app-text-muted); font-size: 13px; }

/* Saved Logs Specific */
.saved-container {
  display: flex;
  width: 100%;
  height: 100%;
}

.saved-file-list {
  width: 320px; /* Widen for checkbox */
  border-right: 1px solid var(--app-border-color);
  display: flex;
  flex-direction: column;
  background: transparent; /* Was #f8fafc */
}

.file-item {
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  gap: 12px;
  border-bottom: 1px solid var(--app-border-color);
  transition: all 0.2s;
  align-items: flex-start;
}

.file-checkbox {
  margin-top: 2px;
}

/* Log Viewer Specific */
.saved-log-viewer {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: rgba(15, 23, 42, 0.8); /* Semi-transparent dark bg for logs */
  overflow: hidden;
  backdrop-filter: blur(10px);
}

/* Search Results Panel */
.search-results-panel {
  flex: 1;
  background: transparent;
  overflow-y: auto;
  padding: 0;
}

.search-result-group {
  border-bottom: 1px solid var(--app-border-color);
}

.group-header {
  padding: 8px 16px;
  background: rgba(0,0,0,0.02);
  font-weight: 600;
  font-size: 13px;
  color: var(--app-text-muted);
  display: flex;
  justify-content: space-between;
}

.group-matches {
  padding: 0;
}

.match-item {
  padding: 8px 16px;
  border-bottom: 1px solid var(--app-border-color);
  font-family: monospace;
  font-size: 12px;
  color: var(--app-text-main);
  cursor: pointer;
}
.match-item:hover { background: rgba(0,0,0,0.05); }
.match-line-num { color: var(--app-text-muted); margin-right: 8px; user-select: none; }

/* Detail / Viewer */
.task-detail {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: transparent; /* Was #fff */
  overflow: hidden;
}

.viewer-header {
  padding: 8px 16px;
  background: rgba(15, 23, 42, 0.9); /* Dark header */
  color: #e2e8f0;
  font-size: 13px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #1e293b; /* Subtle border */
  height: 50px;
}

.header-left {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-right: 16px;
  font-weight: 600;
  color: #94a3b8;
}

.header-right {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.log-lines {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  font-family: 'Menlo', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #cbd5e1;
}
.log-line { white-space: pre-wrap; word-break: break-all; }

.search-results { flex: 1; overflow-y: auto; background: transparent; }
.results-header { padding: 12px 16px; background: rgba(0,0,0,0.02); border-bottom: 1px solid var(--app-border-color); font-size: 13px; color: var(--app-text-muted); }
.result-item { padding: 12px 16px; border-bottom: 1px solid var(--app-border-color); cursor: pointer; }
.result-item:hover { background: rgba(0,0,0,0.05); }
.result-meta { display: flex; justify-content: space-between; font-size: 11px; color: var(--app-text-muted); margin-bottom: 4px; }
.res-file { font-weight: 600; color: #3b82f6; }
.result-content { font-family: monospace; font-size: 12px; color: var(--app-text-main); white-space: pre-wrap; }

.empty-detail, .empty-viewer { flex: 1; display: flex; align-items: center; justify-content: center; background: transparent; }

/* Live Logs */
.live-container { display: flex; flex-direction: column; height: 100%; }
.live-controls { display: flex; gap: 12px; margin-bottom: 16px; }
.log-raw { margin: 0; white-space: pre-wrap; word-break: break-all; font-family: 'Menlo', monospace; font-size: 12px; line-height: 1.5; color: #e2e8f0; }
</style>
