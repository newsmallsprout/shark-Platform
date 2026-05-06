<template>
  <div class="approval-detail-page">
    <el-card shadow="never">
      <template #header>
        <div class="page-header">
          <div>
            <div class="page-title">审批工单详情</div>
            <div class="page-subtitle">审批链、抄送人、申请原因与 SQL 上下文</div>
          </div>
          <el-button @click="router.back()">返回</el-button>
        </div>
      </template>

      <el-descriptions v-if="detail" :column="2" border>
        <el-descriptions-item label="工单 ID">{{ detail.id }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
        <el-descriptions-item label="申请人">{{ detail.applicant }}</el-descriptions-item>
        <el-descriptions-item label="超时">{{ detail.overdue ? '是' : '否' }}</el-descriptions-item>
        <el-descriptions-item label="申请原因" :span="2">{{ detail.reason || '-' }}</el-descriptions-item>
        <el-descriptions-item label="抄送人" :span="2">{{ (detail.cc_users || []).map((item: any) => item.username).join('、') || '-' }}</el-descriptions-item>
        <el-descriptions-item label="执行策略" :span="2">{{ detail.request_payload?.policy_name || detail.request_payload?.matched_approval_policy || '-' }}</el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">审批链</el-divider>
      <el-steps :active="detail?.current_node || 1" finish-status="success">
        <el-step v-for="item in detail?.steps || []" :key="item.step_no" :title="`节点 ${item.step_no}`" :description="`${item.approver_role || '-'} / ${item.action}`" />
      </el-steps>

      <el-divider content-position="left">SQL 作业</el-divider>
      <el-card v-if="detail?.job" shadow="never" class="inner-card">
        <div class="sql-meta">
          <el-tag>{{ detail.job.sql_type }}</el-tag>
          <el-tag type="warning">{{ detail.job.execute_mode }}</el-tag>
          <el-tag type="info">{{ detail.job.database_name || '-' }}</el-tag>
        </div>
        <pre class="sql-content">{{ detail.job.sql_text }}</pre>
      </el-card>

      <el-divider content-position="left">SQL 规则预审</el-divider>
      <el-descriptions v-if="detail?.ai_review" :column="1" border>
        <el-descriptions-item label="决策">{{ detail.ai_review.decision || '-' }}</el-descriptions-item>
        <el-descriptions-item label="摘要">{{ detail.ai_review.sql_summary || '-' }}</el-descriptions-item>
        <el-descriptions-item label="优化建议">{{ (detail.ai_review.optimization_suggestions || []).join('；') || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { dbManagerProApi } from '@/api/db_manager_pro'

const route = useRoute()
const router = useRouter()
const detail = ref<any>(null)

onMounted(async () => {
  detail.value = await dbManagerProApi.getApprovalDetail(Number(route.params.id))
})
</script>

<style scoped>
.approval-detail-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.page-title {
  font-size: 18px;
  font-weight: 600;
  color: #1d2129;
}
.page-subtitle {
  margin-top: 4px;
  color: #8c8c8c;
  font-size: 12px;
}
.inner-card {
  margin-top: 12px;
}
.sql-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.sql-content {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  background: #0f172a;
  color: #e5e7eb;
  padding: 12px;
  border-radius: 10px;
}
</style>
