import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { systemApi } from '@/api/system'
import request from '@/utils/request'
import type { MonitorConfig, InspectionReport } from '@/types/system'
import { ElMessage } from 'element-plus'

export const useSystemStore = defineStore('system', () => {
  // Monitor State
  const monitorTasks = ref<any[]>([])
  const monitorLogs = ref<any[]>([])
  
  // Inspection State
  const reports = ref<any[]>([])
  const currentReport = ref<any | null>(null)
  const inspectionConfig = ref<any>({
    prometheus_url: '',
    ark_base_url: '',
    ark_api_key: '',
    ark_api_key_set: false,
    ark_model_id: ''
  })
  
  const loading = ref(false)
  
  // Monitor Actions
  const fetchMonitorTasks = async () => {
    loading.value = true
    try {
      monitorTasks.value = await systemApi.getMonitorTasks()
    } catch (e) {
      console.error(e)
    } finally {
      loading.value = false
    }
  }

  const saveMonitorTask = async (task: any) => {
    try {
      if (task.id) {
        await systemApi.updateMonitorTask(task.id, task)
      } else {
        await systemApi.saveMonitorTask(task)
      }
      ElMessage.success('Task saved')
      await fetchMonitorTasks()
    } catch (e) {
      console.error(e)
    }
  }

  const deleteMonitorTask = async (id: number) => {
    try {
      await systemApi.deleteMonitorTask(id)
      ElMessage.success('Task deleted')
      await fetchMonitorTasks()
    } catch (e) {
      console.error(e)
    }
  }
  
  const fetchMonitorLogs = async (taskId: string) => {
    loading.value = true
    try {
      monitorLogs.value = await systemApi.getMonitorLogs({ task_id: taskId })
    } catch (e) {
      console.error(e)
    } finally {
      loading.value = false
    }
  }

  const getLogContent = async (taskId: string, filename: string, keyword?: string) => {
    try {
      const res = await systemApi.getLogContent({ task_id: taskId, filename, keyword })
      return res.content
    } catch (e) {
      console.error(e)
      return ''
    }
  }
  
  // Inspection Actions
  const fetchReports = async () => {
    loading.value = true
    try {
      reports.value = await systemApi.getReports()
    } catch (e) {
      console.error(e)
    } finally {
      loading.value = false
    }
  }
  
  const runInspection = async (config?: any) => {
    try {
      await systemApi.runInspection(config)
      ElMessage.success('Inspection started')
      await fetchReports()
    } catch (e) {
      console.error(e)
    }
  }

  const fetchReportDetail = async (id: string) => {
    try {
      currentReport.value = await systemApi.getReportDetail(id)
    } catch (e) {
      console.error(e)
    }
  }

  const fetchInspectionConfig = async () => {
    try {
      inspectionConfig.value = await systemApi.getInspectionConfig()
    } catch (e) {
      console.error(e)
    }
  }

  const saveInspectionConfig = async (config: any) => {
    try {
      await systemApi.saveInspectionConfig(config)
      ElMessage.success('Configuration saved')
      await fetchInspectionConfig()
    } catch (e) {
      console.error(e)
    }
  }
  
  const systemStats = ref<any>(null)
  const currentUser = ref<any>(null)
  
  const fetchSystemStats = async () => {
    try {
      systemStats.value = await systemApi.getSystemStats()
    } catch (e) {
      console.error(e)
    }
  }

  const fetchCurrentUser = async () => {
    try {
      // Use relative path, axios baseURL will prepend /api
      currentUser.value = await request.get('/me')
    } catch (e) {
      console.error(e)
    }
  }

  const isAdmin = computed(() => currentUser.value?.is_superuser || currentUser.value?.groups?.includes('Admin'))
  
  const hasPermission = (perm: string) => {
    if (!currentUser.value) return false
    if (currentUser.value.is_superuser) return true
    if (currentUser.value.permissions?.includes(perm)) return true
    return false
  }
  
  return {
    monitorTasks,
    monitorLogs,
    reports,
    currentReport,
    inspectionConfig,
    systemStats,
    currentUser,
    isAdmin,
    hasPermission,
    loading,
    fetchMonitorTasks,
    saveMonitorTask,
    deleteMonitorTask,
    fetchMonitorLogs,
    getLogContent,
    fetchReports,
    runInspection,
    fetchReportDetail,
    fetchInspectionConfig,
    saveInspectionConfig,
    fetchSystemStats,
    fetchCurrentUser
  }
})
