"""core loyihasi URL konfiguratsiyasi."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Nurli Diyor — boshqaruv"
admin.site.site_title = "Nurli Diyor admin"
admin.site.index_title = "Xonadon turlari va planirovkalar"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('inventory.urls')),
]

# Ishlab chiqish (DEBUG) rejimida media (yuklangan rasm)larni Django o'zi uzatadi
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
