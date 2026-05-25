import pymysql
import redis
from redis.cluster import RedisCluster
from pymongo import MongoClient
import pika
import json
import urllib.request
import base64
import ssl
from bson import ObjectId
from datetime import datetime
from .models import DatabaseConnection

def mongo_json_default(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)

class DBEngineFactory:
    @staticmethod
    def get_engine(conn: DatabaseConnection):
        if conn.type == 'mysql':
            return MySQLEngine(conn)
        elif conn.type == 'redis':
            return RedisEngine(conn)
        elif conn.type == 'mongo':
            return MongoEngine(conn)
        elif conn.type == 'rabbitmq':
            return RabbitMQEngine(conn)
        else:
            raise ValueError(f"Unsupported database type: {conn.type}")

class BaseEngine:
    def __init__(self, conn: DatabaseConnection):
        self.conn = conn

    def test(self):
        raise NotImplementedError

    def get_structure(self):
        """Return tree: { db: [tables/collections] }"""
        raise NotImplementedError

    def query(self, db, target, query_params):
        """Return { headers: [], rows: [] }"""
        raise NotImplementedError

class MySQLEngine(BaseEngine):
    def _connect(self, db=None):
        connect_args = {
            "host": self.conn.host,
            "port": self.conn.port,
            "user": self.conn.user,
            "password": self.conn.password,
            "database": db or self.conn.database,
            "connect_timeout": 5,
            "read_timeout": 10,
            "write_timeout": 10,
            "cursorclass": pymysql.cursors.DictCursor
        }

        # Handle SSL Configuration
        extra = self.conn.extra_config or {}
        if extra.get('ssl'):
            ssl_conf = extra.get('ssl')
            # If ssl is just True, use a default permissive context
            if ssl_conf is True:
                connect_args['ssl'] = {'check_hostname': False}
            elif isinstance(ssl_conf, dict):
                # If user provided a dict, use it. 
                # Common keys: ca, cert, key, check_hostname, verify_mode
                # We need to map 'verify_mode' string to ssl constant if present
                if 'verify_mode' in ssl_conf and isinstance(ssl_conf['verify_mode'], str):
                    mode_str = ssl_conf['verify_mode'].upper()
                    if mode_str == 'CERT_NONE':
                        ssl_conf['verify_mode'] = ssl.CERT_NONE
                    elif mode_str == 'CERT_OPTIONAL':
                        ssl_conf['verify_mode'] = ssl.CERT_OPTIONAL
                    elif mode_str == 'CERT_REQUIRED':
                        ssl_conf['verify_mode'] = ssl.CERT_REQUIRED
                connect_args['ssl'] = ssl_conf
            
        return pymysql.connect(**connect_args)

    def test(self):
        try:
            c = self._connect()
            c.close()
            return True, "Connected successfully"
        except Exception as e:
            return False, str(e)

    def get_structure(self):
        tree = {}
        conn = self._connect()
        try:
            with conn.cursor() as c:
                # Query information_schema for detailed table info
                # Only select necessary columns for overview
                c.execute("""
                    SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_ROWS, DATA_LENGTH, ENGINE, CREATE_TIME, UPDATE_TIME
                    FROM information_schema.TABLES 
                    WHERE TABLE_SCHEMA NOT IN ('information_schema', 'performance_schema', 'sys', 'mysql')
                """)
                for row in c.fetchall():
                    db = row['TABLE_SCHEMA']
                    if db not in tree:
                        tree[db] = []
                    
                    # Format size
                    size = row['DATA_LENGTH'] or 0
                    if size > 1024 * 1024:
                        size_str = f"{size / (1024 * 1024):.2f} MB"
                    elif size > 1024:
                        size_str = f"{size / 1024:.2f} KB"
                    else:
                        size_str = f"{size} B"

                    tree[db].append({
                        "name": row['TABLE_NAME'],
                        "rows": row['TABLE_ROWS'] if row['TABLE_ROWS'] is not None else 0, # Ensure rows is not None
                        "size": size_str,
                        "engine": row['ENGINE'],
                        "created": row['CREATE_TIME'].strftime('%Y-%m-%d %H:%M:%S') if row['CREATE_TIME'] else '-',
                        "updated": row['UPDATE_TIME'].strftime('%Y-%m-%d %H:%M:%S') if row['UPDATE_TIME'] else '-'
                    })
        finally:
            conn.close()
        return tree

    def query(self, db, table, params):
        sql = params.get('sql')
        where = params.get('where')
        conn = self._connect(db)
        try:
            with conn.cursor() as c:
                if sql:
                    # Execute multiple statements
                    try:
                        # ... existing SQL execution logic ...
                        c.execute(sql)
                        
                        # Commit if it's a DML/DDL (Insert, Update, Delete, Create, Drop)
                        conn.commit()
                        
                        if c.description:
                            # It's a SELECT or similar returning rows
                            rows = c.fetchall()
                            rows = json.loads(json.dumps(rows, default=mongo_json_default))
                            headers = list(rows[0].keys()) if rows else ["Info"]
                            if not rows:
                                return {"headers": ["Info"], "rows": [{"Info": "Query executed successfully. No rows returned."}], "total": 0}
                            return {"headers": headers, "rows": rows, "total": len(rows)}
                        else:
                            # It's an INSERT/UPDATE/DELETE/DDL
                            msg = f"Query executed successfully. Affected rows: {c.rowcount}"
                            return {"headers": ["Info"], "rows": [{"Info": msg}], "total": 0}
                            
                    except Exception as e:
                        return {"headers": ["Error"], "rows": [{"Error": str(e)}], "total": 0}
                else:
                    page = int(params.get('page', 1))
                    page_size = int(params.get('pageSize', 100))
                    offset = (page - 1) * page_size
                    
                    # Optimization: Use approximate count from information_schema if no filter is applied
                    # This significantly speeds up loading large tables
                    total = 0
                    if not where:
                        try:
                            c.execute(f"""
                                SELECT TABLE_ROWS 
                                FROM information_schema.TABLES 
                                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                            """, (db, table))
                            res = c.fetchone()
                            if res:
                                total = res['TABLE_ROWS']
                        except:
                            # Fallback to COUNT(*) if information_schema query fails
                            pass
                    
                    # If total is still 0 or we have a where clause, do a real count
                    # Note: For very large tables with WHERE, this can still be slow. 
                    # We could implement a 'fast mode' flag from frontend to skip this if needed.
                    if total == 0 or where:
                        count_sql = f"SELECT COUNT(*) as cnt FROM `{table}`"
                        if where: count_sql += f" WHERE {where}"
                        c.execute(count_sql)
                        total = c.fetchone()['cnt']
                    
                    select_sql = f"SELECT * FROM `{table}`"
                    if where: select_sql += f" WHERE {where}"
                    select_sql += " LIMIT %s OFFSET %s"
                    
                    c.execute(select_sql, (page_size, offset))
                    rows = c.fetchall()
                    if not rows:
                        return {"headers": [], "rows": [], "total": total}
                    
                    rows = json.loads(json.dumps(rows, default=mongo_json_default))
                    headers = list(rows[0].keys())
                    return {"headers": headers, "rows": rows, "total": total}
        finally:
            conn.close()

