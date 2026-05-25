<template>
  <div class="create-task-container">
    <el-page-header @back="goBack" content="Create New Sync Task" class="page-header" />
    
    <el-card shadow="never" class="form-card">
      <el-form :model="form" :rules="rules" ref="formRef" label-width="150px" v-loading="submitting">
        <el-form-item label="Task ID" prop="task_id">
          <el-input v-model="form.task_id" placeholder="e.g. sync_users_order" />
        </el-form-item>
        
        <el-divider content-position="left">Source (MySQL)</el-divider>
        
        <el-form-item label="MySQL Connection" prop="source_conn_id">
          <el-select v-model="form.source_conn_id" placeholder="Select MySQL Connection" @change="handleSourceChange">
            <el-option
              v-for="item in mysqlConnections"
              :key="item.id"
              :label="`${item.id} (${item.host})`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Database" prop="mysql_database">
          <el-select 
            v-model="form.mysql_database" 
            placeholder="Select Database" 
            :disabled="!form.source_conn_id"
            @change="handleDatabaseChange"
          >
            <el-option
              v-for="db in databaseList"
              :key="db"
              :label="db"
              :value="db"
            />
          </el-select>
        </el-form-item>
        
        <el-divider content-position="left">Target (MongoDB)</el-divider>
        
        <el-form-item label="Mongo Connection" prop="target_conn_id">
          <el-select v-model="form.target_conn_id" placeholder="Select Mongo Connection">
            <el-option
              v-for="item in mongoConnections"
              :key="item.id"
              :label="`${item.id} (${item.hosts || item.host})`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Target Database" prop="mongo_database">
          <el-input v-model="form.mongo_database" placeholder="e.g. sync_db" />
        </el-form-item>
        
        <el-divider content-position="left">Table Mapping</el-divider>
        
        <el-form-item label="Tables to Sync">
          <div class="table-selector">
            <el-checkbox-group v-model="selectedTables">
              <el-checkbox v-for="table in tableList" :key="table" :label="table">{{ table }}</el-checkbox>
            </el-checkbox-group>
            <div v-if="!form.mysql_database" class="text-gray">Please select database first</div>
            <div v-else-if="tableList.length === 0" class="text-gray">No tables found</div>
          </div>
        </el-form-item>
        
        <el-form-item label="Sync Options">
          <el-checkbox v-model="form.auto_discover_new_tables">Auto Discover New Tables</el-checkbox>
          <el-checkbox v-model="form.update_insert_new_doc">Update Inserts New Doc (Versioning)</el-checkbox>
          <el-checkbox v-model="form.use_pk_as_mongo_id">Use MySQL PK as Mongo _id</el-checkbox>
        </el-form-item>

        <el-divider content-position="left">Binlog Start Position (Optional)</el-divider>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="Filename" prop="binlog_filename">
              <el-input v-model="form.binlog_filename" placeholder="e.g. mysql-bin.000001" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="Position" prop="binlog_position">
               <el-input-number v-model="form.binlog_position" :min="4" placeholder="e.g. 154" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">Performance (可配置)</el-divider>
        <el-form-item label="Preset">
          <el-select v-model="perfPreset" style="width: 260px" placeholder="Select preset" @change="applyPreset">
            <el-option label="Balanced (默认)" value="balanced" />
            <el-option label="High Throughput (追速)" value="fast" />
            <el-option label="Conservative (稳一点)" value="safe" />
          </el-select>
        </el-form-item>

        <el-collapse v-model="perfCollapse">
          <el-collapse-item title="高级性能参数" name="advanced">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="MySQL Fetch Batch">
                  <el-input-number v-model="form.mysql_fetch_batch" :min="100" :max="50000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Mongo Bulk Batch">
                  <el-input-number v-model="form.mongo_bulk_batch" :min="100" :max="50000" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="Prefetch Queue Size">
                  <el-input-number v-model="form.prefetch_queue_size" :min="1" :max="50" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Progress Interval (sec)">
                  <el-input-number v-model="form.progress_interval" :min="1" :max="300" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-divider content-position="left">Incremental Flush</el-divider>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="Inc Flush Batch">
                  <el-input-number v-model="form.inc_flush_batch" :min="1000" :max="200000" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Inc Flush Interval (sec)">
                  <el-input-number v-model="form.inc_flush_interval_sec" :min="1" :max="30" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="State Save Interval (sec)">
                  <el-input-number v-model="form.state_save_interval_sec" :min="1" :max="60" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-divider content-position="left">Rate Limit</el-divider>
            <el-form-item label="Enable Rate Limit">
              <el-switch v-model="form.rate_limit_enabled" />
            </el-form-item>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="Max Load Avg Ratio">
                  <el-input-number v-model="form.max_load_avg_ratio" :min="0.5" :max="10" :step="0.1" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Max Sleep (ms)">
                  <el-input-number v-model="form.max_sleep_ms" :min="0" :max="2000" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-divider content-position="left">Mongo Client</el-divider>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="Max Pool Size">
                  <el-input-number v-model="form.mongo_max_pool_size" :min="10" :max="500" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Write Concern (w)">
                  <el-input-number v-model="form.mongo_write_w" :min="0" :max="5" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
          </el-collapse-item>
        </el-collapse>
        
        <el-form-item>
          <el-button type="primary" @click="onSubmit">Create & Start</el-button>
          <el-button @click="goBack">Cancel</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useConnectionStore } from '@/stores/connection'
import { useTaskStore } from '@/stores/task'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'

