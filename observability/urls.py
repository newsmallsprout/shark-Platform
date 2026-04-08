from django.urls import path

from . import views

urlpatterns = [
    path("streams/", views.stream_list, name="obs_streams"),
    path("traffic/summary/", views.traffic_summary, name="obs_traffic_summary"),
    path("insights/", views.insight_list, name="obs_insights"),
    path("traffic/analyze/", views.traffic_analyze, name="obs_traffic_analyze"),
]
