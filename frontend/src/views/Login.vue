<template>
  <div class="login-container">
    <div class="login-card l5-glass">
      <div class="brand">
        <div class="mono-badge">L5</div>
        <h1 class="title">shark-aiops</h1>
        <p class="subtitle">Control plane access</p>
      </div>

      <el-form :model="form" class="login-form" @submit.prevent="handleLogin">
        <el-form-item>
          <el-input
            v-model="form.username"
            placeholder="Username"
            size="large"
            :prefix-icon="User"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="Password"
            size="large"
            show-password
            :prefix-icon="Lock"
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          class="login-btn"
          :loading="loading"
          @click="handleLogin"
        >
          Authenticate
        </el-button>
      </el-form>

      <div class="footer">Distributed edge · LangGraph center brain</div>
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
.login-container {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 24px;
  background:
    radial-gradient(ellipse 80% 50% at 50% -20%, rgba(14, 165, 233, 0.12), transparent),
    radial-gradient(ellipse 60% 40% at 100% 100%, rgba(16, 185, 129, 0.08), transparent),
    #050505;
}

.login-card {
  width: 100%;
  max-width: 420px;
  padding: 40px 36px 32px;
}

.brand {
  text-align: center;
  margin-bottom: 28px;
}

.mono-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 12px;
  font-family: var(--l5-font-mono);
  font-weight: 800;
  font-size: 18px;
  color: #0ea5e9;
  border: 1px solid rgba(14, 165, 233, 0.35);
  margin-bottom: 16px;
  box-shadow: 0 0 20px rgba(14, 165, 233, 0.15);
}

.title {
  margin: 0;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.06em;
  color: #fafafa;
}

.subtitle {
  margin: 8px 0 0;
  font-size: 13px;
  color: #737373;
}

.login-form {
  width: 100%;
}

.login-btn {
  width: 100%;
  margin-top: 4px;
  font-weight: 600;
  --el-button-bg-color: #0ea5e9;
  --el-button-border-color: #0ea5e9;
}

.footer {
  margin-top: 28px;
  text-align: center;
  font-size: 11px;
  color: #525252;
  letter-spacing: 0.04em;
}
</style>
