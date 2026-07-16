from django.urls import path

from . import views

urlpatterns = [
    path("layouts/", views.layouts_api, name="layouts_api"),
]
