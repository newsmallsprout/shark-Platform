from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inspection', '0002_inspectionreport'),
    ]

    operations = [
        migrations.CreateModel(
            name='InspectionIgnore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=512, unique=True)),
                ('check_id', models.CharField(blank=True, default='', max_length=64)),
                ('label', models.CharField(blank=True, default='', max_length=512)),
                ('note', models.CharField(blank=True, default='', max_length=255)),
                ('created_by', models.CharField(blank=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