class RedisEngine(BaseEngine):
    def _connect(self, db=0):
        mode = self.conn.extra_config.get('mode', 'standalone')
        
        if mode == 'cluster':
            nodes = []
            if ',' in self.conn.host:
                for hp in self.conn.host.split(','):
                    try:
                        h, p = hp.split(':')
                        nodes.append(redis.cluster.ClusterNode(h, int(p)))
                    except: pass
            else:
                nodes.append(redis.cluster.ClusterNode(self.conn.host, self.conn.port))
            
            # Pass username if provided (Redis 6+ ACL support)
            return RedisCluster(
                startup_nodes=nodes, 
                password=self.conn.password or None, 
                username=self.conn.user or None, # Added username support
                decode_responses=True
            )
        else:
            return redis.Redis(
                host=self.conn.host,
                port=self.conn.port,
                password=self.conn.password or None,
                username=self.conn.user or None, # Added username support
                db=db,
                socket_timeout=5,
                decode_responses=True
            )

    def test(self):
        try:
            r = self._connect()
            r.ping()
            r.close()
            return True, "Connected successfully"
        except Exception as e:
            return False, str(e)

    def get_structure(self):
        tree = {}
        r = self._connect()
        mode = self.conn.extra_config.get('mode', 'standalone')
        try:
            # 1. Determine DBs to show
            dbs = []
            if mode == 'cluster':
                dbs = ['db0']
            else:
                info = r.info('keyspace')
                for k in info.keys():
                    if k.startswith('db'):
                        dbs.append(k)
                if not dbs: dbs = ['db0']
            
            # 2. For each DB, scan keys to build "virtual folders"
            # This mimics Redis Commander's tree view (grouped by prefix)
            for db_key in dbs:
                db_idx = int(db_key.replace('db', '')) if db_key.startswith('db') else 0
                
                # Connect to specific DB if standalone
                if mode != 'cluster':
                    r.select(db_idx)
                
                # Get Stats
                try:
                    db_size = r.dbsize()
                    mem_info = r.info('memory')
                    used_mem = mem_info.get('used_memory_human', '-')
                except:
                    db_size = 0
                    used_mem = '-'

                # Scan a sample of keys (limit to avoid blocking)
                # We use a larger count to get a good representative sample
                cursor = '0'
                keys = []
                # Scan up to 10000 keys to build the structure
                for _ in range(10): 
                    cursor, partial = r.scan(cursor=cursor, count=1000)
                    keys.extend(partial)
                    if cursor == 0 or len(keys) >= 10000:
                        break
                
                # Group keys and Count
                groups = {}
                
                # Force flat mode for Redis as requested
                # Heuristic: If we scanned few keys and they don't look like they have many common prefixes, just show them flat
                # Or if the total sample is small, just show all keys.
                # User preference: "Don't want folders".
                # ALWAYS show flat for now unless overridden
                show_flat = True 
                
                for k in keys:
                    if not show_flat and ':' in k:
                        # Use the first part as a folder
                        prefix = k.split(':')[0]
                        group_name = f"{prefix}:*"
                    else:
                        group_name = k
                    
                    groups[group_name] = groups.get(group_name, 0) + 1
                
                # Ensure db_size is int
                if not isinstance(db_size, int): db_size = 0

                # If no keys found, add a placeholder
                if not groups:
                    # If we have db_size but scan found nothing (weird?), add Keys
                    if db_size > 0:
                        groups['Keys'] = db_size
                    else:
                        groups['Keys'] = 0
                
                # Convert to objects
                result_list = []
                
                for g, count in groups.items():
                    item = {
                        "name": g,
                        "rows": count,
                        "size": "-",
                        "engine": "Redis",
                        "created": "-",
                        "updated": "-"
                    }
                    
                    # If it's the generic 'Keys' placeholder or we only have one group, assume it's the whole DB
                    if g == 'Keys' and len(groups) == 1:
                        item['rows'] = db_size
                        item['size'] = used_mem
                    
                    result_list.append(item)
                
                # Sort: Folders (*) first, then others
                result_list.sort(key=lambda x: (0 if x['name'].endswith(':*') else 1, x['name']))
                
                tree[db_key] = result_list

        except Exception as e:
            # Fallback
            tree['db0'] = [{"name": "Keys", "rows": 0, "size": "-", "engine": "Redis"}]
        finally:
            r.close()
        return tree

    def query(self, db_name, table, params):
        command = params.get('command')
        db_idx = int(db_name.replace('db', ''))
        
        mode = self.conn.extra_config.get('mode', 'standalone')
        if mode == 'cluster': db_idx = 0
            
        r = self._connect(db_idx)
        try:
            if command:
                parts = command.split()
                if not parts: return {"headers": [], "rows": [], "total": 0}
                cmd = parts[0]
                args = parts[1:]
                res = r.execute_command(cmd, *args)
                return {
                    "headers": ["Result"], 
                    "rows": [{"Result": str(res)}], 
                    "total": 1
                }
            
            # Use table name as pattern if no explicit pattern provided
            # This supports clicking on "user:*" in the sidebar
            pattern = params.get('pattern')
            if not pattern and table and table != 'Keys':
                 pattern = table
            
            if not pattern: pattern = '*'

            # Pagination Logic
            page = int(params.get('page', 1))
            page_size = int(params.get('pageSize', 50))
            offset = (page - 1) * page_size
            
            # We need to scan enough keys to reach the offset + page_size
            # This is "deep pagination" and can be slow, but it's the only way without stateful cursors.
            target_count = offset + page_size
            
            cursor = '0'
            keys = []
            
            # Safety limit: don't scan forever. 
            # If user asks for page 1000, we might stop early.
            max_scan = target_count + 1000 
            
            while True:
                # Scan a batch
                cursor, partial = r.scan(cursor=cursor, match=pattern, count=1000)
                keys.extend(partial)
                
                # If we have enough keys or finished scanning
                if len(keys) >= max_scan or cursor == 0:
                    break
            
            # Slice the keys for the current page
            page_keys = keys[offset : offset + page_size]
            
            # Calculate total
            # If cursor is 0, we know the exact total (len(keys))
            # If cursor is not 0, we estimate total as "dbsize" or "keys found so far + more"
            if cursor == 0:
                total = len(keys)
            else:
                # If we haven't finished scanning, total must be larger than what we have
                # We can use dbsize as an upper bound estimate, or just say "many"
                try:
                    db_size = r.dbsize()
                    # Ensure total is at least enough to show the next page button
                    # If we found keys up to target_count, we need total > target_count
                    total = max(db_size, len(keys) + 100)
                except:
                    total = len(keys) + 100 # Fake it to allow next page
            
            rows = []
            for k in page_keys:
                try:
                    type_ = r.type(k)
                    val = "(large/complex)"
                    if type_ == 'string':
                        val = r.get(k)
                        if val and len(val) > 200: val = val[:200] + "..."
                    rows.append({"key": k, "type": type_, "value": val})
                except:
                    pass
                
            return {
                "headers": ["key", "type", "value"],
                "rows": rows,
                "total": total,
            }
        finally:
            r.close()

