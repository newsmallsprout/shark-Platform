import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
import { useSystemStore } from '@/stores/system'

const routes: Array<RouteRecordRaw> = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: 'Login', hidden: true },
  },
  {
    path: '/admin',
    redirect: () => {
      window.location.href = '/admin/'
      return '/'
    },
    meta: { hidden: true },
  },
  {
    path: '/',
    name: 'AIOps',
    component: () => import('@/views/AIOps/Index.vue'),
    meta: { title: 'L5 AIOps' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

router.beforeEach(async (to, _from, next) => {
  const systemStore = useSystemStore()
  if (!systemStore.currentUser) {
    try {
      await systemStore.fetchCurrentUser()
    } catch {
      /* handled below */
    }
  }
  if (!systemStore.currentUser && to.path !== '/login') {
    return next('/login')
  }
  if (systemStore.currentUser && to.path === '/login') {
    return next('/')
  }
  next()
})

export default router
