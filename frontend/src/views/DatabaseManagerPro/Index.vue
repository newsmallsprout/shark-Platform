<template>
  <div class="dbm-pro-page">
    <div class="summary-grid">
      <el-card v-for="card in summaryCards" :key="card.label" shadow="never" class="summary-card">
        <div class="summary-label">{{ card.label }}</div>
        <div class="summary-value">{{ card.value }}</div>
        <div class="summary-extra">{{ card.extra }}</div>
      </el-card>
    </div>

    <div class="content-grid">
      <el-card shadow="never" class="instance-panel">
        <template #header>
          <div class="panel-header">
            <span>实例管理</span>
            <el-button type="primary" size="small" @click="openCreateDrawer">新增实例</el-button>
          </div>
        </template>
        <el-input v-model="filters.keyword" placeholder="搜索实例 / Host" clearable class="mb-12" @change="loadInstances" />
        <el-select v-model="filters.environment" placeholder="环境" clearable class="mb-12" @change="loadInstances">
          <el-option label="开发" value="dev" />
          <el-option label="测试" value="test" />
          <el-option label="预发" value="staging" />
          <el-option label="生产" value="prod" />
        </el-select>
        <el-table :data="instances" height="560" @row-click="selectInstance">
          <el-table-column prop="name" label="实例" min-width="140" />
          <el-table-column prop="db_type" label="类型" width="110" />
          <el-table-column label="部署" width="88">
            <template #default="{ row }">
              <el-tag size="small" :type="row.deployment_mode === 'cluster' ? 'warning' : 'info'" effect="plain">
                {{ row.deployment_mode === 'cluster' ? '集群' : '单点' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="environment" label="环境" width="100" />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click.stop="testInstance(row)">测试</el-button>
              <el-button link @click.stop="editInstance(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <div class="workspace-panel">
        <el-card shadow="never" class="workspace-card">
          <template #header>
            <div class="panel-header">
              <div>
                <div class="workspace-title">SQL 工作台</div>
                <div class="workspace-subtitle">{{ activeInstanceTitle }}</div>
              </div>
              <div class="toolbar-group">
                <el-button @click="formatSqlAction">格式化</el-button>
                <el-button @click="explainSqlAction" :loading="explainLoading" :disabled="!canRun">执行计划</el-button>
                <el-button type="warning" @click="reviewSqlAction" :loading="aiReviewLoading" :disabled="!canRun">AI 分析</el-button>
                <el-button @click="approvalSettingDrawerVisible = true" :disabled="!selectedInstance">审批设置</el-button>
                <el-button type="primary" @click="executeSqlAction" :loading="executeLoading" :disabled="!canRun">执行 SQL</el-button>
              </div>
            </div>
          </template>
          <div class="editor-topbar">
            <el-select v-model="selectedInstanceId" placeholder="选择实例" class="instance-input" @change="handleInstanceChange">
              <el-option v-for="item in instances" :key="item.id" :label="`${item.name} · ${item.environment}`" :value="item.id" />
            </el-select>
            <el-select v-model="workbench.database" placeholder="选择库 / Schema" class="database-input" filterable clearable>
              <el-option v-for="item in databaseOptions" :key="item" :label="item" :value="item" />
            </el-select>
            <el-select v-model="workbench.applicantUserId" placeholder="工单申请人" class="applicant-input" clearable filterable>
              <el-option v-for="item in approvalApplicants" :key="item.id" :label="`${item.username}${item.groups?.length ? ` (${item.groups.join(',')})` : ''}`" :value="item.id" />
            </el-select>
            <el-tag type="warning">自动模式: {{ autoExecuteModeText }}</el-tag>
          </div>
          <monaco-sql-editor
            v-model="workbench.sql"
            :language="editorLanguage"
            :extra-snippets="editorExtraSnippets"
            :fetch-completions="fetchEditorCompletions"
          />
        </el-card>

        <div class="workspace-bottom">
          <el-card shadow="never" class="analysis-card">
            <template #header>
              <div class="panel-header">
                <span>AI 分析 / 执行计划</span>
                <el-tag v-if="aiReview?.risk_level" :type="riskTagType(aiReview.risk_level)">{{ aiReview.risk_level }}</el-tag>
              </div>
            </template>
            <el-empty v-if="!aiReview && !explainResult.rows?.length" description="先执行 AI 分析或执行计划预览" />
            <template v-else>
              <el-alert
                v-if="aiReview"
                :title="`决策：${aiReview.decision || '-'} / SQL 类型：${aiReview.sql_type || '-'}`"
                :type="alertType(aiReview?.decision)"
                :closable="false"
                show-icon
                class="mb-12"
              />
              <el-descriptions v-if="aiReview" :column="1" border>
                <el-descriptions-item label="摘要">{{ aiReview.sql_summary || '-' }}</el-descriptions-item>
                <el-descriptions-item label="执行计划摘要">{{ aiReview.explain_summary || '-' }}</el-descriptions-item>
                <el-descriptions-item label="安全风险">
                  <div v-for="item in aiReview.security_findings || []" :key="item">{{ item }}</div>
                </el-descriptions-item>
                <el-descriptions-item label="性能建议">
                  <div v-for="item in aiReview.optimization_suggestions || []" :key="item">{{ item }}</div>
                </el-descriptions-item>
              </el-descriptions>
              <explain-visualizer v-if="explainResult.rows?.length" :headers="explainResult.headers" :rows="explainResult.rows" class="mt-12" />
              <el-table v-if="explainResult.rows?.length" :data="explainResult.rows" max-height="220" class="mt-12">
                <el-table-column v-for="header in explainResult.headers" :key="header" :prop="header" :label="header" min-width="140" />
              </el-table>
            </template>
          </el-card>

          <el-card shadow="never" class="result-card">
            <template #header>
              <div class="panel-header">
                <span>执行结果</span>
                <div class="toolbar-group">
                  <el-button v-if="activeJob?.status === 'running'" size="small" @click="pauseJobAction">暂停</el-button>
                  <el-button v-if="activeJob?.status === 'running'" size="small" type="danger" @click="cancelJobAction">取消</el-button>
                  <el-button v-if="activeJob?.status === 'paused'" size="small" type="primary" @click="resumeJobAction">恢复</el-button>
                </div>
              </div>
            </template>
            <div v-if="activeJob?.id" class="job-exec-panel">
              <div class="job-exec-row">
                <span class="job-exec-title">作业 #{{ activeJob.id }}</span>
                <el-tag effect="dark" :type="jobStatusTagType">{{ jobStatusLabel }}</el-tag>
                <span v-if="activeJob.trace_id" class="job-exec-trace">trace {{ activeJob.trace_id }}</span>
              </div>
              <div class="job-exec-meta">
                <span>实例：{{ activeJob.instance_name || `#${activeJob.instance}` }}</span>
                <span v-if="activeJob.database_name">库：{{ activeJob.database_name }}</span>
                <span v-if="activeJob.sql_type">类型：{{ activeJob.sql_type }}</span>
                <span v-if="activeJob.affected_rows != null">影响行：{{ activeJob.affected_rows }}</span>
                <span v-if="activeJob.duration_ms != null">耗时：{{ activeJob.duration_ms }} ms</span>
              </div>
              <el-progress
                class="job-exec-progress"
                :percentage="jobProgressUi.percent"
                :status="jobProgressUi.barStatus"
                :stroke-width="10"
                :striped="jobProgressUi.striped"
                :striped-flow="jobProgressUi.stripedFlow"
              />
              <div class="job-phase-hint">{{ jobPhaseHint }}</div>
              <el-alert
                v-if="activeJob.status === 'failed' && activeJob.error_message"
                type="error"
                :closable="false"
                show-icon
                class="job-exec-err"
                :title="String(activeJob.error_message)"
              />
              <el-alert
                v-else-if="activeJob.status === 'waiting_approval'"
                type="warning"
                :closable="false"
                show-icon
                title="当前作业在等待审批，审批通过后才会进入队列执行。"
              />
            </div>
            <el-tabs v-model="activePane">
              <el-tab-pane label="结果集" name="result">
                <el-table v-if="jobResult.rows_json?.length" :data="jobResult.rows_json" max-height="260">
                  <el-table-column v-for="header in jobResult.columns_json || []" :key="header" :prop="header" :label="header" min-width="140" />
                </el-table>
                <el-empty v-else description="暂无结果集" />
              </el-tab-pane>
              <el-tab-pane label="执行日志" name="logs">
                <el-empty
                  v-if="!jobLogs.length && (activeJob?.status === 'queued' || activeJob?.status === 'running')"
                  description="暂无日志输出；排队或执行刚开始时稍候刷新。"
                />
                <div v-else class="log-stream">
                  <div v-for="item in jobLogs" :key="`${item.seq}-${item.created_at}`" class="log-line" :class="item.level">
                    [{{ item.level }}] {{ item.message }}
                  </div>
                </div>
              </el-tab-pane>
              <el-tab-pane label="作业记录" name="jobs">
                <el-table :data="jobs" max-height="260" @row-click="loadJobDetail">
                  <el-table-column prop="id" label="Job" width="90" />
                  <el-table-column prop="instance_name" label="实例" min-width="120" />
                  <el-table-column prop="sql_type" label="类型" width="100" />
                  <el-table-column prop="status" label="状态" width="110" />
                  <el-table-column prop="duration_ms" label="耗时" width="100" />
                </el-table>
              </el-tab-pane>
              <el-tab-pane label="审批中心" name="approvals">
                <el-table :data="approvals" max-height="260">
                  <el-table-column prop="id" label="审批单" width="90" />
                  <el-table-column prop="applicant" label="申请人" width="120" />
                  <el-table-column prop="status" label="状态" width="100" />
                  <el-table-column prop="overdue" label="超时" width="90" />
                  <el-table-column prop="reason" label="原因" min-width="180" />
                  <el-table-column label="操作" width="150">
                    <template #default="{ row }">
                      <el-button link @click="viewApproval(row)">详情</el-button>
                      <el-button link type="primary" @click="approve(row)" :disabled="row.status !== 'pending'">通过</el-button>
                      <el-button link type="warning" @click="remind(row)" :disabled="row.status !== 'pending'">催办</el-button>
                      <el-button link type="danger" @click="reject(row)" :disabled="row.status !== 'pending'">拒绝</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-tab-pane>
              <el-tab-pane label="审计日志" name="audit">
                <div class="toolbar-group mb-12">
                  <el-button size="small" @click="exportAuditAction">导出 CSV</el-button>
                  <el-button size="small" @click="createRollbackFromSelectedAudit" :disabled="!auditLogs.length">生成回滚任务</el-button>
                </div>
                <el-table :data="auditLogs" max-height="260">
                  <el-table-column prop="id" label="审计ID" width="90" />
                  <el-table-column prop="instance_name" label="实例" min-width="120" />
                  <el-table-column prop="username" label="执行人" width="120" />
                  <el-table-column prop="sql_type" label="类型" width="100" />
                  <el-table-column prop="risk_level" label="风险" width="100" />
                  <el-table-column prop="success" label="成功" width="90" />
                </el-table>
              </el-tab-pane>
              <el-tab-pane label="审批策略" name="policies">
                <div class="toolbar-group mb-12">
                  <el-button type="primary" size="small" @click="openPolicyDrawer">新增策略</el-button>
                </div>
                <el-table :data="approvalPolicies" max-height="260">
                  <el-table-column prop="name" label="策略名称" min-width="140" />
                  <el-table-column prop="environment_scope" label="环境" min-width="120" />
                  <el-table-column prop="db_type_scope" label="数据库类型" min-width="120" />
                  <el-table-column prop="sql_type_scope" label="SQL 类型" min-width="120" />
                  <el-table-column prop="risk_scope" label="风险级别" min-width="120" />
                  <el-table-column prop="enabled" label="启用" width="90" />
                </el-table>
              </el-tab-pane>
              <el-tab-pane v-if="canManageDbPermissions" label="访问控制" name="access">
                <div class="toolbar-group mb-12">
                  <el-button type="primary" size="small" @click="openAccessRuleDrawer">新增访问规则</el-button>
                </div>
                <el-table :data="accessRules" max-height="260">
                  <el-table-column prop="name" label="规则名称" min-width="140" />
                  <el-table-column prop="username" label="用户" width="120" />
                  <el-table-column prop="group_name" label="角色组" width="120" />
                  <el-table-column prop="instance_name" label="实例" min-width="120" />
                  <el-table-column prop="database_pattern" label="库范围" width="120" />
                  <el-table-column prop="table_pattern" label="表范围" width="120" />
                  <el-table-column prop="actions" label="动作" min-width="160" />
                  <el-table-column prop="match_explanation" label="命中解释" min-width="220" />
                  <el-table-column prop="conflicts" label="冲突规则" min-width="160" />
                </el-table>
              </el-tab-pane>
              <el-tab-pane label="备份恢复" name="backup">
                <div class="toolbar-group mb-12">
                  <el-button type="primary" size="small" @click="openBackupPlanDrawer()" :disabled="!selectedInstance">新增备份计划</el-button>
                  <el-button size="small" @click="openRestoreDrawer()" :disabled="!selectedInstance">创建恢复任务</el-button>
                  <el-button size="small" type="warning" @click="createRollbackFromSelectedAudit" :disabled="!auditLogs.length">创建回滚任务</el-button>
                </div>
                <el-table :data="backupPlans" max-height="120">
                  <el-table-column prop="name" label="计划" min-width="140" />
                  <el-table-column prop="instance_name" label="实例" min-width="120" />
                  <el-table-column prop="backup_type" label="类型" width="100" />
                  <el-table-column prop="retention_days" label="保留天数" width="100" />
                  <el-table-column prop="storage_uri" label="存储目标" min-width="180" />
                  <el-table-column label="操作" width="150">
                    <template #default="{ row }">
                      <el-button link @click="openBackupPlanDrawer(row)">编辑</el-button>
                      <el-button link type="primary" @click="runBackup(row)">立即执行</el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-divider content-position="left">备份记录</el-divider>
                <el-table :data="backupRecords" max-height="120">
                  <el-table-column prop="instance_name" label="实例" min-width="120" />
                  <el-table-column prop="file_uri" label="文件" min-width="220" />
                  <el-table-column prop="checksum_sha256" label="校验和" min-width="180" />
                  <el-table-column prop="status" label="状态" width="100" />
                </el-table>
                <el-divider content-position="left">恢复任务</el-divider>
                <el-table :data="restoreJobs" max-height="120">
                  <el-table-column prop="instance_name" label="实例" min-width="120" />
                  <el-table-column prop="restore_mode" label="模式" width="110" />
                  <el-table-column prop="status" label="状态" width="100" />
                  <el-table-column prop="target_txn_id" label="事务 / 时间点" min-width="160" />
                </el-table>
                <el-divider content-position="left">回滚任务</el-divider>
                <el-table :data="rollbackJobs" max-height="120">
                  <el-table-column prop="instance_name" label="实例" min-width="120" />
                  <el-table-column prop="status" label="状态" width="100" />
                  <el-table-column prop="source_audit" label="来源审计" width="120" />
                  <el-table-column label="操作" width="120">
                    <template #default="{ row }">
                      <el-button link type="danger" @click="runRollback(row)">执行回滚</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-tab-pane>
              <el-tab-pane label="实例诊断" name="diagnostics">
                <div class="toolbar-group mb-12">
                  <el-button size="small" type="primary" @click="runDiagnosticsAction" :disabled="!selectedInstance">重新诊断</el-button>
                </div>
                <el-descriptions v-if="diagnosticsReport" :column="2" border>
                  <el-descriptions-item label="Schema 数">{{ diagnosticsReport.summary?.schema_count ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="表数量">{{ diagnosticsReport.summary?.table_count ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="备份计划">{{ diagnosticsReport.summary?.backup_plan_count ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="最近备份状态">{{ diagnosticsReport.summary?.latest_backup_status ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="SQL 作业">{{ diagnosticsReport.summary?.sql_job_count ?? '-' }}</el-descriptions-item>
                  <el-descriptions-item label="失败作业">{{ diagnosticsReport.summary?.failed_sql_jobs ?? '-' }}</el-descriptions-item>
                </el-descriptions>
                <el-timeline class="mt-12">
                  <el-timeline-item v-for="item in diagnosticsReport?.checks || []" :key="`${item.name}-${item.message}`" :type="item.status === 'failed' ? 'danger' : item.status === 'warning' ? 'warning' : 'primary'">
                    <div class="diag-title">{{ item.name }}</div>
                    <div class="diag-desc">{{ item.message }}</div>
                  </el-timeline-item>
                </el-timeline>
              </el-tab-pane>
            </el-tabs>
          </el-card>
        </div>
      </div>
    </div>

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="520px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="实例名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="数据库类型">
          <el-select v-model="form.db_type">
            <el-option label="MySQL" value="mysql" />
            <el-option label="PostgreSQL" value="postgresql" />
            <el-option label="Redis" value="redis" />
            <el-option label="MongoDB" value="mongo" />
            <el-option label="RabbitMQ" value="rabbitmq" />
          </el-select>
        </el-form-item>
        <el-form-item label="部署模式">
          <el-radio-group v-model="form.deployment_mode">
            <el-radio-button label="single">单点</el-radio-button>
            <el-radio-button label="cluster">集群</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="环境">
          <el-select v-model="form.environment">
            <el-option label="开发" value="dev" />
            <el-option label="测试" value="test" />
            <el-option label="预发" value="staging" />
            <el-option label="生产" value="prod" />
          </el-select>
        </el-form-item>
        <el-form-item label="Host"><el-input v-model="form.host" /></el-form-item>
        <el-form-item label="Port">
          <el-input-number v-model="form.port" :min="1" :max="65535" @change="onInstancePortUserChange" />
        </el-form-item>
        <el-form-item label="默认库">
          <el-input v-model="form.default_database" :placeholder="drawerDatabasePlaceholder" />
        </el-form-item>
        <el-form-item label="用户名"><el-input v-model="form.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password /></el-form-item>
        <el-form-item label="所属团队"><el-input v-model="form.owner_team" /></el-form-item>
        <el-form-item label="只读实例"><el-switch v-model="form.read_only" /></el-form-item>
        <el-divider content-position="left">PITR 配置</el-divider>
        <template v-if="drawerPitrFields.length">
          <el-form-item v-for="field in drawerPitrFields" :key="field.key" :label="field.label">
            <el-input
              v-if="field.kind === 'text'"
              v-model="form.extra_config[field.key]"
              :placeholder="field.placeholder"
            />
            <el-input-number
              v-else-if="field.kind === 'number'"
              v-model="form.extra_config[field.key]"
              :min="field.min ?? 1024"
              :max="field.max ?? 65535"
              style="width: 100%"
            />
            <el-switch v-else-if="field.kind === 'switch'" v-model="form.extra_config[field.key]" />
          </el-form-item>
        </template>
        <el-alert
          v-else
          type="info"
          :closable="false"
          show-icon
          title="当前数据库类型无需配置 PITR 本地路径"
          description="备份/恢复任务仍可按控制台与备份记录流程执行。"
        />
      </el-form>
      <template #footer>
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" @click="submitInstance">保存</el-button>
      </template>
    </el-drawer>

    <el-drawer v-model="policyDrawerVisible" title="审批策略配置" size="560px">
      <el-form :model="policyForm" label-width="120px">
        <el-form-item label="策略名称"><el-input v-model="policyForm.name" /></el-form-item>
        <el-form-item label="环境范围">
          <el-select v-model="policyForm.environment_scope" multiple>
            <el-option label="开发" value="dev" />
            <el-option label="测试" value="test" />
            <el-option label="预发" value="staging" />
            <el-option label="生产" value="prod" />
          </el-select>
        </el-form-item>
        <el-form-item label="数据库类型">
          <el-select v-model="policyForm.db_type_scope" multiple>
            <el-option label="MySQL" value="mysql" />
            <el-option label="PostgreSQL" value="postgresql" />
            <el-option label="Redis" value="redis" />
            <el-option label="MongoDB" value="mongo" />
          </el-select>
        </el-form-item>
        <el-form-item label="SQL 类型">
          <el-select v-model="policyForm.sql_type_scope" multiple>
            <el-option label="SELECT" value="SELECT" />
            <el-option label="INSERT" value="INSERT" />
            <el-option label="UPDATE" value="UPDATE" />
            <el-option label="DELETE" value="DELETE" />
            <el-option label="ALTER" value="ALTER" />
            <el-option label="DROP" value="DROP" />
            <el-option label="CREATE" value="CREATE" />
            <el-option label="TRUNCATE" value="TRUNCATE" />
          </el-select>
        </el-form-item>
        <el-form-item label="风险级别">
          <el-select v-model="policyForm.risk_scope" multiple>
            <el-option label="low" value="low" />
            <el-option label="medium" value="medium" />
            <el-option label="high" value="high" />
            <el-option label="critical" value="critical" />
          </el-select>
        </el-form-item>
        <el-form-item label="SLA(分钟)"><el-input-number v-model="policyForm.sla_minutes" :min="5" :max="1440" /></el-form-item>
        <el-form-item label="审批流">
          <div class="flow-config">
            <div v-for="(step, index) in policyForm.approval_flow" :key="index" class="flow-row">
              <el-select v-model="step.group_name" placeholder="审批角色组">
                <el-option v-for="item in roleOptions" :key="item.name" :label="item.name" :value="item.name" />
              </el-select>
              <el-input-number v-model="step.sla_minutes" :min="5" :max="1440" />
              <el-button link type="danger" @click="policyForm.approval_flow.splice(index, 1)">删除</el-button>
            </div>
            <el-button size="small" @click="policyForm.approval_flow.push({ group_name: '', sla_minutes: policyForm.sla_minutes })">新增审批节点</el-button>
          </div>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="policyForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="policyDrawerVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPolicy">保存</el-button>
      </template>
    </el-drawer>

    <el-drawer v-model="accessDrawerVisible" title="访问控制规则" size="560px">
      <el-form :model="accessRuleForm" label-width="120px">
        <el-form-item label="规则名称"><el-input v-model="accessRuleForm.name" /></el-form-item>
        <el-form-item label="用户">
          <el-select v-model="accessRuleForm.user_id" clearable filterable placeholder="选择用户">
            <el-option v-for="item in userOptions" :key="item.id" :label="item.username" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色组">
          <el-select v-model="accessRuleForm.group_name" clearable filterable placeholder="选择角色组">
            <el-option v-for="item in roleOptions" :key="item.name" :label="item.name" :value="item.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="实例">
          <el-select v-model="accessRuleForm.instance" clearable>
            <el-option v-for="item in instances" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="库范围"><el-input v-model="accessRuleForm.database_pattern" placeholder="* 或具体库名" /></el-form-item>
        <el-form-item label="表范围"><el-input v-model="accessRuleForm.table_pattern" placeholder="* 或 order_*" /></el-form-item>
        <el-form-item label="SQL 类型">
          <el-select v-model="accessRuleForm.sql_types" multiple>
            <el-option label="SELECT" value="SELECT" />
            <el-option label="INSERT" value="INSERT" />
            <el-option label="UPDATE" value="UPDATE" />
            <el-option label="DELETE" value="DELETE" />
            <el-option label="ALTER" value="ALTER" />
            <el-option label="DROP" value="DROP" />
            <el-option label="CREATE" value="CREATE" />
            <el-option label="TRUNCATE" value="TRUNCATE" />
          </el-select>
        </el-form-item>
        <el-form-item label="动作权限">
          <el-select v-model="accessRuleForm.actions" multiple>
            <el-option label="查看" value="view" />
            <el-option label="查询" value="query" />
            <el-option label="DML" value="dml" />
            <el-option label="DDL" value="ddl" />
            <el-option label="审批" value="approve" />
            <el-option label="管理" value="manage" />
            <el-option label="备份恢复" value="backup" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="accessRuleForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accessDrawerVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAccessRule">保存</el-button>
      </template>
    </el-drawer>

    <el-drawer v-model="backupPlanDrawerVisible" :title="backupPlanForm.id ? '编辑备份计划' : '新增备份计划'" size="620px">
      <el-form :model="backupPlanForm" label-width="140px">
        <el-form-item label="实例">
          <el-select v-model="backupPlanForm.instance">
            <el-option v-for="item in instances" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="计划名称"><el-input v-model="backupPlanForm.name" /></el-form-item>
        <el-form-item label="备份类型">
          <el-select v-model="backupPlanForm.backup_type">
            <el-option label="逻辑备份" value="logical" />
            <el-option label="物理备份" value="physical" />
            <el-option label="快照" value="snapshot" />
          </el-select>
        </el-form-item>
        <el-form-item label="Cron 表达式"><el-input v-model="backupPlanForm.schedule_expr" placeholder="0 2 * * *" /></el-form-item>
        <el-form-item label="保留天数"><el-input-number v-model="backupPlanForm.retention_days" :min="1" :max="3650" /></el-form-item>
        <el-form-item label="存储 URI"><el-input v-model="backupPlanForm.storage_uri" placeholder="s3://bucket/prefix 或 local://..." /></el-form-item>
        <el-form-item label="启用压缩"><el-switch v-model="backupPlanForm.compression_enabled" /></el-form-item>
        <el-form-item label="启用加密"><el-switch v-model="backupPlanForm.encryption_enabled" /></el-form-item>
        <el-divider content-position="left">对象存储配置</el-divider>
        <el-form-item label="Bucket"><el-input v-model="backupPlanForm.storage_config.bucket" /></el-form-item>
        <el-form-item label="Region"><el-input v-model="backupPlanForm.storage_config.region" /></el-form-item>
        <el-form-item label="Endpoint"><el-input v-model="backupPlanForm.storage_config.endpoint" placeholder="https://s3.amazonaws.com 或 MinIO 地址" /></el-form-item>
        <el-form-item label="Access Key"><el-input v-model="backupPlanForm.storage_config.access_key" /></el-form-item>
        <el-form-item label="Secret Key"><el-input v-model="backupPlanForm.storage_config.secret_key" type="password" show-password /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="backupPlanForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="backupPlanDrawerVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBackupPlan">保存</el-button>
      </template>
    </el-drawer>

    <el-drawer v-model="restoreDrawerVisible" title="创建恢复任务 / PITR" size="620px">
      <el-form :model="restoreForm" label-width="140px">
        <el-form-item label="实例">
          <el-select v-model="restoreForm.instance">
            <el-option v-for="item in instances" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备份记录">
          <el-select v-model="restoreForm.backup_record" clearable filterable>
            <el-option v-for="item in backupRecords.filter(record => record.instance === restoreForm.instance || record.instance_id === restoreForm.instance)" :key="item.id" :label="`${item.id} - ${item.file_uri}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="恢复模式">
          <el-radio-group v-model="restoreForm.restore_mode">
            <el-radio-button label="backup">备份恢复</el-radio-button>
            <el-radio-button label="point_in_time">时间点恢复</el-radio-button>
            <el-radio-button label="transaction">事务恢复</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="restoreForm.restore_mode === 'point_in_time'" label="目标时间">
          <el-date-picker v-model="restoreForm.target_time" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" />
        </el-form-item>
        <el-form-item v-if="restoreForm.restore_mode === 'transaction'" label="目标事务">
          <el-input v-model="restoreForm.target_txn_id" placeholder="MySQL GTID / stop-position 或 PostgreSQL XID" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="restoreDrawerVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRestoreJob">创建</el-button>
      </template>
    </el-drawer>

    <el-drawer v-model="approvalSettingDrawerVisible" title="审批工单设置" size="560px">
      <el-form :model="workbench" label-width="120px">
        <el-form-item label="申请人">
          <el-select v-model="workbench.applicantUserId" clearable filterable>
            <el-option v-for="item in approvalApplicants" :key="item.id" :label="`${item.username}${item.groups?.length ? ` (${item.groups.join(',')})` : ''}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="抄送人">
          <el-select v-model="workbench.ccUserIds" multiple clearable filterable>
            <el-option v-for="item in userOptions" :key="item.id" :label="item.username" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="申请原因">
          <el-input v-model="workbench.approvalReason" type="textarea" :rows="3" placeholder="说明执行目的、影响范围和回滚方案" />
        </el-form-item>
        <el-form-item label="指定审批链">
          <div class="flow-config">
            <div v-for="(step, index) in workbench.approvalFlow" :key="index" class="flow-row">
              <el-select v-model="step.group_name" placeholder="审批角色组">
                <el-option v-for="item in roleOptions" :key="item.name" :label="item.name" :value="item.name" />
              </el-select>
              <el-input-number v-model="step.sla_minutes" :min="5" :max="1440" />
              <el-button link type="danger" @click="workbench.approvalFlow.splice(index, 1)">删除</el-button>
            </div>
            <el-button size="small" @click="workbench.approvalFlow.push({ group_name: '', sla_minutes: 60 })">新增审批节点</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="approvalSettingDrawerVisible = false">关闭</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { dbManagerProApi, type DBInstancePayload } from '@/api/db_manager_pro'
import { useSystemStore } from '@/stores/system'
import { useRouter } from 'vue-router'
import MonacoSqlEditor from './components/MonacoSqlEditor.vue'
import ExplainVisualizer from './components/ExplainVisualizer.vue'
import { getDbTypePreset } from './dbInstanceTypePresets'

const systemStore = useSystemStore()
const router = useRouter()

const filters = reactive({ keyword: '', environment: '' })
const instances = ref<any[]>([])
const approvals = ref<any[]>([])
const auditLogs = ref<any[]>([])
const approvalPolicies = ref<any[]>([])
const accessRules = ref<any[]>([])
const backupPlans = ref<any[]>([])
const backupRecords = ref<any[]>([])
const restoreJobs = ref<any[]>([])
const rollbackJobs = ref<any[]>([])
const jobs = ref<any[]>([])
const userOptions = ref<any[]>([])
const roleOptions = ref<any[]>([])
const approvalApplicants = ref<any[]>([])
const databaseOptions = ref<string[]>([])
const selectedInstance = ref<any>(null)
const selectedInstanceId = ref<number | undefined>(undefined)
const drawerVisible = ref(false)
const drawerTitle = ref('新增实例')
const activePane = ref('result')
const aiReview = ref<any>(null)
const explainResult = ref<any>({ headers: [], rows: [] })
const activeJob = ref<any>(null)
const jobLogs = ref<any[]>([])
const jobResult = ref<any>({ columns_json: [], rows_json: [] })
const portManuallyEdited = ref(false)
const applyingPresetPort = ref(false)
const flushingDrawerFromRow = ref(false)
const diagnosticsReport = ref<any>(null)
const policyDrawerVisible = ref(false)
const accessDrawerVisible = ref(false)
const backupPlanDrawerVisible = ref(false)
const restoreDrawerVisible = ref(false)
const approvalSettingDrawerVisible = ref(false)
const form = reactive<DBInstancePayload>({
  name: '',
  db_type: 'mysql',
  deployment_mode: 'single',
  environment: 'dev',
  host: '',
  port: 3306,
  default_database: '',
  username: '',
  password: '',
  read_only: false,
  owner_team: '',
  tags: [],
  extra_config: {
    mysql_binlog_dir: '',
    pg_wal_archive_dir: '',
    pg_restore_data_dir: '',
    pg_ctl_path: '',
    pg_pitr_port: 55432,
    pg_auto_start_recovery: false
  }
})
const workbench = reactive({
  database: '',
  sql: '',
  applicantUserId: undefined as number | undefined,
  ccUserIds: [] as number[],
  approvalReason: '',
  approvalFlow: [] as Array<{ group_name: string; sla_minutes: number }>
})
const policyForm = reactive({
  name: '',
  environment_scope: ['prod'],
  db_type_scope: [] as string[],
  sql_type_scope: ['ALTER', 'DROP', 'TRUNCATE', 'UPDATE', 'DELETE', 'INSERT'],
  risk_scope: ['high', 'critical'],
  approval_flow: [{ group_name: '', sla_minutes: 60 }] as Array<{ group_name: string; sla_minutes: number }>,
  sla_minutes: 60,
  enabled: true
})
const accessRuleForm = reactive({
  name: '',
  user_id: undefined as number | undefined,
  group_name: '',
  instance: undefined as number | undefined,
  database_pattern: '*',
  table_pattern: '*',
  sql_types: [] as string[],
  actions: ['view', 'query'] as string[],
  enabled: true
})
const backupPlanForm = reactive({
  id: undefined as number | undefined,
  instance: undefined as number | undefined,
  name: '',
  backup_type: 'logical',
  schedule_expr: '0 2 * * *',
  retention_days: 7,
  storage_uri: 'local://db_backups',
  storage_config: {
    bucket: '',
    region: '',
    endpoint: '',
    access_key: '',
    secret_key: ''
  },
  compression_enabled: true,
  encryption_enabled: false,
  enabled: true
})
const restoreForm = reactive({
  instance: undefined as number | undefined,
  backup_record: undefined as number | undefined,
  restore_mode: 'backup',
  target_time: '',
  target_txn_id: ''
})

let pollTimer: number | undefined
let pollIntervalDesiredMs = 0
const explainLoading = ref(false)
const aiReviewLoading = ref(false)
const executeLoading = ref(false)

const summaryCards = computed(() => {
  const online = instances.value.filter(item => item.status === 'online').length
  const running = jobs.value.filter(item => item.status === 'running').length
  const pending = approvals.value.filter(item => item.status === 'pending').length
  const risky = auditLogs.value.filter(item => ['high', 'critical'].includes(item.risk_level)).length
  return [
    { label: '实例总数', value: instances.value.length, extra: `${online} 在线` },
    { label: '执行作业', value: jobs.value.length, extra: `${running} 运行中` },
    { label: '待审批', value: pending, extra: '高风险 SQL 进入审批' },
    { label: '高风险审计', value: risky, extra: `备份计划 ${backupPlans.value.length} 条` }
  ]
})

const canManageDbPermissions = computed(() => {
  return systemStore.isAdmin || systemStore.hasPermission('manage_db_permissions') || systemStore.hasPermission('manage_db_instances')
})

const activeInstanceTitle = computed(() => {
  if (!selectedInstance.value) return '请选择实例并输入 SQL'
  return `${selectedInstance.value.name} · ${selectedInstance.value.environment} · ${selectedInstance.value.db_type}`
})

const drawerDatabasePlaceholder = computed(() => getDbTypePreset(form.db_type).defaultDatabasePlaceholder)
const drawerPitrFields = computed(() => getDbTypePreset(form.db_type).pitrFields)

const editorLanguage = computed(() => getDbTypePreset(selectedInstance.value?.db_type).monacoLanguage)
const editorExtraSnippets = computed(() => getDbTypePreset(selectedInstance.value?.db_type).editorSnippets)

const canRun = computed(() => Boolean(selectedInstance.value?.id && workbench.sql.trim()))
const autoExecuteModeText = computed(() => {
  const sql = workbench.sql.trim().toUpperCase()
  if (!sql) return '待识别'
  if (/^(INSERT|UPDATE|DELETE|MERGE|ALTER|DROP|TRUNCATE|CREATE|RENAME)\b/.test(sql)) return '事务执行'
  return '自动提交'
})

const resetForm = () => {
  portManuallyEdited.value = false
  Object.assign(form, {
    id: undefined,
    name: '',
    db_type: 'mysql',
    deployment_mode: 'single',
    environment: 'dev',
    host: '',
    port: 3306,
    default_database: '',
    username: '',
    password: '',
    read_only: false,
    owner_team: '',
    tags: [],
    extra_config: {
      mysql_binlog_dir: '',
      pg_wal_archive_dir: '',
      pg_restore_data_dir: '',
      pg_ctl_path: '',
      pg_pitr_port: 55432,
      pg_auto_start_recovery: false
    }
  })
}

const onInstancePortUserChange = () => {
  if (applyingPresetPort.value) return
  portManuallyEdited.value = true
}

watch(
  () => form.db_type,
  () => {
    if (flushingDrawerFromRow.value) return
    if (portManuallyEdited.value) return
    applyingPresetPort.value = true
    form.port = getDbTypePreset(form.db_type).defaultPort
    nextTick(() => {
      applyingPresetPort.value = false
    })
  }
)

const openCreateDrawer = () => {
  drawerTitle.value = '新增实例'
  resetForm()
  drawerVisible.value = true
}

const editInstance = (row: any) => {
  flushingDrawerFromRow.value = true
  drawerTitle.value = '编辑实例'
  resetForm()
  Object.assign(form, row, {
    password: '',
    deployment_mode: row.deployment_mode === 'cluster' ? 'cluster' : 'single',
    extra_config: {
      mysql_binlog_dir: row.extra_config?.mysql_binlog_dir || '',
      pg_wal_archive_dir: row.extra_config?.pg_wal_archive_dir || '',
      pg_restore_data_dir: row.extra_config?.pg_restore_data_dir || '',
      pg_ctl_path: row.extra_config?.pg_ctl_path || '',
      pg_pitr_port: row.extra_config?.pg_pitr_port || 55432,
      pg_auto_start_recovery: !!row.extra_config?.pg_auto_start_recovery
    }
  })
  drawerVisible.value = true
  nextTick(() => {
    flushingDrawerFromRow.value = false
  })
}

const submitInstance = async () => {
  const payload = { ...form }
  if (payload.id) {
    await dbManagerProApi.updateInstance(payload.id, payload)
    ElMessage.success('实例已更新')
  } else {
    await dbManagerProApi.createInstance(payload)
    ElMessage.success('实例已创建')
  }
  drawerVisible.value = false
  await loadInstances()
}

const loadInstances = async () => {
  const data = await dbManagerProApi.listInstances({ keyword: filters.keyword || undefined, environment: filters.environment || undefined })
  instances.value = Array.isArray(data) ? data : []
  if (!selectedInstance.value && instances.value.length) {
    selectInstance(instances.value[0])
  }
}

const loadJobs = async () => {
  const data = await dbManagerProApi.listJobs()
  jobs.value = Array.isArray(data) ? data : []
}

const loadApprovals = async () => {
  const data = await dbManagerProApi.listApprovals()
  approvals.value = Array.isArray(data) ? data : []
}

const loadAudit = async () => {
  const data = await dbManagerProApi.listAudit()
  auditLogs.value = Array.isArray(data) ? data : []
}

const loadPolicies = async () => {
  const data = await dbManagerProApi.listApprovalPolicies()
  approvalPolicies.value = Array.isArray(data) ? data : []
}

const loadAccessRules = async () => {
  if (!canManageDbPermissions.value) {
    accessRules.value = []
    return
  }
  const data = await dbManagerProApi.listAccessRules()
  accessRules.value = Array.isArray(data) ? data : []
}

const loadUserRoleOptions = async () => {
  if (!canManageDbPermissions.value) {
    userOptions.value = []
    roleOptions.value = []
    return
  }
  const data = await dbManagerProApi.listPermissionSubjects()
  userOptions.value = Array.isArray(data.users) ? data.users : []
  roleOptions.value = Array.isArray(data.roles) ? data.roles : []
}

const loadApprovalApplicants = async () => {
  const data = await dbManagerProApi.listApprovalApplicants()
  approvalApplicants.value = Array.isArray(data.users) ? data.users : []
  if (!workbench.applicantUserId && approvalApplicants.value.length) {
    workbench.applicantUserId = approvalApplicants.value[0].id
  }
}

const loadDatabaseOptions = async (instanceId: number) => {
  const data = await dbManagerProApi.getSchema(instanceId)
  databaseOptions.value = Object.keys(data || {})
}

const loadBackupData = async () => {
  const [plans, records, restores, rollbacks] = await Promise.all([
    dbManagerProApi.listBackupPlans(),
    dbManagerProApi.listBackupRecords(),
    dbManagerProApi.listRestoreJobs(),
    dbManagerProApi.listRollbackJobs()
  ])
  backupPlans.value = Array.isArray(plans) ? plans : []
  backupRecords.value = Array.isArray(records) ? records : []
  restoreJobs.value = Array.isArray(restores) ? restores : []
  rollbackJobs.value = Array.isArray(rollbacks) ? rollbacks : []
}

const fetchEditorCompletions = async (keyword: string, suggestTables: boolean) => {
  const inst = selectedInstance.value
  if (!inst?.id) return []
  const dt = inst.db_type as string
  if (!['mysql', 'postgresql'].includes(dt)) return []
  const res = await dbManagerProApi.completion(inst.id, workbench.database || '', keyword, suggestTables)
  let items: any[] = Array.isArray(res.items) ? res.items : []
  if (!suggestTables) {
    const preset = getDbTypePreset(dt).sqlCompletion
    const seen = new Set(items.map((i) => String(i.label || '').toLowerCase()))
    for (const p of preset) {
      const k = p.label.toLowerCase()
      if (!seen.has(k)) {
        seen.add(k)
        items.push({ ...p, kind: 'keyword' })
      }
    }
  }
  return items
}

const selectInstance = async (row: any) => {
  selectedInstance.value = row
  selectedInstanceId.value = row.id
  await loadDatabaseOptions(row.id)
  workbench.database = row.default_database || databaseOptions.value[0] || ''
  const preset = getDbTypePreset(row.db_type)
  if (!workbench.sql.trim()) {
    workbench.sql = preset.defaultSql
  }
  await runDiagnosticsAction()
}

const handleInstanceChange = async (instanceId: number) => {
  const row = instances.value.find(item => item.id === instanceId)
  if (row) {
    await selectInstance(row)
  }
}

const testInstance = async (row: any) => {
  const res = await dbManagerProApi.testInstance(row.id)
  ElMessage.success(res.msg || '测试完成')
  await loadInstances()
}

const formatSqlAction = async () => {
  if (!workbench.sql.trim()) return
  const res = await dbManagerProApi.formatSql(workbench.sql)
  workbench.sql = res.formatted_sql || workbench.sql
}

const explainSqlAction = async () => {
  if (!selectedInstance.value) {
    ElMessage.warning('请先选择数据库实例')
    return
  }
  explainLoading.value = true
  try {
    explainResult.value = await dbManagerProApi.explainSql(selectedInstance.value.id, workbench.database, workbench.sql)
  } finally {
    explainLoading.value = false
  }
}

const reviewSqlAction = async () => {
  if (!selectedInstance.value) {
    ElMessage.warning('请先选择数据库实例')
    return
  }
  aiReviewLoading.value = true
  try {
    const res = (await dbManagerProApi.reviewSql(selectedInstance.value.id, workbench.database, workbench.sql)) as any
    aiReview.value = res.report
    if (aiReview.value) ElMessage.success('AI 分析完成')
  } catch {
    /* request interceptor */
  } finally {
    aiReviewLoading.value = false
  }
}

const executeSqlAction = async () => {
  if (!selectedInstance.value) {
    ElMessage.warning('请先选择数据库实例')
    return
  }
  executeLoading.value = true
  try {
    const res = (await dbManagerProApi.createJob({
      instance_id: selectedInstance.value.id,
      database: workbench.database,
      sql: workbench.sql,
      applicant_user_id: workbench.applicantUserId,
      approval_reason: workbench.approvalReason,
      cc_user_ids: workbench.ccUserIds,
      approval_flow: workbench.approvalFlow.filter(item => item.group_name)
    })) as any
    activeJob.value = res.job
    aiReview.value = res.report
    await loadJobs()
    if (activeJob.value?.id) {
      await loadJobDetail(activeJob.value)
    }
    const st = activeJob.value?.status
    if (st === 'failed') {
      ElMessage.error(activeJob.value?.error_message || '作业被拒绝或未执行')
      activePane.value = 'logs'
    } else if (st === 'waiting_approval') {
      ElMessage.warning('已提交审批，通过后才会执行 SQL；可在「作业记录」查看状态')
      activePane.value = 'jobs'
    } else {
      ElMessage.success('作业已排队执行（异步）；成功后下方会自动切换到结果集')
      activePane.value = jobResult.value.rows_json?.length ? 'result' : 'logs'
    }
    tunePollInterval()
  } catch {
    /* request interceptor */
  } finally {
    executeLoading.value = false
  }
}

const viewApproval = (row: any) => {
  router.push(`/database-manager/approvals/${row.id}`)
}

const loadJobDetail = async (row: any) => {
  const detail = await dbManagerProApi.getJobDetail(row.id)
  activeJob.value = detail
  jobLogs.value = await dbManagerProApi.getJobLogs(row.id)
  try {
    jobResult.value = await dbManagerProApi.getJobResult(row.id)
  } catch {
    jobResult.value = { columns_json: [], rows_json: [] }
  }
  const rows = jobResult.value.rows_json as unknown[] | undefined
  if (detail.status === 'running' || detail.status === 'queued') {
    activePane.value = 'logs'
  } else if (detail.status === 'success') {
    activePane.value = 'result'
  }
}

const cancelJobAction = async () => {
  if (!activeJob.value?.id) return
  await dbManagerProApi.cancelJob(activeJob.value.id)
  await loadJobDetail(activeJob.value)
  tunePollInterval()
  await loadAudit()
}

const pauseJobAction = async () => {
  if (!activeJob.value?.id) return
  await dbManagerProApi.pauseJob(activeJob.value.id)
  await loadJobDetail(activeJob.value)
  tunePollInterval()
}

const resumeJobAction = async () => {
  if (!activeJob.value?.id) return
  await dbManagerProApi.resumeJob(activeJob.value.id)
  await loadJobDetail(activeJob.value)
  tunePollInterval()
}

const approve = async (row: any) => {
  await dbManagerProApi.approve(row.id)
  ElMessage.success('审批已通过')
  await Promise.all([loadApprovals(), loadJobs()])
}

const reject = async (row: any) => {
  const { value } = await ElMessageBox.prompt('请输入拒绝原因', '拒绝审批', { confirmButtonText: '确认', cancelButtonText: '取消' })
  await dbManagerProApi.reject(row.id, value)
  ElMessage.success('审批已拒绝')
  await Promise.all([loadApprovals(), loadJobs()])
}

const remind = async (row: any) => {
  await dbManagerProApi.remindApproval(row.id)
  ElMessage.success('已发送催办')
  await loadJobDetail(activeJob.value || { id: row.job_id })
}

const openPolicyDrawer = () => {
  Object.assign(policyForm, {
    name: '',
    environment_scope: ['prod'],
    db_type_scope: selectedInstance.value ? [selectedInstance.value.db_type] : [],
    sql_type_scope: ['ALTER', 'DROP', 'TRUNCATE', 'UPDATE', 'DELETE', 'INSERT'],
    risk_scope: ['high', 'critical'],
    approval_flow: [{ group_name: '', sla_minutes: 60 }],
    sla_minutes: 60,
    enabled: true
  })
  policyDrawerVisible.value = true
}

const submitPolicy = async () => {
  await dbManagerProApi.createApprovalPolicy({ ...policyForm })
  policyDrawerVisible.value = false
  ElMessage.success('审批策略已创建')
  await loadPolicies()
}

const openAccessRuleDrawer = () => {
  Object.assign(accessRuleForm, {
    name: '',
    user_id: undefined,
    group_name: '',
    instance: selectedInstance.value?.id,
    database_pattern: workbench.database || '*',
    table_pattern: '*',
    sql_types: [],
    actions: ['view', 'query'],
    enabled: true
  })
  accessDrawerVisible.value = true
}

const submitAccessRule = async () => {
  await dbManagerProApi.createAccessRule({ ...accessRuleForm })
  accessDrawerVisible.value = false
  ElMessage.success('访问规则已创建')
  await loadAccessRules()
}

const openBackupPlanDrawer = (row?: any) => {
  Object.assign(backupPlanForm, {
    id: row?.id,
    instance: row?.instance || selectedInstance.value?.id,
    name: row?.name || '',
    backup_type: row?.backup_type || 'logical',
    schedule_expr: row?.schedule_expr || '0 2 * * *',
    retention_days: row?.retention_days || 7,
    storage_uri: row?.storage_uri || 'local://db_backups',
    storage_config: {
      bucket: row?.storage_config?.bucket || '',
      region: row?.storage_config?.region || '',
      endpoint: row?.storage_config?.endpoint || '',
      access_key: row?.storage_config?.access_key || '',
      secret_key: row?.storage_config?.secret_key || ''
    },
    compression_enabled: row?.compression_enabled ?? true,
    encryption_enabled: row?.encryption_enabled ?? false,
    enabled: row?.enabled ?? true
  })
  backupPlanDrawerVisible.value = true
}

const submitBackupPlan = async () => {
  const payload = { ...backupPlanForm, storage_config: { ...backupPlanForm.storage_config } }
  if (payload.id) {
    await dbManagerProApi.updateBackupPlan(payload.id, payload)
    ElMessage.success('备份计划已更新')
  } else {
    await dbManagerProApi.createBackupPlan(payload)
    ElMessage.success('备份计划已创建')
  }
  backupPlanDrawerVisible.value = false
  await loadBackupData()
}

const runBackup = async (row: any) => {
  await dbManagerProApi.runBackupPlan(row.id)
  ElMessage.success('已生成备份记录')
  await loadBackupData()
}

const openRestoreDrawer = () => {
  Object.assign(restoreForm, {
    instance: selectedInstance.value?.id,
    backup_record: backupRecords.value.find(item => item.instance === selectedInstance.value?.id || item.instance_id === selectedInstance.value?.id)?.id,
    restore_mode: 'backup',
    target_time: '',
    target_txn_id: ''
  })
  restoreDrawerVisible.value = true
}

const submitRestoreJob = async () => {
  await dbManagerProApi.createRestoreJob({
    instance: restoreForm.instance,
    backup_record: restoreForm.backup_record,
    restore_mode: restoreForm.restore_mode,
    target_time: restoreForm.target_time || undefined,
    target_txn_id: restoreForm.target_txn_id || undefined
  })
  restoreDrawerVisible.value = false
  ElMessage.success('恢复任务已创建')
  await loadBackupData()
}

const createRollbackFromSelectedAudit = async () => {
  const audit = auditLogs.value[0]
  if (!audit) return
  await dbManagerProApi.createRollbackJob({ source_audit: audit.id })
  ElMessage.success('已生成回滚任务')
  await loadBackupData()
}

const runRollback = async (row: any) => {
  await dbManagerProApi.executeRollbackJob(row.id)
  ElMessage.success('回滚任务已启动')
  await loadBackupData()
}

const runDiagnosticsAction = async () => {
  if (!selectedInstance.value?.id) return
  diagnosticsReport.value = await dbManagerProApi.getDiagnostics(selectedInstance.value.id)
}

const exportAuditAction = async () => {
  const blob = await dbManagerProApi.exportAudit()
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'db_audit_export.csv'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

const riskTagType = (risk: string) => {
  if (risk === 'low') return 'success'
  if (risk === 'medium') return 'warning'
  return 'danger'
}

const alertType = (decision: string) => {
  if (decision === 'allow') return 'success'
  if (decision === 'warn') return 'warning'
  return 'error'
}

const JOB_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  ai_reviewing: 'AI 预审中',
  waiting_confirm: '待确认',
  waiting_approval: '待审批',
  queued: '排队中',
  running: '执行中',
  paused: '已暂停',
  success: '执行成功',
  failed: '失败',
  cancelled: '已取消',
}

const jobStatusLabel = computed(() => {
  const st = activeJob.value?.status
  return (st && JOB_STATUS_LABELS[st]) || st || '—'
})

const jobStatusTagType = computed(() => {
  const st = activeJob.value?.status
  if (st === 'success') return 'success'
  if (st === 'failed' || st === 'cancelled') return 'danger'
  if (st === 'running' || st === 'queued') return 'primary'
  if (st === 'waiting_approval' || st === 'paused') return 'warning'
  return 'info'
})

const jobProgressUi = computed(() => {
  const j = activeJob.value
  if (!j?.id) {
    return { percent: 0, barStatus: undefined as undefined | 'success' | 'exception' | 'warning', striped: false, stripedFlow: false }
  }
  const st = j.status
  const raw = Number(j.progress_percent) || 0
  if (st === 'success') return { percent: 100, barStatus: 'success' as const, striped: false, stripedFlow: false }
  if (st === 'failed' || st === 'cancelled') {
    return { percent: Math.min(Math.max(raw, 8), 99), barStatus: 'exception' as const, striped: false, stripedFlow: false }
  }
  if (st === 'queued') return { percent: Math.max(raw, 12), barStatus: undefined, striped: true, stripedFlow: true }
  if (st === 'running') return { percent: Math.max(raw, 18), barStatus: undefined, striped: true, stripedFlow: true }
  if (st === 'waiting_approval' || st === 'paused') {
    return { percent: Math.min(raw || 6, 30), barStatus: 'warning' as const, striped: false, stripedFlow: false }
  }
  return { percent: Math.min(Math.max(raw, 5), 95), barStatus: undefined, striped: false, stripedFlow: false }
})

const jobPhaseHint = computed(() => {
  const j = activeJob.value
  if (!j?.id) return '执行 SQL 后将在此展示进度与各阶段说明'
  const st = j.status
  if (st === 'waiting_approval') return '等待审批；可通过下方「审批中心」催办，通过后作业才会排队执行。'
  if (st === 'queued') return '已在队列中，等待执行器（Celery Worker 或进程内线程）拉取任务…'
  if (st === 'paused') return '作业已暂停，恢复后将重新排队。'
  if (st === 'cancelled') return '作业已取消。'
  if (st === 'failed') return '执行失败，请查看下方红色错误信息与「执行日志」明细。'
  if (st === 'success') return '执行成功；有返回行时在「结果集」查看，仅 DML 时可能无表格数据。'
  if (st === 'running') {
    const p = Number(j.progress_percent) || 0
    if (p < 22) return '阶段 1/4：连接实例并初始化执行上下文…'
    if (p < 48) return '阶段 2/4：采集变更前快照（如适用）…'
    if (p < 82) return '阶段 3/4：在数据库中执行 SQL…'
    return '阶段 4/4：写入结果集、审计与收尾…'
  }
  const zh = st ? JOB_STATUS_LABELS[st] : ''
  return zh ? `当前：${zh}` : ''
})

const tunePollInterval = () => {
  const st = activeJob.value?.status || ''
  const busy = st === 'queued' || st === 'running'
  const want = busy ? 1500 : 5000
  if (pollTimer && want === pollIntervalDesiredMs) return
  pollIntervalDesiredMs = want
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(refreshAll, want)
}

const refreshAll = async () => {
  await Promise.all([loadInstances(), loadJobs(), loadApprovals(), loadAudit(), loadPolicies(), loadAccessRules(), loadBackupData(), loadUserRoleOptions(), loadApprovalApplicants()])
  if (activeJob.value?.id) {
    await loadJobDetail(activeJob.value)
  }
  tunePollInterval()
}

onMounted(async () => {
  await refreshAll()
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.dbm-pro-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.summary-card {
  border-radius: 12px;
}
.summary-label {
  color: #8c8c8c;
  font-size: 13px;
}
.summary-value {
  font-size: 28px;
  font-weight: 700;
  color: #1d2129;
  margin-top: 8px;
}
.summary-extra {
  margin-top: 8px;
  color: #1677ff;
  font-size: 12px;
}
.content-grid {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 12px;
  min-height: calc(100vh - 240px);
}
.instance-panel,
.workspace-card,
.analysis-card,
.result-card {
  border-radius: 12px;
}
.workspace-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.workspace-bottom {
  display: grid;
  grid-template-columns: 420px 1fr;
  gap: 12px;
}
.job-exec-panel {
  padding: 12px 12px 8px;
  margin-bottom: 8px;
  background: linear-gradient(180deg, #f8fafc 0%, #fff 100%);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.job-exec-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.job-exec-title {
  font-weight: 600;
  font-size: 15px;
}
.job-exec-trace {
  font-size: 12px;
  color: #64748b;
  font-family: ui-monospace, monospace;
}
.job-exec-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  margin: 8px 0 10px;
  font-size: 12px;
  color: #475569;
}
.job-exec-progress {
  margin-bottom: 8px;
}
.job-phase-hint {
  font-size: 13px;
  color: #334155;
  line-height: 1.5;
  margin-bottom: 8px;
}
.job-exec-err {
  margin-top: 4px;
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.workspace-title {
  font-size: 18px;
  font-weight: 600;
}
.workspace-subtitle {
  color: #8c8c8c;
  font-size: 12px;
  margin-top: 4px;
}
.toolbar-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.editor-topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.instance-input {
  width: 240px;
}
.database-input {
  width: 220px;
}
.applicant-input {
  width: 240px;
}
.sql-editor :deep(textarea) {
  font-family: Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
}
.log-stream {
  min-height: 240px;
  max-height: 260px;
  overflow: auto;
  background: #0f172a;
  color: #e5e7eb;
  border-radius: 10px;
  padding: 12px;
  font-family: Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}
.log-line {
  margin-bottom: 6px;
  line-height: 1.5;
}
.log-line.error {
  color: #f87171;
}
.log-line.warning {
  color: #fbbf24;
}
.log-line.success {
  color: #4ade80;
}
.diag-title {
  font-weight: 600;
  color: #1d2129;
}
.diag-desc {
  margin-top: 4px;
  color: #4b5563;
}
.flow-config {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.flow-row {
  display: grid;
  grid-template-columns: 1fr 140px 60px;
  gap: 8px;
  width: 100%;
}
.mb-12 {
  margin-bottom: 12px;
}
.mt-12 {
  margin-top: 12px;
}
</style>
