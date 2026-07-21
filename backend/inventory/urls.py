from django.urls import path

from . import views

urlpatterns = [
    path("layouts/", views.layouts_api, name="layouts_api"),
    path("knowledge/", views.knowledge_api, name="knowledge_api"),
    path("qa/", views.qa_api, name="qa_api"),
    path("tariff/", views.tariff_api, name="tariff_api"),
]