class MongoEngine(BaseEngine):
    def _connect(self):
        if '://' in self.conn.host:
             return MongoClient(self.conn.host, serverSelectionTimeoutMS=5000)
        
        # Build URI
        creds = ""
        if self.conn.user:
            creds = f"{self.conn.user}:{self.conn.password}@"
            
        default_db = self.conn.database if self.conn.database else 'admin'
        
        # Check if authSource is provided in extra_config
        auth_source = 'admin'
        if self.conn.extra_config and self.conn.extra_config.get('authSource'):
            auth_source = self.conn.extra_config['authSource']
            
        # Construct base URI
        uri = f"mongodb://{creds}{self.conn.host}:{self.conn.port}/{default_db}?authSource={auth_source}"
        
        # Optional: Add directConnection=true ONLY if user explicitly requested it or if we detect it might be needed.
        # But user said "I don't need forced". So we remove forced directConnection.
        # If user is connecting to a specific member of a replica set from outside (like via SSH tunnel or Docker port mapping),
        # they might actually NEED directConnection=true, but let's respect the "standard" behavior first.
        # If it fails, user can use URI string mode to customize.
        
        return MongoClient(uri, serverSelectionTimeoutMS=5000)

    def test(self):
        try:
            c = self._connect()
            c.server_info()
            c.close()
            return True, "Connected"
        except Exception as e:
            return False, str(e)

    def get_structure(self):
        tree = {}
        c = self._connect()
        try:
            # Check if connected
            c.admin.command('ping')
            
            dbs = c.list_database_names()
            for db in dbs:
                if db in ('admin', 'config', 'local'): continue
                
                # Optimized: Only list names first
                cols = c[db].list_collection_names()
                
                col_list = []
                # Very simple heuristic: if > 100 collections, skip detailed stats entirely
                # Just return names. This makes loading almost instant even for 10k collections.
                fast_mode = len(cols) > 50
                
                for col_name in cols:
                    if fast_mode:
                         col_list.append({
                            "name": col_name,
                            "rows": "-",
                            "size": "-",
                            "engine": "WiredTiger",
                            "created": "-", 
                            "updated": "-" 
                        })
                    else:
                        try:
                            # Full stats for small number of collections
                            stats = c[db].command("collStats", col_name)
                            size = stats.get('size', 0)
                            if size > 1024 * 1024:
                                size_str = f"{size / (1024 * 1024):.2f} MB"
                            elif size > 1024:
                                size_str = f"{size / 1024:.2f} KB"
                            else:
                                size_str = f"{size} B"
                                
                            col_list.append({
                                "name": col_name,
                                "rows": stats.get('count', 0),
                                "size": size_str,
                                "engine": "WiredTiger",
                                "created": "-", 
                                "updated": "-" 
                            })
                        except:
                             col_list.append({
                                "name": col_name,
                                "rows": "-",
                                "size": "-",
                                "engine": "-",
                                "created": "-",
                                "updated": "-"
                            })
                tree[db] = col_list
        finally:
            c.close()
        return tree

    def query(self, db, collection, params):
        filter_str = params.get('filter')
        c = self._connect()
        try:
            col = c[db][collection]
            
            # Common pagination params
            page = int(params.get('page', 1))
            page_size = int(params.get('pageSize', 50))
            skip = (page - 1) * page_size

            if filter_str:
                try:
                    query_filter = json.loads(filter_str)
                except:
                    return {"headers": ["Error"], "rows": [{"Error": "Invalid JSON"}], "total": 0}
                
                # Optimized: Add projection to limit fields if documents are huge?
                # For now, just limiting limit
                cursor = col.find(query_filter).skip(skip).limit(page_size)
                
                # Optimized: count_documents is slow with filter, use limit if possible or explain
                # For UX, we just say "50+" if we hit limit? 
                # Or use count_documents with limit.
                total = col.count_documents(query_filter)
            else:
                # Optimization: Sort by _id desc (LIFO) by default for better usability
                # Most users want to see the latest data first
                cursor = col.find().sort('_id', -1).skip(skip).limit(page_size)
                
                # Optimized: estimated_document_count is fast (metadata based)
                total = col.estimated_document_count()
            
            rows = []
            for doc in cursor:
                safe_doc = json.loads(json.dumps(doc, default=mongo_json_default))
                rows.append(safe_doc)
            
            headers = set()
            # Optimized: Only scan first 10 rows for headers to be faster
            for r in rows[:10]:
                headers.update(r.keys())
            
            # Ensure _id is always first
            header_list = sorted(list(headers))
            if '_id' in header_list:
                header_list.remove('_id')
                header_list.insert(0, '_id')
            
            return {"headers": header_list, "rows": rows, "total": total}
        finally:
            c.close()

