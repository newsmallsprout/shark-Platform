import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import request from '@/utils/request'

export const useSystemStore = defineStore('system', () => {
  const currentUser = ref<Record<string, unknown> | null>(null)

  const fetchCurrentUser = async () => {
    try {
      currentUser.value = (await request.get('/me')) as Record<string, unknown>
    } catch {
      currentUser.value = null
    }
  }

  const isAdmin = computed(
    () =>
      Boolean(currentUser.value?.is_superuser) ||
      Boolean((currentUser.value?.groups as string[] | undefined)?.includes('Admin')),
  )

  const hasPermission = (perm: string) => {
    if (!currentUser.value) return false
    if (currentUser.value.is_superuser) return true
    const perms = currentUser.value.permissions as string[] | undefined
    if (perms?.includes('all')) return true
    return Boolean(perms?.includes(perm))
  }

  return {
    currentUser,
    isAdmin,
    hasPermission,
    fetchCurrentUser,
  }
})
