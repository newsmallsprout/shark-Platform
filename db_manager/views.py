from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from .models import DatabaseConnection
from .engines import DBEngineFactory
import re

def is_readonly(user):
    # Superusers and staff are not readonly
    if user.is_superuser or user.is_staff:
        return False
    # Check if user has explicit 'change' permission
    if user.has_perm('db_manager.change_databaseconnection'):
        return False
    return True

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def connection_list(request):
    if request.method == 'GET':
        conns = DatabaseConnection.objects.all().order_by('-created_at')
        data = []
        for c in conns:
            data.append({
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "host": c.host,
                "port": c.port,
                "user": c.user,
                "database": c.database
            })
        return Response(data)
    elif request.method == 'POST':
        if is_readonly(request.user):
            return Response({"error": "Permission Denied: Read-only account"}, status=403)
            
        data = request.data
        conn = DatabaseConnection.objects.create(
            name=data.get('name'),
            type=data.get('type'),
            host=data.get('host'),
            port=data.get('port', 3306),
            user=data.get('user'),
            password=data.get('password'),
            database=data.get('database'),
            extra_config=data.get('extra_config', {})
        )
        return Response({"id": conn.id, "msg": "Created"})

@api_view(['GET', 'DELETE', 'PUT'])
@permission_classes([IsAuthenticated])
def connection_detail(request, pk):
    conn = get_object_or_404(DatabaseConnection, pk=pk)
    if request.method == 'GET':
        return Response({
            "id": conn.id,
            "name": conn.name,
            "type": conn.type,
            "host": conn.host,
            "port": conn.port,
            "user": conn.user,
            "database": conn.database,
            "extra_config": conn.extra_config
        })
    elif request.method == 'DELETE':
        if is_readonly(request.user):
            return Response({"error": "Permission Denied: Read-only account"}, status=403)
        conn.delete()
        return Response({"msg": "Deleted"})
    elif request.method == 'PUT':
        if is_readonly(request.user):
            return Response({"error": "Permission Denied: Read-only account"}, status=403)
        data = request.data
        conn.name = data.get('name', conn.name)
        conn.host = data.get('host', conn.host)
        conn.port = data.get('port', conn.port)
        conn.user = data.get('user', conn.user)
        if 'password' in data:
            conn.password = data['password']
        conn.database = data.get('database', conn.database)
        conn.extra_config = data.get('extra_config', conn.extra_config)
        conn.save()
        return Response({"msg": "Updated"})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_connection(request):
    data = request.data
    conn = DatabaseConnection(
        type=data.get('type'),
        host=data.get('host'),
        port=data.get('port'),
        user=data.get('user'),
        password=data.get('password'),
        database=data.get('database'),
        extra_config=data.get('extra_config', {})
    )
    try:
        engine = DBEngineFactory.get_engine(conn)
        ok, msg = engine.test()
        return Response({"ok": ok, "msg": msg})
    except Exception as e:
        return Response({"ok": False, "msg": str(e)})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_saved_connection(request, pk):
    conn = get_object_or_404(DatabaseConnection, pk=pk)
    try:
        engine = DBEngineFactory.get_engine(conn)
        ok, msg = engine.test()
        return Response({"ok": ok, "msg": msg})
    except Exception as e:
        return Response({"ok": False, "msg": str(e)})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_structure(request, pk):
    conn = get_object_or_404(DatabaseConnection, pk=pk)
    try:
        engine = DBEngineFactory.get_engine(conn)
        tree = engine.get_structure()
        return Response(tree)
    except Exception as e:
        return Response({"error": str(e)}, status=400)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def execute_query(request, pk):
    conn = get_object_or_404(DatabaseConnection, pk=pk)
    db = request.data.get('db')
    target = request.data.get('target')
    params = request.data.get('params', {})
    
    # Permission Check for Read-Only Users
    if is_readonly(request.user):
        if conn.type == 'mysql':
            sql = params.get('sql', '').strip().upper()
            # Allow SELECT, SHOW, EXPLAIN, DESCRIBE
            # Block INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, etc.
            # Using a whitelist approach for safety
            allowed_prefixes = ('SELECT', 'SHOW', 'EXPLAIN', 'DESC', 'DESCRIBE')
            if sql and not sql.startswith(allowed_prefixes):
                 return Response({"error": "Read-only Access: Only SELECT queries are allowed."}, status=403)
                 
        elif conn.type == 'redis':
            command = params.get('command', '').strip().upper()
            if command:
                cmd_root = command.split()[0]
                # Whitelist of safe read commands
                safe_cmds = (
                    'GET', 'HGET', 'HGETALL', 'HMGET', 'LINDEX', 'LLEN', 'LRANGE', 
                    'SCARD', 'SISMEMBER', 'SMEMBERS', 'SRANDMEMBER', 'ZCARD', 'ZCOUNT', 
                    'ZRANGE', 'ZRANK', 'ZSCORE', 'TYPE', 'TTL', 'PTTL', 'EXISTS', 
                    'STRLEN', 'KEYS', 'SCAN', 'HSCAN', 'SSCAN', 'ZSCAN', 'INFO', 'DBSIZE',
                    'PING', 'ECHO'
                )
                if cmd_root not in safe_cmds:
                    return Response({"error": f"Read-only Access: Command '{cmd_root}' is not allowed."}, status=403)

    try:
        engine = DBEngineFactory.get_engine(conn)
        result = engine.query(db, target, params)
        return Response(result)
    except Exception as e:
        return Response({"error": str(e)}, status=400)
