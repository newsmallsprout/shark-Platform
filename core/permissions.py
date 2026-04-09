"""DRF permissions for AIOps 运维类 API（可选强制 staff）。"""

from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import BasePermission


class AiOpsOpsPermission(BasePermission):
    """
    若 ``AIOPS_OPS_REQUIRE_STAFF=True``，仅 staff 用户可写运维接口；
    默认 False 保持与历史行为一致（已登录即可）。
    """

    message = "需要运维权限（staff）"

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(settings, "AIOPS_OPS_REQUIRE_STAFF", False):
            return bool(getattr(request.user, "is_staff", False))
        return True
