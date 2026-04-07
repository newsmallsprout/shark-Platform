<template>
  <div class="login">
    <div class="login-panel">
      <div class="login-brand">
        <span class="login-mark" />
        <div>
          <h1 class="login-title">AIOps Platform</h1>
          <p class="login-lede">控制中心登录</p>
        </div>
      </div>

      <el-form :model="form" class="login-form" @submit.prevent="handleLogin">
        <el-form-item class="fi">
          <el-input
            v-model="form.username"
            placeholder="用户名"
            size="large"
            :prefix-icon="User"
          />
        </el-form-item>
        <el-form-item class="fi">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            size="large"
            show-password
            :prefix-icon="Lock"
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          class="login-submit"
          :loading="loading"
          @click="handleLogin"
        >
          登录
        </el-button>
      </el-form>

      <p class="login-foot">LangGraph · Celery · SSE</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { User, Lock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'
import { useSystemStore } from '@/stores/system'

const router = useRouter()
const route = useRoute()
const systemStore = useSystemStore()
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
})

const handleLogin = async () => {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await request.post('/auth/login', form)
    ElMessage.success('登录成功')
    await systemStore.fetchCurrentUser()
    const next = route.query.next as string
    if (next && next.startsWith('/')) router.push(next)
    else router.push('/')
  } catch {
    /* interceptor */
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login {
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--aiops-bg);
  position: relative;
}

.login::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(ellipse 55% 40% at 50% -15%, rgba(250, 250, 250, 0.05), transparent 60%);
}

.login-panel {
  position: relative;
  width: 100%;
  max-width: 400px;
  padding: 40px 36px 32px;
  border-radius: 14px;
  border: 1px solid var(--aiops-border);
  background: var(--aiops-surface-2);
  box-shadow:
    0 32px 64px rgba(0, 0, 0, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
  animation: rise 0.55s cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.login-brand {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 32px;
}

.login-mark {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 8px;
  background: var(--aiops-accent-live);
  flex-shrink: 0;
}

.login-title {
  margin: 0;
  font-size: 1.375rem;
  font-weight: 600;
  letter-spacing: -0.03em;
  color: var(--aiops-text);
}

.login-lede {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--aiops-text-tertiary);
}

.login-form {
  width: 100%;
}

.login-form :deep(.fi) {
  margin-bottom: 16px;
}

.login-submit {
  width: 100%;
  margin-top: 8px;
  height: 44px;
  font-weight: 600;
  border-radius: 8px;
}

.login-submit:active {
  transform: scale(0.99);
}

.login-foot {
  margin: 28px 0 0;
  text-align: center;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--aiops-text-tertiary);
}
</style>