class RabbitMQEngine(BaseEngine):
    def _connect(self):
        credentials = pika.PlainCredentials(self.conn.user, self.conn.password)
        vhost = self.conn.database or '/'
        params = pika.ConnectionParameters(
            host=self.conn.host,
            port=self.conn.port or 5672,
            virtual_host=vhost,
            credentials=credentials,
            socket_timeout=5
        )
        return pika.BlockingConnection(params)

    def test(self):
        try:
            c = self._connect()
            c.close()
            return True, "Connected successfully"
        except Exception as e:
            return False, str(e)
    
    def get_structure(self):
        # Try to fetch queue stats via Management API (http://host:15672/api/queues)
        # This provides "messages" (rows) and "memory" (size) for the charts.
        try:
            host = self.conn.host
            # Assume standard management port 15672. 
            # In a real app, we might want to allow configuring this port.
            mgmt_port = 15672
            
            # Handle vhost in URL
            path = "/api/queues"
            if self.conn.database and self.conn.database != '/':
                vhost_enc = urllib.parse.quote(self.conn.database, safe='')
                path = f"/api/queues/{vhost_enc}"
                
            url = f"http://{host}:{mgmt_port}{path}"
            
            req = urllib.request.Request(url)
            
            # Add Auth
            if self.conn.user and self.conn.password:
                auth_str = f"{self.conn.user}:{self.conn.password}"
                b64_auth = base64.b64encode(auth_str.encode()).decode()
                req.add_header("Authorization", f"Basic {b64_auth}")
            
            # 2 second timeout to avoid hanging if port is closed
            try:
                with urllib.request.urlopen(req, timeout=2) as response:
                    if response.status == 200:
                        data = json.loads(response.read())
                        queues = []
                        for q in data:
                            queues.append({
                                "name": q.get('name'),
                                "rows": q.get('messages', 0),
                                "size": f"{q.get('memory', 0)} B",
                                "engine": "RabbitMQ",
                                "created": "-",
                                "updated": "-"
                            })
                        
                        if not queues:
                            return {"Queues": []}
                            
                        return {"Queues": queues}
            except urllib.error.HTTPError as e:
                # Catch 401/403/etc explicitly and return friendly error item instead of letting view return 400
                return {"Queues": [{
                    "name": f"Error: {e.reason} (Auth/Permission)", 
                    "rows": 0, 
                    "size": "-", 
                    "engine": f"Status {e.code}"
                }]}
            except Exception as e:
                # Catch other URL errors
                 return {"Queues": [{
                    "name": "Note: Mgmt API Unreachable", 
                    "rows": 0, 
                    "size": "-", 
                    "engine": "Check Port 15672"
                }]}
        except Exception as e:
            # Catch all setup errors
            return {"Queues": [{
                "name": "Note: Mgmt API Error", 
                "rows": 0, 
                "size": "-", 
                "engine": str(e)
            }]}
        
    def query(self, db, target, params):
        queue_name = params.get('where') or target
        if queue_name == "(Enter Queue Name)" or queue_name == "(Enter Queue Name to Peek)" or not queue_name:
             return {"headers": ["Info"], "rows": [{"Info": "Please enter Queue Name in search box"}], "total": 0}
             
        conn = self._connect()
        try:
            channel = conn.channel()
            
            # Pagination
            page = int(params.get('page', 1))
            page_size = int(params.get('pageSize', 50))
            offset = (page - 1) * page_size
            
            # 1. Get True Total via Passive Declare
            # This allows accurate pagination numbers without fetching everything
            true_total = 0
            try:
                q_res = channel.queue_declare(queue=queue_name, passive=True)
                true_total = q_res.method.message_count
            except:
                pass

            rows = []
            fetched_count = 0
            
            # 2. Fetch Loop
            # Only fetch if we are within range
            if true_total == 0 or offset < true_total:
                # We iterate until we reach the limit (page_size + offset)
                # or the queue is empty.
                limit = offset + page_size
                
                # Safety break: don't loop too long
                loop_limit = limit + 10
                
                for _ in range(loop_limit): 
                    method, props, body = channel.basic_get(queue_name, auto_ack=False)
                    if method:
                        fetched_count += 1
                        
                        if fetched_count > offset and fetched_count <= limit:
                            # Optimized: Truncate body if too long for preview
                            body_str = body.decode('utf-8', 'ignore')
                            if len(body_str) > 1000: body_str = body_str[:1000] + "... (truncated)"
                            
                            rows.append({
                                "Exchange": method.exchange,
                                "RoutingKey": method.routing_key,
                                "Redelivered": method.redelivered,
                                "Body": body_str,
                                "Props": str(props)
                            })
                        
                        if fetched_count >= limit:
                            break
                    else:
                        break
            
            # 3. Final Total Calculation
            # If we got a true total from the server, use it (unless we fetched more, which shouldn't happen)
            # If true_total is 0 (failed to get), fallback to fetched count estimation
            if true_total > 0:
                total = true_total
            else:
                total = fetched_count
                if fetched_count >= (offset + page_size):
                     total = fetched_count + 100

            return {"headers": ["Exchange", "RoutingKey", "Body", "Redelivered", "Props"], "rows": rows, "total": total}
        except Exception as e:
            return {"headers": ["Error"], "rows": [{"Error": str(e)}], "total": 0}
        finally:
            conn.close()
