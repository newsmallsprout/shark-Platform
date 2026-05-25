from django.urls import path
from . import views

urlpatterns = [
    path('connections/', views.connection_list),
    path('connections/<str:pk>/', views.connection_detail),
    path('test/', views.test_connection),
    path('test/<str:pk>/', views.test_saved_connection),
    path('<str:pk>/structure/', views.get_structure),
    path('<str:pk>/query/', views.execute_query),
]
