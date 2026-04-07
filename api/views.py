from __future__ import annotations

import logging

import psutil
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    username = request.data.get("username")
    password = request.data.get("password")
    user = authenticate(request, username=username, password=password)
    if user is not None:
        login(request, user)
        return Response({"msg": "Login successful", "username": user.username})
    return Response({"error": "Invalid credentials"}, status=401)


@api_view(["POST"])
def logout_view(request):
    logout(request)
    return Response({"msg": "Logged out"})


def _edge_token_ok(request) -> bool:
    tok = getattr(settings, "SHARK_EDGE_TOKEN", "") or ""
    if not tok:
        return False
    got = (request.META.get("HTTP_X_SHARK_EDGE_TOKEN") or "").strip()
    return got == tok


@api_view(["POST"])
@permission_classes([AllowAny])
def edge_heartbeat(request):
    """Distributed go-agent: push host metrics snapshot."""
    if not _edge_token_ok(request):
        return Response({"error": "unauthorized"}, status=401)
    body = request.data if isinstance(request.data, dict) else {}
    node_id = str(body.get("node_id") or body.get("hostname") or "unknown")
    from django.core.cache import cache

    cache.set(f"edge:hb:{node_id}", body, timeout=600)
    logger.info("edge heartbeat node=%s keys=%s", node_id, list(body.keys()))
    return Response({"ok": True, "node_id": node_id})


@api_view(["POST"])
@permission_classes([AllowAny])
def edge_logs(request):
    """Distributed go-log-collector: push batched log lines for analytics pipeline."""
    if not _edge_token_ok(request):
        return Response({"error": "unauthorized"}, status=401)
    body = request.data if isinstance(request.data, dict) else {}
    lines = body.get("lines") or body.get("events") or []
    n = len(lines) if isinstance(lines, list) else 0
    logger.info(
        "edge logs batch source=%s count=%s",
        body.get("source") or body.get("path") or "?",
        n,
    )
    return Response({"ok": True, "accepted": n})


class HasRolePermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if "users" in request.path or "roles" in request.path:
            return user.is_staff or user.groups.filter(name="Admin").exists()
        return True


def _custom_permission_content_type():
    ct, _ = ContentType.objects.get_or_create(app_label="api", model="custom_permission")
    return ct


def _ensure_custom_permissions():
    ct = _custom_permission_content_type()
    perms = [
        {"codename": "manage_users", "name": "Manage Users & Roles"},
        {"codename": "view_ai_ops", "name": "View AI Ops Console"},
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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def system_stats(request):
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return Response(
        {
            "resources": {
                "cpu": {"value": f"{cpu_percent}%", "percentage": cpu_percent},
                "memory": {
                    "value": f"{round(mem.used / (1024**3), 1)} GB",
                    "percentage": mem.percent,
                    "total": f"{round(mem.total / (1024**3), 1)} GB",
                },
                "disk": {
                    "value": f"{round(disk.used / (1024**3), 1)} GB",
                    "percentage": disk.percent,
                    "total": f"{round(disk.total / (1024**3), 1)} GB",
                },
                "load": "Optimal" if cpu_percent < 70 else "High",
            },
            "health": [
                {
                    "name": "Control Plane",
                    "desc": "Django API + LangGraph workers",
                    "status": "online",
                }
            ],
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    perms = set()
    if request.user.is_superuser:
        perms.add("all")
    else:
        for group in request.user.groups.all().prefetch_related("permissions"):
            for p in group.permissions.all():
                perms.add(p.codename)
    return Response(
        {
            "id": request.user.id,
            "username": request.user.username,
            "email": request.user.email,
            "is_staff": request.user.is_staff,
            "is_superuser": request.user.is_superuser,
            "groups": [g.name for g in request.user.groups.all()],
            "permissions": list(perms),
        }
    )


@api_view(["GET", "POST"])
@permission_classes([HasRolePermission])
def user_list(request):
    if request.method == "GET":
        users = User.objects.all().prefetch_related("groups")
        data = []
        for u in users:
            data.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "is_active": u.is_active,
                    "is_staff": u.is_staff,
                    "groups": [g.name for g in u.groups.all()],
                }
            )
        return Response({"users": data})
    data = request.data
    user = User.objects.create_user(
        username=data["username"],
        password=data["password"],
        email=data.get("email", ""),
    )
    if "groups" in data:
        for gname in data["groups"]:
            group, _ = Group.objects.get_or_create(name=gname)
            user.groups.add(group)
            if gname == "Admin":
                user.is_staff = True
    user.save()
    return Response({"msg": "created"})


@api_view(["PUT", "DELETE"])
@permission_classes([HasRolePermission])
def user_detail(request, pk):
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return Response({"error": "User not found"}, status=404)
    if request.method == "PUT":
        data = request.data
        if "is_active" in data:
            user.is_active = data["is_active"]
        if "groups" in data:
            user.groups.clear()
            user.is_staff = False
            for gname in data["groups"]:
                group, _ = Group.objects.get_or_create(name=gname)
                user.groups.add(group)
                if gname == "Admin":
                    user.is_staff = True
        user.save()
        return Response({"msg": "updated"})
    if user.is_superuser:
        return Response({"error": "Cannot delete superuser"}, status=400)
    user.delete()
    return Response({"msg": "deleted"})


@api_view(["GET", "POST"])
@permission_classes([HasRolePermission])
def role_list(request):
    _ensure_custom_permissions()
    if request.method == "GET":
        allowed = {p["codename"] for p in _ensure_custom_permissions()}
        groups = Group.objects.all().prefetch_related("permissions")
        data = []
        for g in groups:
            data.append(
                {
                    "id": g.id,
                    "name": g.name,
                    "permissions": [
                        p.codename for p in g.permissions.filter(codename__in=allowed)
                    ],
                }
            )
        return Response({"roles": data})
    data = request.data
    group = None
    if "id" in data and data["id"]:
        try:
            group = Group.objects.get(id=data["id"])
            group.name = data["name"]
            group.save()
        except Group.DoesNotExist:
            pass
    if not group:
        group, _ = Group.objects.get_or_create(name=data["name"])
    if "permissions" in data:
        requested = list(data["permissions"] or [])
        perms = Permission.objects.filter(codename__in=requested)
        existing = set(perms.values_list("codename", flat=True))
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


@api_view(["GET"])
@permission_classes([HasRolePermission])
def permission_list(request):
    perms = _ensure_custom_permissions()
    return Response({"permissions": perms})
