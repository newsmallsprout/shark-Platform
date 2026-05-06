import axios, { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'

class Request {
  private instance: AxiosInstance
  
  constructor() {
    this.instance = axios.create({
      baseURL: '/api',
      timeout: 30000, // Increase global timeout to 30s
      headers: {
        'Content-Type': 'application/json'
      }
    })
    
    this.setupInterceptors()
  }
  
  private setupInterceptors() {
    // Request interceptor
    this.instance.interceptors.request.use(
      (config) => {
        // CSRF Token for Django
        const csrfToken = this.getCookie('csrftoken')
        if (csrfToken) {
          config.headers['X-CSRFToken'] = csrfToken
        }
        return config
      },
      (error) => Promise.reject(error)
    )
    
    // Response interceptor
    this.instance.interceptors.response.use(
      (response: AxiosResponse) => {
        return response.data
      },
      (error) => {
        // Handle Session Timeout (401 or 403 when session expired)
        // Check for "Authentication credentials were not provided." (case sensitive in DRF)
        const detail = error.response?.data?.detail
        if (
            error.response?.status === 401 || 
            (error.response?.status === 403 && (typeof detail === 'string' && detail.toLowerCase().includes('authentication')))
        ) {
          // Prevent multiple redirects or alerts if many requests fail at once
          if (!window.location.pathname.startsWith('/login')) {
              ElMessage.error('Session expired. Please login again.')
              // Use window.location.replace to prevent back-button loops
              window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname)
          }
          return Promise.reject(error)
        }

        // Silently ignore 401/404 for /api/me during initial load
        const isMeError = error.config?.url?.includes('/me')
        if (isMeError && (error.response?.status === 401 || error.response?.status === 404)) {
          return Promise.reject(error)
        }

        const msg = error.response?.data?.detail || error.response?.data?.error || error.message || 'Request failed'
        ElMessage.error(msg)
        return Promise.reject(error)
      }
    )
  }

  private getCookie(name: string): string | null {
    let cookieValue = null
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';')
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim()
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1))
          break
        }
      }
    }
    return cookieValue
  }
  
  public get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.get(url, config)
  }
  
  public post<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.post(url, data, config)
  }
  
  public put<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.put(url, data, config)
  }
  
  public delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.delete(url, config)
  }

  public patch<T>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> {
    return this.instance.patch(url, data, config)
  }
}

export default new Request()
