from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('OpenBench', '0017_import_verdict_config'),
    ]

    operations = [
        migrations.AddField(
            model_name='test',
            name='eta_games',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='test',
            name='eta_core_seconds',
            field=models.FloatField(default=0.0),
        ),
    ]
