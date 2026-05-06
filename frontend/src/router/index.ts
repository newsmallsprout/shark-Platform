import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
import AppLayout from '@/components/Layout/AppLayout.vue'
import { useSystemStore } from '@/stores/system'

const routes: Array<RouteRecordRaw> = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: 'Login', hidden: true }
  },
  // Django admin: redirect /admin to /admin/ so backend is hit (or user goes to Django admin)
  {
    path: '/admin',
    redirect: () => {
      window.location.href = '/admin/'
      return '/dashboard'
    },
    meta: { title: 'Admin', hidden: true }
  },
  {
    path: '/',
    component: AppLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard/Index.vue'),
        meta: { title: 'Traffic Dashboard', icon: 'DataLine', viewPerm: 'view_dashboard' }
      },
      {
        path: 'tasks',
        name: 'Tasks',
        component: () => import('@/views/Tasks/Index.vue'),
        meta: { title: 'Tasks', icon: 'List', viewPerm: 'view_tasks' }
      },
      {
        path: 'tasks/create',
        name: 'CreateTask',
        component: () => import('@/views/Tasks/Create.vue'),
        meta: { title: 'Create Task', hidden: true }
      },
      {
        path: 'tasks/logs/:id',
        name: 'TaskLogs',
        component: () => import('@/views/Tasks/Logs.vue'),
        meta: { title: 'Task Logs', hidden: true }
      },
      {
        path: 'connections',
        name: 'Connections',
        component: () => import('@/views/Connections/Index.vue'),
        meta: { title: 'Connections', icon: 'Link', viewPerm: 'view_tasks' }
      },
      {
        path: 'logs',
        name: 'Logs',
        component: () => import('@/views/LogMonitor/Index.vue'),
        meta: { title: 'Log Monitor', icon: 'Monitor', viewPerm: 'view_logs' }
      },
      {
        path: 'schedules',
        name: 'Schedules',
        component: () => import('@/views/Schedules/Index.vue'),
        meta: { title: 'Schedules', icon: 'Calendar' }
      },
      {
        path: 'system/tickets',
        name: 'SystemOpsTickets',
        component: () => import('@/views/System/OpsTickets.vue'),
        meta: { title: 'System Ops Tickets', icon: 'Tickets', viewPerm: 'view_inspection' }
      },
      {
        path: 'system',
        name: 'System',
        component: () => import('@/views/System/Index.vue'),
        meta: { title: 'System', icon: 'Setting', viewPerm: 'view_inspection' }
      },
      {
        path: 'permissions',
        name: 'Permissions',
        component: () => import('@/views/Permissions/Index.vue'),
        meta: { title: 'Permissions', icon: 'Lock' }
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

router.beforeEach(async (to, from, next) => {
  const systemStore = useSystemStore()
  
  // 1. Ensure user info is loaded
  if (!systemStore.currentUser) {
    try {
      await systemStore.fetchCurrentUser()
    } catch {
      // If fetch fails and we are not going to login, redirect
      if (to.path !== '/login') return next('/login')
    }
  }

  // 2. Permission Check
  const perm = (to.meta as any)?.viewPerm as string | undefined
  if (perm) {
    const hasAccess = systemStore.isAdmin || systemStore.hasPermission(perm)
    if (!hasAccess) {
      // Prevent infinite loop: if we are already targeting the fallback route
      if (to.path === '/logs' && !systemStore.hasPermission('view_logs')) {
        return next('/login')
      }
      
      // Intelligent fallback
      if (systemStore.hasPermission('view_logs')) return next('/logs')
      if (systemStore.hasPermission('view_tasks')) return next('/tasks')
      if (systemStore.hasPermission('view_inspection')) return next('/system')
      if (systemStore.hasPermission('view_dashboard')) return next('/dashboard')
      
      return next('/dashboard')
    }
  }
  next()
})

export default router
