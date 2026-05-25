import request from '@/utils/request'

export interface DBConnection {
  id?: string
  name: string
  type: 'mysql' | 'redis' | 'mongo' | 'rabbitmq'
  host: string
  port: number
  user?: string
  password?: string
  database?: string
  extra_config?: any
}

export const dbApi = {
  listConnections() {
    return request.get('db/connections/')
  },
  
  createConnection(data: DBConnection) {
    return request.post('db/connections/', data)
  },
  
  updateConnection(id: string, data: DBConnection) {
    return request.put(`db/connections/${id}/`, data)
  },
  
  deleteConnection(id: string) {
    return request.delete(`db/connections/${id}/`)
  },
  
  testConnection(data: DBConnection) {
    return request.post('db/test/', data)
  },
  
  getStructure(id: string) {
    return request.get(`db/${id}/structure/`)
  },
  
  query(connId: string, db: string, target: string, params: any) {
    return request.post(`db/${connId}/query/`, {
      db,
      target,
      params
    })
  }
}
