from django.contrib import admin
from django.utils.html import format_html

from .models import Layout


@admin.register(Layout)
class LayoutAdmin(admin.ModelAdmin):
    list_display = ("__str__", "blocks", "available_count", "total_count",
                    "image_tag", "is_active", "synced_at")
    list_filter = ("rooms", "is_active")
    list_editable = ("is_active",)
    readonly_fields = ("image_preview", "image_3d_preview", "sample_flat_id", "synced_at",
                       "created_at", "updated_at")
    fields = ("rooms", "area", "blocks", "available_count", "total_count",
              "min_floor", "max_floor", "sample_flat_id",
              "planirovka", "image_preview",
              "planirovka_3d", "image_3d_preview",
              "is_active", "note",
              "synced_at", "created_at", "updated_at")

    @admin.display(description="Rasm")
    def image_tag(self, obj):
        thumbs = []
        if obj.planirovka:
            thumbs.append(format_html(
                '<img src="{}" title="2D" style="height:44px;border-radius:4px;margin-right:4px" />',
                obj.planirovka.url))
        if obj.planirovka_3d:
            thumbs.append(format_html(
                '<img src="{}" title="3D" style="height:44px;border-radius:4px" />',
                obj.planirovka_3d.url))
        if thumbs:
            return format_html("".join(["{}"] * len(thumbs)), *thumbs)
        return format_html('<span style="color:#c00">— yo\'q —</span>')

    @admin.display(description="Planirovka (2D) ko'rinishi")
    def image_preview(self, obj):
        if obj.planirovka:
            return format_html('<img src="{}" style="max-width:520px;border:1px solid #ddd" />',
                               obj.planirovka.url)
        return "Hali 2D rasm yuklanmagan (ixtiyoriy)."

    @admin.display(description="Planirovka (3D) ko'rinishi")
    def image_3d_preview(self, obj):
        if obj.planirovka_3d:
            return format_html('<img src="{}" style="max-width:520px;border:1px solid #ddd" />',
                               obj.planirovka_3d.url)
        return "Hali 3D rasm yuklanmagan (ixtiyoriy)."
