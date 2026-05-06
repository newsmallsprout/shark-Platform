import request from '@/utils/request'

export interface DBInstancePayload {
  id?: number
  name: string
  db_type: 'mysql' | 'postgresql' | 'redis' | 'mongo' | 'rabbitmq'
  deployment_mode?: 'single' | 'cluster'
  environment: 'dev' | 'test' | 'staging' | 'prod'
  host: string
  port: number
  default_database?: string
  read_only?: boolean
  owner_team?: string
  tags?: string[]
  extra_config?: Record<string, any>
  username?: string
  password?: string
}

export const dbManagerProApi = {
  listInstances(params?: Record<string, any>) {
    return request.get('db/instances/', { params })
  },
  createInstance(data: DBInstancePayload) {
    return request.post('db/instances/', data)
  },
  updateInstance(id: number, data: Partial<DBInstancePayload>) {
    return request.put(`db/instances/${id}/`, data)
  },
  testInstance(id: number) {
    return request.post(`db/instances/${id}/test/`)
  },
  getSchema(id: number) {
    return request.get(`db/instances/${id}/schema/`)
  },
  getTableDetail(id: number, database: string, table: string) {
    return request.get(`db/instances/${id}/table-detail/`, { params: { database, table } })
  },
  getDiagnostics(id: number) {
    return request.get(`db/instances/${id}/diagnostics/`)
  },
  formatSql(sql: string) {
    return request.post('db/sql/format/', { sql })
  },
  completion(instance_id: number, database: string, keyword = '', suggest_tables = false) {
    const params: Record<string, string | number> = { instance_id, database, keyword }
    if (suggest_tables) params.suggest_tables = '1'
    return request.get('db/sql/completion/', { params })
  },
  explainSql(instance_id: number, database: string, sql: string) {
    return request.post(
      'db/sql/explain/',
      { instance_id, database, sql, execute_mode: 'explain' },
      { timeout: 120000 },
    )
  },
  reviewSql(instance_id: number, database: string, sql: string) {
    return request.post(
      'db/sql/ai-review/',
      { instance_id, database, sql, review_mode: 'full' },
      { timeout: 180000 },
    )
  },
  listApprovalApplicants() {
    return request.get('db/sql/approval-applicants/')
  },
  createJob(data: Record<string, any>) {
    return request.post('db/sql/jobs/create/', data, { timeout: 180000 })
  },
  listJobs(params?: Record<string, any>) {
    return request.get('db/sql/jobs/', { params })
  },
  getJobDetail(id: number) {
    return request.get(`db/sql/jobs/${id}/`)
  },
  getJobResult(id: number) {
    return request.get(`db/sql/jobs/${id}/result/`)
  },
  getJobLogs(id: number) {
    return request.get(`db/sql/jobs/${id}/logs/`)
  },
  cancelJob(id: number) {
    return request.post(`db/sql/jobs/${id}/cancel/`)
  },
  pauseJob(id: number) {
    return request.post(`db/sql/jobs/${id}/pause/`)
  },
  resumeJob(id: number) {
    return request.post(`db/sql/jobs/${id}/resume/`)
  },
  listApprovals() {
    return request.get('db/approvals/')
  },
  getApprovalDetail(id: number) {
    return request.get(`db/approvals/${id}/`)
  },
  listApprovalPolicies() {
    return request.get('db/approval-policies/')
  },
  createApprovalPolicy(data: Record<string, any>) {
    return request.post('db/approval-policies/', data)
  },
  listAccessRules() {
    return request.get('db/access-rules/')
  },
  createAccessRule(data: Record<string, any>) {
    return request.post('db/access-rules/', data)
  },
  updateAccessRule(id: number, data: Record<string, any>) {
    return request.put(`db/access-rules/${id}/`, data)
  },
  deleteAccessRule(id: number) {
    return request.delete(`db/access-rules/${id}/`)
  },
  previewAccessRule(data: Record<string, any>) {
    return request.post('db/access-rules/preview/', data)
  },
  listExecutionPolicies() {
    return request.get('db/execution-policies/')
  },
  createExecutionPolicy(data: Record<string, any>) {
    return request.post('db/execution-policies/', data)
  },
  updateExecutionPolicy(id: number, data: Record<string, any>) {
    return request.put(`db/execution-policies/${id}/`, data)
  },
  deleteExecutionPolicy(id: number) {
    return request.delete(`db/execution-policies/${id}/`)
  },
  listPermissionSubjects() {
    return request.get('db/permission-subjects/')
  },
  listUsers() {
    return request.get('/users')
  },
  listRoles() {
    return request.get('/roles')
  },
  approve(id: number) {
    return request.post(`db/approvals/${id}/approve/`)
  },
  remindApproval(id: number) {
    return request.post(`db/approvals/${id}/remind/`)
  },
  reject(id: number, comment: string) {
    return request.post(`db/approvals/${id}/reject/`, { comment })
  },
  listAudit(params?: Record<string, any>) {
    return request.get('db/audit/logs/', { params })
  },
  exportAudit(params?: Record<string, any>) {
    return request.get('db/audit/export/', { params, responseType: 'blob' })
  },
  listBackupPlans() {
    return request.get('db/backup/plans/')
  },
  createBackupPlan(data: Record<string, any>) {
    return request.post('db/backup/plans/', data)
  },
  updateBackupPlan(id: number, data: Record<string, any>) {
    return request.put(`db/backup/plans/${id}/`, data)
  },
  runBackupPlan(id: number) {
    return request.post(`db/backup/plans/${id}/run/`)
  },
  listBackupRecords(params?: Record<string, any>) {
    return request.get('db/backup/records/', { params })
  },
  listRestoreJobs() {
    return request.get('db/restore/jobs/')
  },
  createRestoreJob(data: Record<string, any>) {
    return request.post('db/restore/jobs/', data)
  },
  listRollbackJobs() {
    return request.get('db/rollback/jobs/')
  },
  createRollbackJob(data: Record<string, any>) {
    return request.post('db/rollback/jobs/', data)
  },
  executeRollbackJob(id: number) {
    return request.post(`db/rollback/jobs/${id}/execute/`)
  }
}
