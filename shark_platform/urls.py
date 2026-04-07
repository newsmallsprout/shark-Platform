from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve
from django.conf import settings
from django.http import HttpResponse
import os


def serve_spa(request):
    try:
        possible_paths = [
            os.path.join(settings.BASE_DIR, "frontend/dist/index.html"),
            os.path.join(settings.BASE_DIR, "templates/index.html"),
        ]
        for p in possible_paths:
            if os.path.exists(p):
                with open(p, "r") as f:
                    return HttpResponse(f.read())
        return HttpResponse(
            "Frontend index.html not found. Run 'npm run build' in frontend directory.",
            status=501,
        )
    except Exception as e:
        return HttpResponse(f"Error serving SPA: {str(e)}", status=500)


def serve_static_from_root(request, path):
    doc_root = os.path.join(settings.BASE_DIR, "frontend/dist")
    fullpath = os.path.join(doc_root, path)
    if os.path.isfile(fullpath):
        return serve(request, path, document_root=doc_root)
    return serve_spa(request)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("api/ai_ops/", include("ai_ops.urls")),
    re_path(
        r"^assets/(?P<path>.*)$",
        serve,
        {"document_root": os.path.join(settings.BASE_DIR, "frontend/dist/assets")},
    ),
    re_path(r"^(?P<path>.*)$", serve_static_from_root),
]
