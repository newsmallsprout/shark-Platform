// ============================================================
// src/stores/task-store.ts — 任务全局状态
// ============================================================

import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type { Task, TaskStatus, TaskMode, Platform, CreateTaskPayload } from "@/types/task";
import { getTasks, getTaskById, createTask, updateTask, deleteTask } from "@/lib/api/tasks";

export interface TaskFilters {
  search: string;
  status: TaskStatus | "all";
  platform: Platform | "all";
  mode: TaskMode | "all";
  page: number;
  pageSize: number;
}

const DEFAULT_FILTERS: TaskFilters = {
  search: "", status: "all", platform: "all", mode: "all", page: 1, pageSize: 20,
};

interface TaskStore {
  tasks: Task[];
  total: number;
  currentTask: Task | null;
  filters: TaskFilters;
  isLoading: boolean;
  isCreating: boolean;

  setFilters: (partial: Partial<TaskFilters>) => void;
  resetFilters: () => void;
  fetchTasks: () => Promise<void>;
  fetchTaskById: (id: string) => Promise<void>;
  addTask: (payload: CreateTaskPayload) => Promise<Task>;
  editTask: (id: string, payload: Partial<Task>) => Promise<void>;
  removeTask: (id: string) => Promise<void>;
  startTask: (id: string) => Promise<void>;
  cancelTask: (id: string) => Promise<void>;
}

export const useTaskStore = create<TaskStore>()(
  devtools(
    (set, get) => ({
      tasks: [], total: 0, currentTask: null,
      filters: { ...DEFAULT_FILTERS },
      isLoading: false, isCreating: false,

      setFilters: (partial) => {
        const filters = { ...get().filters, ...partial, page: partial.page ?? 1 };
        set({ filters });
        get().fetchTasks();
      },
      resetFilters: () => {
        set({ filters: { ...DEFAULT_FILTERS } });
        get().fetchTasks();
      },

      fetchTasks: async () => {
        set({ isLoading: true });
        try {
          const { filters } = get();
          const params: Record<string, unknown> = { page: filters.page, page_size: filters.pageSize };
          if (filters.search) params.search = filters.search;
          if (filters.status !== "all") params.status = filters.status;
          if (filters.platform !== "all") params.platform = filters.platform;
          if (filters.mode !== "all") params.mode = filters.mode;
          const result = await getTasks(params);
          set({ tasks: result.tasks, total: result.total });
        } finally { set({ isLoading: false }); }
      },

      fetchTaskById: async (id) => {
        const task = await getTaskById(id);
        set({ currentTask: task });
      },

      addTask: async (payload) => {
        set({ isCreating: true });
        try {
          const task = await createTask(payload);
          set((s) => ({ tasks: [task, ...s.tasks], total: s.total + 1 }));
          return task;
        } finally { set({ isCreating: false }); }
      },

      editTask: async (id, payload) => {
        const updated = await updateTask(id, payload as Record<string, unknown>);
        set((s) => ({
          tasks: s.tasks.map((t) => (t.id === id ? updated : t)),
          currentTask: s.currentTask?.id === id ? updated : s.currentTask,
        }));
      },

      removeTask: async (id) => {
        await deleteTask(id);
        set((s) => ({
          tasks: s.tasks.filter((t) => t.id !== id), total: s.total - 1,
          currentTask: s.currentTask?.id === id ? null : s.currentTask,
        }));
      },

      startTask: async (id) => {
        await get().editTask(id, { status: "running" });
      },
      cancelTask: async (id) => {
        await get().editTask(id, { status: "cancelled" });
      },
    }),
    { name: "task-store" }
  )
);
