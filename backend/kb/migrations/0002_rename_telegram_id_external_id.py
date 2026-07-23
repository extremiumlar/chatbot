# Instagramga o'tish: Lead/Message maydoni endi kanaldan mustaqil (external_id).
# managed=False bo'lgani uchun bu migratsiya real DB'ni o'zgartirmaydi (haqiqiy
# ustun ko'chirishni knowledge/db.py::migrate_platform_id() bajaradi) — faqat
# Django migratsiya holatini modellar bilan mos saqlaydi.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kb', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='lead',
            old_name='telegram_id',
            new_name='external_id',
        ),
        migrations.AlterField(
            model_name='lead',
            name='external_id',
            field=models.BigIntegerField(blank=True, null=True, unique=True,
                                          verbose_name='Kanal ID (Instagram)'),
        ),
        migrations.RenameField(
            model_name='message',
            old_name='telegram_id',
            new_name='external_id',
        ),
        migrations.AlterField(
            model_name='message',
            name='external_id',
            field=models.BigIntegerField(verbose_name='Kanal ID (Instagram)'),
        ),
    ]
