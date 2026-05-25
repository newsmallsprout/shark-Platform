export interface Connection {
  id: string
  type: 'mysql' | 'mongo'
  host: string
  port: number | string
  user: string
  password?: string
  database?: string
  auth_source?: string
  hosts?: string // for mongo replica set
  replica_set?: string
}
