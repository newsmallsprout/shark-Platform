MySQL → MongoDB 数据同步服务
一个面向生产环境的 MySQL 到 MongoDB 数据同步服务，支持：
全量快照同步（FullSync）
增量 Binlog 同步（CDC / Incremental Sync）
适用于需要把 MySQL 业务数据持续同步到 MongoDB，用于冷存储、快照、分析与审计等场景。

1. 背景与目标
在实际业务中，经常需要将 MySQL 中的业务数据持续同步到 MongoDB，用于：
冷数据存储
账务 / 资产快照
查询分析（OLAP / 风控）
历史留存 / 审计
本项目旨在提供一个：
可长期稳定运行
对大表友好
保证数值精度（金融级）
具备可观测性
可直接用于生产环境
的数据同步服务。
2. 核心能力
2.1 同步模式
A. 全量同步（FullSync）
按主键递增进行分段扫描（无 OFFSET）
MongoDB 采用批量写入（insert_many）
可处理 百万 / 千万级数据
实时输出进度 / 速度 / 百分比
FullSync 阶段可选择关闭 Mongo journaling，提升写入性能
B. 增量同步（Incremental Sync / CDC）
基于 MySQL Binlog（ROW 模式）
实时监听 Insert / Update / Delete 事件
持久化 Binlog 位点，支持重启续跑
与 FullSync 无缝衔接：FullSync 完成后自动进入增量
2.2 数据类型安全（金融级）
目标：不丢精度，不做 float 化。
MySQL 类型	MongoDB 存储方式	说明
DECIMAL	Decimal128	✅ 不丢精度
DATE	datetime（00:00:00）	统一成可计算时间类型
DATETIME / TIMESTAMP	原样保留	保持语义一致
其他	BSON 原生类型	按可映射类型写入
原则：❗不做 float 转换，避免精度问题。
2.3 MongoDB 支持能力
支持 ReplicaSet
显式认证方式：
authSource=admin
SCRAM-SHA-256
写入策略区分：
FullSync：高性能写入
IncSync：安全写入
2.4 稳定性与可靠性
任务配置持久化
Binlog 位点持久化
服务重启后自动恢复任务
单任务异常不影响整体服务
3. 系统架构
+----------------+        +------------------------+
|     MySQL      | -----> |   FullSync 全量同步     |
|   (InnoDB)     |        |  主键分段 + 批量写入    |
+----------------+        +------------------------+
        |                              |
        |                              v
        |                      +------------------------+
        +--------------------> |   Binlog 增量同步 CDC   |
                               |  ROW 监听 + 位点持久化   |
                               +------------------------+
                                              |
                                              v
                                   +----------------------+
                                   |       MongoDB         |
                                   |     (ReplicaSet)      |
                                   +----------------------+
4. 接口说明
4.1 启动同步任务
POST /tasks/start
{
  "task_id": "job_cold_account",
  "mysql_conf": {
    "host": "mysql.example.com",
    "port": 3306,
    "user": "sync_user",
    "password": "******",
    "database": "exchange_account"
  },
  "mongo_conf": {
    "user": "mongo_admin",
    "password": "******",
    "database": "cold_account",
    "replica_set": "prd_rs",
    "hosts": [
      "10.10.46.137:27017",
      "10.10.66.14:27017",
      "10.10.96.64:27017"
    ]
  },
  "table_map": {},
  "pk_field": "id",
  "progress_interval": 10
}
参数说明
task_id：任务唯一标识
table_map：
为空：自动发现数据库内所有基础表
非空：手动指定表映射
pk_field：全量同步所依赖的递增主键字段
progress_interval：进度日志输出间隔（秒）
4.2 停止同步任务
POST /tasks/stop/{task_id}
4.3 服务状态
GET /
5. 同步进度日志示例
[job_cold_account] Table start: account_spot_asset, total=2111477
[job_cold_account] Prog: t=account_spot_asset done=300000/2111477 14.2% sp=12800 row/s
[job_cold_account] Prog: t=account_spot_asset done=1200000/2111477 56.8% sp=14500 row/s
[job_cold_account] Table done: account_spot_asset, inserted=2111477
字段说明：
done / total：已同步 / 总行数
%：完成百分比
sp：同步速度（行/秒）
6. 性能表现（参考）
写入方式	同步速度
单条写入	200 ~ 500 行/秒
批量写入（1000）	8k ~ 20k 行/秒
批量 + 关闭 journaling	10k ~ 30k 行/秒
实际性能取决于 MongoDB 机器配置、索引数量、网络情况。
7. 设计原则
7.1 Insert-Only 设计
不在 Mongo 中做 update / delete
每次变更生成一条新文档
适合：
账务流水
资产快照
审计日志
冷数据分析
7.2 为什么不并行 FullSync
Mongo 批量写入已充分利用 IO
单线程更易维护
失败恢复更简单可靠
8. 运维说明
8.1 重启与恢复
服务重启后自动恢复任务
FullSync 完成后自动进入增量同步
如需重新全量同步：
rm state/<task_id>.json
8.2 索引建议（强烈推荐）
为保证 FullSync 性能：
FullSync 前删除非必要索引
FullSync 完成后重建索引
9. 已知限制
Insert-only（不支持 upsert）
依赖稳定的递增主键
MySQL Binlog 必须为 ROW 模式
不保证跨表事务一致性
10. 后续可扩展方向
FullSync ETA 预估
Prometheus /metrics
FullSync 按主键断点续传
自动索引管理
Schema 变更感知
11. 适用场景总结
✅ 冷数据同步
✅ 账务 / 资产类系统
✅ 历史数据留存
✅ 分析型 MongoDB 场景