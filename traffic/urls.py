from django.urls import path

from . import views

urlpatterns = [
    path("traffic/sources", views.traffic_sources, name="traffic_sources"),
    path("traffic/snapshot", views.traffic_snapshot, name="traffic_snapshot"),
    path("traffic/overview", views.traffic_overview, name="traffic_overview"),
    path("traffic/timeseries", views.traffic_timeseries, name="traffic_timeseries"),
    path("traffic/geo", views.traffic_geo, name="traffic_geo"),
    path("traffic/top", views.traffic_top, name="traffic_top"),
    path("traffic/blackbox", views.traffic_blackbox, name="traffic_blackbox"),
    path(
        "traffic/jaeger/traces",
        views.traffic_jaeger_traces,
        name="traffic_jaeger_traces",
    ),
    path(
        "traffic/jaeger/trace/<str:trace_id>",
        views.traffic_jaeger_trace_detail,
        name="traffic_jaeger_trace_detail",
    ),
    path("traffic/config", views.traffic_dashboard_config, name="traffic_dashboard_config"),
    path("traffic/ingest", views.traffic_ingest, name="traffic_ingest"),
    path("edge/logs", views.edge_logs_ingest, name="edge_logs_ingest"),
]
