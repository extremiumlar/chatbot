"""core loyihasi URL konfiguratsiyasi."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

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
    path('api/instagram/', include('ig_bot.urls')),
]

# Media (planirovka rasmlari) DEBUG'dan QAT'I NAZAR Django orqali uzatiladi.
# ONGLI MUROSA: rasmlar kam va kichik (bir necha o'nlab planirovka) — kichik yuk
# uchun django.views.static.serve maqbul; ilgari DEBUG=0 qilinsa rasm 404 bo'lib,
# bot planirovka yubora olmay qolardi. Yuk oshsa deploy/nginx.conf.example dagi
# /media/ blokini yoqib, nginx'ga o'tkazing.
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", static_serve,
            {"document_root": settings.MEDIA_ROOT}),
]
