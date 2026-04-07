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
  {
    path: '/admin',
    redirect: () => {
      window.location.href = '/admin/'
      return '/ai-ops'
    },
    meta: { title: 'Admin', hidden: true }
  },
  {
    path: '/',
    component: AppLayout,
    redirect: '/ai-ops',
    children: [
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
        path: 'database-manager',
        name: 'DatabaseManager',
        component: () => import('@/views/DatabaseManagerPro/Index.vue'),
        meta: { title: 'Database Manager', icon: 'Coin', viewPerm: 'view_db_manager' }
      },
      {
        path: 'database-manager/permissions',
        name: 'DatabaseManagerPermissions',
        component: () => import('@/views/DatabaseManagerPro/Permissions.vue'),
        meta: { title: 'Database Permissions', icon: 'Lock', viewPerm: 'manage_db_permissions' }
      },
      {
        path: 'database-manager/approvals/:id',
        name: 'DatabaseManagerApprovalDetail',
        component: () => import('@/views/DatabaseManagerPro/ApprovalDetail.vue'),
        meta: { title: 'Approval Detail', icon: 'Lock', viewPerm: 'approve_sql_execution', hidden: true }
      },
      {
        path: 'database-manager-legacy',
        name: 'DatabaseManagerLegacy',
        component: () => import('@/views/DatabaseManager/Index.vue'),
        meta: { title: 'Database Manager Legacy', hidden: true }
      },
      {
        path: 'ai-ops',
        name: 'AIOps',
        component: () => import('@/views/AIOps/Index.vue'),
        meta: { title: 'AI Fault Analysis', icon: 'Cpu' }
      },
      {
        path: 'schedules',
        name: 'Schedules',
        component: () => import('@/views/Schedules/Index.vue'),
        meta: { title: 'Schedules', icon: 'Calendar' }
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

  if (!systemStore.currentUser) {
    try {
      await systemStore.fetchCurrentUser()
    } catch {
      if (to.path !== '/login') return next('/login')
    }
  }

  const perm = (to.meta as any)?.viewPerm as string | undefined
  if (perm) {
    const hasAccess = systemStore.isAdmin || systemStore.hasPermission(perm)
    if (!hasAccess) {
      if (systemStore.hasPermission('view_tasks')) return next('/tasks')
      if (systemStore.hasPermission('view_inspection')) return next('/system')
      if (systemStore.hasPermission('view_db_manager')) return next('/database-manager')
      return next('/ai-ops')
    }
  }
  next()
})

export default router
