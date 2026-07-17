"""core loyihasi URL konfiguratsiyasi."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core import dashboard

admin.site.site_header = "Nurli Diyor — boshqaruv"
admin.site.site_title = "Nurli Diyor admin"
admin.site.index_title = "Boshqaruv paneli"
dashboard.install()   # bosh sahifaga statistika (templates/admin/index.html)

from inventory import views as inventory_views

urlpatterns = [
    # admin.site.urls dan OLDIN turishi shart (aks holda admin/ ushlab qoladi)
    path('admin/narx/', inventory_views.price_calculator, name='price_calculator'),
    path('admin/narx/pdf/', inventory_views.price_pdf, name='price_pdf'),
    path('admin/', admin.site.urls),
    path('api/', include('inventory.urls')),
]

# Ishlab chiqish (DEBUG) rejimida media (yuklangan rasm)larni Django o'zi uzatadi
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
