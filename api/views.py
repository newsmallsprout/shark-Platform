from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser, BasePermission, AllowAny
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth import authenticate, login, logout
from django.contrib.contenttypes.models import ContentType
import psutil
from inspection.models import InspectionConfig, InspectionReport
from tasks.models import SyncTask
from monitor.models import MonitorTask
import requests
import datetime

# --- Auth ---

@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    username = request.data.get('username')
    password = request.data.get('password')
    user = authenticate(request, username=username, password=password)
    if user is not None:
        login(request, user)
        return Response({"msg": "Login successful", "username": user.username})
    else:
        return Response({"error": "Invalid credentials"}, status=401)

@api_view(['POST'])
def logout_view(request):
    logout(request)
    return Response({"msg": "Logged out"})

# Custom Permission Class
class HasRolePermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if 'users' in request.path or 'roles' in request.path:
            return user.is_staff or user.groups.filter(name='Admin').exists()
        perms = set()
        for group in user.groups.all().prefetch_related('permissions'):
            for p in group.permissions.all():
                perms.add(p.codename)
        path = request.path
        method = request.method
        def has(c):
            return c in perms
        if '/monitor/logs' in path:
            return has('view_logs')
        if '/monitor/tasks' in path:
            if method == 'GET':
                return has('view_logs') or has('manage_log_monitor')
            return has('manage_log_monitor')
        if '/tasks/' in path:
            if method == 'GET':
                return has('view_tasks')
            return has('manage_tasks')
        if '/api/logs/' in path:
            return has('view_logs')
        if '/api/k8s/' in path:
            return has('view_logs')
        if '/deploy/' in path:
            if '/deploy/servers' in path:
                if method == 'GET':
                    return has('view_deploy')
                return has('manage_deploy')
            if '/deploy/run' in path or '/deploy/execute' in path:
                return has('manage_deploy')
            if '/deploy/plans' in path:
                return has('view_deploy')
        if '/inspection/' in path:
            if '/inspection/run' in path:
                return has('run_inspection')
            if '/inspection/config' in path:
                if method == 'GET':
                    return has('view_inspection')
                return has('run_inspection')
            if '/inspection/reports' in path:
                return has('view_inspection')
        return True


def _custom_permission_content_type():
    ct, _ = ContentType.objects.get_or_create(app_label='api', model='custom_permission')
    return ct


