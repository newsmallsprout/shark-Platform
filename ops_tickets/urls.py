from django.urls import path

from . import views

urlpatterns = [
    path("tickets/", views.ticket_collection),
    path("tickets/<int:pk>/", views.ticket_detail),
]
