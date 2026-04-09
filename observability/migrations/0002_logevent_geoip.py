# Generated manually for GeoIP fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("observability", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="logevent",
            name="client_ip",
            field=models.CharField(
                blank=True,
                default="",
                max_length=64,
                db_index=True,
                help_text="客户端 IP（优先 X-Forwarded-For 首段）",
            ),
        ),
        migrations.AddField(
            model_name="logevent",
            name="geo_country",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="logevent",
            name="geo_city",
            field=models.CharField(blank=True, default="", max_length=256),
        ),
        migrations.AddField(
            model_name="logevent",
            name="geo_lat",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="logevent",
            name="geo_lon",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