def _ensure_custom_permissions():
    ct = _custom_permission_content_type()
    perms = [
        {"codename": "view_dashboard", "name": "View Dashboard"},
        {"codename": "view_tasks", "name": "View Sync Tasks"},
        {"codename": "manage_tasks", "name": "Manage Sync Tasks"},
        {"codename": "view_logs", "name": "View Logs"},
        {"codename": "manage_log_monitor", "name": "Manage Log Monitor"},
        {"codename": "view_inspection", "name": "View Inspection"},
        {"codename": "run_inspection", "name": "Run Inspection"},
        {"codename": "view_deploy", "name": "View Deployments"},
        {"codename": "manage_deploy", "name": "Manage Deployments"},
        {"codename": "manage_users", "name": "Manage Users & Roles"},
    ]
    for p in perms:
        obj, created = Permission.objects.get_or_create(
            content_type=ct,
            codename=p["codename"],
            defaults={"name": p["name"]},
        )
        if not created and obj.name != p["name"]:
            obj.name = p["name"]
            obj.save()
    return perms

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def system_stats(request):
    # 1. Resource Stats (Real)
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # 2. Real System Health Data
    health_items = []
    
    # Monitor Tasks Status
    active_monitors = MonitorTask.objects.filter(enabled=True).count()
    health_items.append({
        "name": "Log Monitor Engine",
        "desc": f"{active_monitors} active tasks",
        "status": "online" if active_monitors > 0 else "warning"
    })
    
    # Sync Tasks Status
    error_tasks = SyncTask.objects.filter(status='error').count()
    health_items.append({
        "name": "Data Sync Pipeline",
        "desc": f"{error_tasks} tasks with errors" if error_tasks > 0 else "All tasks healthy",
        "status": "online" if error_tasks == 0 else "warning"
    })

    # Recent Inspection
    latest_report = InspectionReport.objects.order_by('-created_at').first()
    if latest_report:
        content = latest_report.content or {}
        score = content.get('health_summary', {}).get('score')
        if score is None:
            score = content.get('risk_summary', {}).get('score', 0)
        health_items.append({
            "name": "System Inspection",
            "desc": f"Last score: {score}%",
            "status": "online" if score > 80 else "warning"
        })

    return Response({
        "resources": {
            "cpu": { "value": f"{cpu_percent}%", "percentage": cpu_percent },
            "memory": { "value": f"{round(mem.used / (1024**3), 1)} GB", "percentage": mem.percent, "total": f"{round(mem.total / (1024**3), 1)} GB" },
            "disk": { "value": f"{round(disk.used / (1024**3), 1)} GB", "percentage": disk.percent, "total": f"{round(disk.total / (1024**3), 1)} GB" },
            "load": "Optimal" if cpu_percent < 70 else "High"
        },
        "health": health_items
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    # Collect all permissions from user's groups
    perms = set()
    if request.user.is_superuser:
        perms.add('all')
    else:
        for group in request.user.groups.all().prefetch_related('permissions'):
            for p in group.permissions.all():
                perms.add(p.codename)
                
    return Response({
        "id": request.user.id,
        "username": request.user.username,
        "email": request.user.email,
        "is_staff": request.user.is_staff,
        "is_superuser": request.user.is_superuser,
        "groups": [g.name for g in request.user.groups.all()],
        "permissions": list(perms)
    })

@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def user_list(request):
    if request.method == 'GET':
        users = User.objects.all().prefetch_related('groups')
        data = []
        for u in users:
            data.append({
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "is_active": u.is_active,
                "is_staff": u.is_staff,
                "groups": [g.name for g in u.groups.all()]
            })
        return Response({"users": data})
    
    elif request.method == 'POST':
        data = request.data
        user = User.objects.create_user(
            username=data['username'],
            password=data['password'],
            email=data.get('email', '')
        )
        if 'groups' in data:
            for gname in data['groups']:
                group, _ = Group.objects.get_or_create(name=gname)
                user.groups.add(group)
                if gname == 'Admin':
                    user.is_staff = True
        user.save()
        return Response({"msg": "created"})

@api_view(['PUT', 'DELETE'])
@permission_classes([HasRolePermission])
def user_detail(request, pk):
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return Response({"error": "User not found"}, status=404)
        
    if request.method == 'PUT':
        data = request.data
        if 'is_active' in data:
            user.is_active = data['is_active']
        if 'groups' in data:
            user.groups.clear()
            user.is_staff = False
            for gname in data['groups']:
                group, _ = Group.objects.get_or_create(name=gname)
                user.groups.add(group)
                if gname == 'Admin':
                    user.is_staff = True
        user.save()
        return Response({"msg": "updated"})
        
    elif request.method == 'DELETE':
        if user.is_superuser:
            return Response({"error": "Cannot delete superuser"}, status=400)
        user.delete()
        return Response({"msg": "deleted"})

# --- Role & Permission Management ---

@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def role_list(request):
    _ensure_custom_permissions()
    if request.method == 'GET':
        allowed = {p["codename"] for p in _ensure_custom_permissions()}
        groups = Group.objects.all().prefetch_related('permissions')
        data = []
        for g in groups:
            data.append({
                "id": g.id,
                "name": g.name,
                "permissions": [p.codename for p in g.permissions.filter(codename__in=allowed)]
            })
        return Response({"roles": data})
    
    elif request.method == 'POST':
        data = request.data
        group = None
        
        # Try to find by ID first if provided (Edit mode)
        if 'id' in data and data['id']:
            try:
                group = Group.objects.get(id=data['id'])
                group.name = data['name']
                group.save()
            except Group.DoesNotExist:
                pass
        
        # Fallback to get_or_create by name
        if not group:
            group, created = Group.objects.get_or_create(name=data['name'])
            
        if 'permissions' in data:
            requested = list(data['permissions'] or [])
            perms = Permission.objects.filter(codename__in=requested)
            existing = set(perms.values_list('codename', flat=True))
            if requested:
                mapping = {p["codename"]: p["name"] for p in _ensure_custom_permissions()}
                missing = [c for c in requested if c not in existing]
                for codename in missing:
                    Permission.objects.get_or_create(
                        content_type=_custom_permission_content_type(),
                        codename=codename,
                        defaults={"name": mapping.get(codename, codename)},
                    )
                perms = Permission.objects.filter(codename__in=requested)
            group.permissions.set(perms)
        saved = [p.codename for p in group.permissions.all()]
        return Response({"msg": "saved", "id": group.id, "permissions": saved})

@api_view(['GET'])
@permission_classes([HasRolePermission])
def permission_list(request):
    perms = _ensure_custom_permissions()
    return Response({"permissions": perms})
