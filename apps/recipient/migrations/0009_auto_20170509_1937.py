# -*- coding: utf-8 -*-


from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('recipient', '0008_auto_20170509_1531'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='recipientgroup',
            name='updated_at',
        ),
        migrations.RemoveField(
            model_name='recipientgroup',
            name='updated_by',
        ),
        migrations.AlterField(
            model_name='recipientgroup',
            name='created_by',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', blank=True, to=settings.AUTH_USER_MODEL, null=True),
        ),
    ]
