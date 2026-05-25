<template>
  <div class="connections-container">
    <div class="page-header">
      <div class="header-info">
        <h2 class="page-title">Data Connections</h2>
        <p class="page-subtitle">Manage your MySQL and MongoDB connection profiles</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" size="large" @click="handleCreate" class="action-btn shadow-btn">
          <el-icon><Plus /></el-icon> New Connection
        </el-button>
      </div>
    </div>
    
    <el-card shadow="never" class="table-card">
      <el-table :data="connections" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="Connection Name" min-width="180">
          <template #default="{ row }">
            <div class="conn-name-cell">
              <div :class="['type-icon', row.type]">
                <el-icon v-if="row.type === 'mysql'"><Coin /></el-icon>
                <el-icon v-else><Share /></el-icon>
              </div>
              <div class="name-info">
                <div class="name-text">{{ row.name }}</div>
                <div class="id-text">{{ row.id }}</div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="type" label="Database Type" width="140">
          <template #default="{ row }">
            <el-tag :type="row.type === 'mysql' ? 'primary' : 'success'" size="small" effect="dark" class="type-tag">
              {{ row.type.toUpperCase() }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="host" label="Endpoint" min-width="200">
          <template #default="{ row }">
            <div class="endpoint-info">
              <span class="host-text" v-if="row.type === 'mysql'">{{ row.host }}:{{ row.port }}</span>
              <span class="host-text" v-else>{{ row.hosts?.join(', ') || row.host }}</span>
              <div class="db-text" v-if="row.database">DB: {{ row.database }}</div>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="user" label="Credentials" width="150">
          <template #default="{ row }">
            <div class="user-info">
              <el-icon><User /></el-icon>
              <span>{{ row.user || 'Anonymous' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="Actions" width="280" fixed="right">
          <template #default="{ row }">
            <div class="action-group">
              <el-button size="small" @click="handleEdit(row)" plain>
                <el-icon><Edit /></el-icon> Edit
              </el-button>
              <el-button size="small" type="success" plain @click="handleTest(row)">
                <el-icon><Connection /></el-icon> Test
              </el-button>
              <el-button size="small" type="danger" text @click="handleDelete(row.id)">
                Delete
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="editMode ? 'Edit Connection' : 'New Connection'"
      width="640px"
      class="custom-dialog"
      destroy-on-close
    >
      <el-form :model="form" label-width="120px" label-position="top" class="conn-form">
        <div class="form-section">
          <h3 class="section-title">Basic Configuration</h3>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="Database Type">
                <el-radio-group v-model="form.type" :disabled="editMode" class="type-radio-group">
                  <el-radio-button label="mysql">MySQL</el-radio-button>
                  <el-radio-button label="mongo">MongoDB</el-radio-button>
                </el-radio-group>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="Connection ID" required>
                <el-input v-model="form.id" :disabled="editMode" placeholder="e.g. prod_mysql_01" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="Display Name" required>
            <el-input v-model="form.name" placeholder="Friendly name for this connection" />
          </el-form-item>
        </div>

        <div class="form-section">
          <h3 class="section-title">Network & Auth</h3>
          <template v-if="form.type === 'mysql'">
            <el-row :gutter="20">
              <el-col :span="18">
                <el-form-item label="Hostname" required>
                  <el-input v-model="form.host" placeholder="localhost or IP" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="Port" required>
                  <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
          </template>

          <template v-if="form.type === 'mongo'">
            <el-form-item label="Hosts (Replica Set)">
              <el-select
                v-model="form.hosts"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="host1:27017, host2:27017..."
                class="w-full"
              >
                <el-option v-for="h in form.hosts" :key="h" :label="h" :value="h" />
              </el-select>
              <div class="form-tip">Add all members for high availability</div>
            </el-form-item>
            <el-row :gutter="20" v-if="!form.hosts || form.hosts.length === 0">
              <el-col :span="18">
                <el-form-item label="Hostname">
                  <el-input v-model="form.host" placeholder="localhost" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="Port">
                  <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="Replica Set Name">
                  <el-input v-model="form.replica_set" placeholder="rs0" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="Auth Source DB">
                  <el-input v-model="form.auth_source" placeholder="admin" />
                </el-form-item>
              </el-col>
            </el-row>
          </template>

          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="Username">
                <el-input v-model="form.user" placeholder="root / admin" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="Password">
                <el-input v-model="form.password" type="password" show-password placeholder="Required" />
              </el-form-item>
            </el-col>
          </el-row>
          
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="Target Database">
                <el-input v-model="form.database" :placeholder="form.type === 'mysql' ? 'Optional' : 'Default DB'" />
              </el-form-item>
            </el-col>
            <el-col :span="12" v-if="form.type === 'mysql'">
              <el-form-item label="SSL Connection">
                <el-switch v-model="form.use_ssl" active-text="Enabled" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="testCurrentForm" :loading="testing" type="success" plain class="test-btn">
            <el-icon><Connection /></el-icon> Test Connectivity
          </el-button>
          <div class="footer-right">
            <el-button @click="dialogVisible = false">Cancel</el-button>
            <el-button type="primary" @click="submitForm" class="shadow-btn">Save Connection</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useConnectionStore } from '@/stores/connection'
import { storeToRefs } from 'pinia'
import { 
  Plus, Coin, Share, User, 
  Edit, Connection, Delete, Setting 
} from '@element-plus/icons-vue'

const connectionStore = useConnectionStore()
const { connections, loading } = storeToRefs(connectionStore)

const dialogVisible = ref(false)
const editMode = ref(false)
const testing = ref(false)

const form = reactive({
  id: '',
  name: '',
  type: 'mysql',
  host: 'localhost',
  port: 3306,
  user: 'root',
  password: '',
  database: '',
  hosts: [] as string[],
  replica_set: '',
  auth_source: 'admin',
  use_ssl: false
})

onMounted(() => {
  connectionStore.fetchConnections()
})

const handleCreate = () => {
  editMode.value = false
  Object.assign(form, {
    id: '',
    name: '',
    type: 'mysql',
    host: 'localhost',
    port: 3306,
    user: 'root',
    password: '',
    database: '',
    hosts: [],
    replica_set: '',
    auth_source: 'admin',
    use_ssl: false
  })
  dialogVisible.value = true
}

const handleEdit = (row: any) => {
  editMode.value = true
  Object.assign(form, {
    ...row,
    port: row.port || (row.type === 'mysql' ? 3306 : 27017)
  })
  dialogVisible.value = true
}

const handleTest = (row: any) => {
  connectionStore.testConnection(row)
}

const handleDelete = (id: string) => {
  ElMessageBox.confirm('Are you sure you want to remove this connection profile?', 'Delete Connection', {
    confirmButtonText: 'Remove',
    cancelButtonText: 'Cancel',
    type: 'error'
  }).then(() => {
    connectionStore.deleteConnection(id)
  })
}

const testCurrentForm = async () => {
  testing.value = true
  try {
    await connectionStore.testConnection(form as any)
  } finally {
    testing.value = false
  }
}

const submitForm = async () => {
  if (!form.id || !form.name) {
    ElMessage.warning('ID and Name are required')
    return
  }
  try {
    await connectionStore.saveConnection(form as any)
    dialogVisible.value = false
  } catch (e: any) {
    console.error(e)
  }
}
</script>

<style scoped>
.connections-container {
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

.table-card {
  border: 1px solid #f1f5f9 !important;
  border-radius: 12px !important;
}

.conn-name-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

.type-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
}

.type-icon.mysql { background: #eff6ff; color: #3b82f6; }
.type-icon.mongo { background: #f0fdf4; color: #10b981; }

.name-text {
  font-weight: 600;
  color: #1e293b;
  font-size: 14px;
}

.id-text {
  font-size: 11px;
  color: #94a3b8;
}

.type-tag {
  border-radius: 4px;
  font-weight: 700;
  font-size: 10px;
}

.endpoint-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.host-text {
  font-size: 13px;
  color: #334155;
  font-family: ui-monospace, monospace;
}

.db-text {
  font-size: 11px;
  color: #64748b;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #64748b;
}

.action-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.form-section {
  margin-bottom: 24px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
}

.section-title {
  font-size: 13px;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 16px;
  border-left: 3px solid #3b82f6;
  padding-left: 8px;
}

.dialog-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.footer-right {
  display: flex;
  gap: 12px;
}

.form-tip {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 4px;
}

.shadow-btn {
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}

.w-full { width: 100%; }

:deep(.el-form-item__label) {
  font-weight: 600;
  color: #475569;
  font-size: 13px;
  padding-bottom: 4px !important;
}

:deep(.el-input__inner) {
  font-family: ui-monospace, monospace;
}
</style>
