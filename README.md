MySQL → MongoDB 数据同步服务（Full + Binlog CDC）
一个面向生产环境的 MySQL → MongoDB 数据同步服务，
支持 全量同步 + Binlog 增量同步（CDC）+ 数据版本化，
重点解决 DECIMAL 精度、安全性、可审计性 问题。
一、项目特性
✅ MySQL 全量数据同步
✅ MySQL Binlog（ROW）增量同步
✅ UPDATE 版本化（历史数据保留）
✅ DELETE 软删除（可恢复、可审计）
✅ Decimal 防崩溃 & 防精度丢失
✅ 同步任务配置与位点持久化
✅ FastAPI 管理接口
✅ Docker 生产部署友好
二、整体架构
MySQL（ROW Binlog）
        │
        ▼
 Sync Engine
 (Full + CDC)
        │
        ▼
 MongoDB
 ├── Base Collection（当前态）
 └── Version Collection（历史版本）
三、目录结构说明
mysql_to_mongo/
├── app/
│   ├── main.py                  # FastAPI 入口
│   ├── api/                     # 同步任务 API
│   ├── core/
│   │   ├── config_store.py      # 任务配置持久化
│   │   ├── state_store.py       # Binlog 位点持久化
│   │   └── logging.py
│   └── sync/
│       ├── worker.py            # 同步主流程
│       ├── task_manager.py      # 任务生命周期管理
│       ├── mysql_introspector.py
│       ├── mongo_writer.py
│       ├── flush_buffer.py
│       └── convert.py           # 【数据转换核心】
├── Dockerfile
├── requirements.txt
└── README.md
四、数据转换说明（重点）
4.1 Decimal 处理（防崩溃 & 防精度丢失）
背景问题
MySQL 中的 DECIMAL 类型在同步过程中会经历如下转换链路：
MySQL DECIMAL → Python Decimal → MongoDB Decimal128
在实际运行中，Python Decimal 在以下场景非常容易直接抛异常并导致任务崩溃：
精度不一致
scale 不固定
无法 quantize
科学计数法参与运算
而 MongoDB 对高精度数值必须使用 Decimal128，否则会出现精度丢失或类型不兼容问题。
本项目的统一处理策略（核心）
✅ 统一规则
MySQL DECIMAL → Python Decimal
所有 Decimal 强制 quantize
使用 ROUND_DOWN 进行截断
再统一转换为 MongoDB Decimal128
额外保留字符串字段（xxx_str）用于对账
代码位置
app/sync/convert.py
关键实现逻辑（简化说明）
dq = obj.quantize(self.DEC_Q, rounding=ROUND_DOWN)
return Decimal128(dq)
DEC_Q 由统一的 scale 生成
所有 Decimal 先规整精度，再入库
彻底避免 decimal.InvalidOperation 导致任务直接 CRASH
设计收益
✅ 防止同步任务因 Decimal 精度问题崩溃
✅ MongoDB 数值精度稳定
✅ 可通过 xxx_str 字段进行人工 / 程序化对账
✅ 适用于金融、账务、审计等高精度场景
五、数据写入规则
5.1 INSERT
写入 Base Collection
主键字段可配置是否作为 MongoDB 的 _id
支持 upsert 行为，避免重复写入
5.2 UPDATE（版本化）
UPDATE 操作支持版本化存储，用于审计与回溯。
行为说明
Base Collection：可配置为
覆盖（镜像模式）
保留原值（审计模式）
Version Collection：每次 UPDATE 都新增一条版本记录
版本数据示例
{
  "_id": "1001_20250101123000",
  "ref_id": 1001,
  "version": 3,
  "data": {
    "balance": "1200.00"
  },
  "updated_at": "2025-01-01T12:30:00"
}
5.3 DELETE（软删除）
❌ 不进行物理删除
✅ 标记删除状态字段（如 deleted / deleted_at）
✅ 历史数据完整保留
✅ 支持审计、回滚、对账
六、任务持久化与自动恢复
6.1 配置持久化
同步任务配置写入磁盘目录：
/app/configs
6.2 位点持久化
MySQL Binlog 位点持久化保存：
/app/state
保存内容包括：
binlog file
binlog position
6.3 服务重启行为
服务启动时自动加载所有配置
自动恢复同步任务
从上次 Binlog 位点继续同步
不会重复消费历史数据
七、接口说明
7.1 启动任务
POST /tasks/start
7.2 停止任务
POST /tasks/stop/{task_id}
7.3 Swagger 文档
http://localhost:8000/docs
八、Docker 部署说明
8.1 构建镜像
docker build -t mysql-to-mongo .
8.2 生产运行（推荐）
docker run -d \
  --name mysql-to-mongo \
  -p 8000:8000 \
  -e PYTHONUNBUFFERED=1 \
  -v /opt/mysql-to-mongo/configs:/app/configs \
  -v /opt/mysql-to-mongo/state:/app/state \
  --restart unless-stopped \
  mysql-to-mongo
九、总结
本项目是一个生产级 MySQL → MongoDB 同步服务，重点解决：
Binlog 增量同步
Decimal 精度与稳定性
UPDATE 版本化
DELETE 软删除
任务与位点持久化
适用于：
审计系统
风控系统
历史回溯
MongoDB 查询加速场景