const router = useRouter()
const connectionStore = useConnectionStore()
const taskStore = useTaskStore()
const { connections } = storeToRefs(connectionStore)

const formRef = ref()
const submitting = ref(false)
const databaseList = ref<string[]>([])
const tableList = ref<string[]>([])
const selectedTables = ref<string[]>([])

const form = reactive({
  task_id: '',
  source_conn_id: '',
  target_conn_id: '',
  mysql_database: '',
  mongo_database: '',
  auto_discover_new_tables: true,
  update_insert_new_doc: true,
  use_pk_as_mongo_id: true,
  pk_field: 'id',
  binlog_filename: '',
  binlog_position: undefined as number | undefined,

  progress_interval: 10,
  mysql_fetch_batch: 2000,
  mongo_bulk_batch: 2000,
  inc_flush_batch: 10000,
  inc_flush_interval_sec: 2,
  state_save_interval_sec: 2,
  prefetch_queue_size: 2,
  rate_limit_enabled: true,
  max_load_avg_ratio: 1.5,
  max_sleep_ms: 200,
  mongo_max_pool_size: 50,
  mongo_write_w: 1,
  mongo_write_j: false
})

const perfPreset = ref<'balanced' | 'fast' | 'safe'>('balanced')
const perfCollapse = ref<string[]>([])

const applyPreset = () => {
  if (perfPreset.value === 'safe') {
    form.mysql_fetch_batch = 2000
    form.mongo_bulk_batch = 2000
    form.prefetch_queue_size = 2
    form.inc_flush_batch = 10000
    form.inc_flush_interval_sec = 2
    form.state_save_interval_sec = 2
    form.rate_limit_enabled = true
    form.max_load_avg_ratio = 1.5
    form.max_sleep_ms = 200
    form.mongo_max_pool_size = 50
    form.mongo_write_w = 1
    form.mongo_write_j = false
    return
  }
  if (perfPreset.value === 'fast') {
    form.mysql_fetch_batch = 10000
    form.mongo_bulk_batch = 10000
    form.prefetch_queue_size = 8
    form.inc_flush_batch = 50000
    form.inc_flush_interval_sec = 1
    form.state_save_interval_sec = 2
    form.rate_limit_enabled = false
    form.max_load_avg_ratio = 3.0
    form.max_sleep_ms = 20
    form.mongo_max_pool_size = 200
    form.mongo_write_w = 1
    form.mongo_write_j = false
    perfCollapse.value = ['advanced']
    return
  }
  form.mysql_fetch_batch = 5000
  form.mongo_bulk_batch = 5000
  form.prefetch_queue_size = 4
  form.inc_flush_batch = 20000
  form.inc_flush_interval_sec = 2
  form.state_save_interval_sec = 2
  form.rate_limit_enabled = true
  form.max_load_avg_ratio = 2.5
  form.max_sleep_ms = 80
  form.mongo_max_pool_size = 100
  form.mongo_write_w = 1
  form.mongo_write_j = false
}

const rules = {
  task_id: [{ required: true, message: 'Please input task ID', trigger: 'blur' }],
  source_conn_id: [{ required: true, message: 'Please select source connection', trigger: 'change' }],
  target_conn_id: [{ required: true, message: 'Please select target connection', trigger: 'change' }],
  mysql_database: [{ required: true, message: 'Please select source database', trigger: 'change' }],
  mongo_database: [{ required: true, message: 'Please input target database', trigger: 'blur' }]
}

const mysqlConnections = computed(() => connections.value.filter(c => c.type === 'mysql'))
const mongoConnections = computed(() => connections.value.filter(c => c.type === 'mongo'))

onMounted(() => {
  connectionStore.fetchConnections()
  applyPreset()
})

const goBack = () => {
  router.back()
}

const handleSourceChange = async (val: string) => {
  form.mysql_database = ''
  databaseList.value = []
  tableList.value = []
  selectedTables.value = []
  
  if (val) {
    try {
      databaseList.value = await connectionStore.fetchDatabases(val)
    } catch (e) {
      console.error(e)
    }
  }
}

const handleDatabaseChange = async (val: string) => {
  tableList.value = []
  selectedTables.value = []
  
  if (val && form.source_conn_id) {
    try {
      tableList.value = await connectionStore.fetchTables(form.source_conn_id, val)
    } catch (e) {
      console.error(e)
    }
  }
}

const onSubmit = async () => {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid: boolean) => {
    if (valid) {
      if (selectedTables.value.length === 0 && !form.auto_discover_new_tables) {
        ElMessage.warning('Please select at least one table or enable auto discovery')
        return
      }
      
      const tableMap: Record<string, string> = {}
      if (selectedTables.value.length > 0) {
        selectedTables.value.forEach(t => {
          tableMap[t] = t
        })
      } else {
        tableMap['*'] = '*'
      }
      
      submitting.value = true
      try {
        await taskStore.createTask({
          ...form,
          table_map: tableMap
        })
        router.push('/tasks')
      } catch (e) {
        console.error(e)
      } finally {
        submitting.value = false
      }
    }
  })
}
</script>

<style scoped>
.create-task-container {
  /* padding: 20px; */
}
.page-header {
  margin-bottom: 20px;
}
.form-card {
  max-width: 800px;
  margin: 0 auto;
}
.table-selector {
  border: 1px solid #dcdfe6;
  padding: 10px;
  border-radius: 4px;
  max-height: 200px;
  overflow-y: auto;
}
.text-gray {
  color: #909399;
  font-size: 13px;
  text-align: center;
  padding: 20px;
}
</style>
