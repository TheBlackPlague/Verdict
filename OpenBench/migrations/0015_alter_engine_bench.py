from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('OpenBench', '0014_llr_history')]

    operations = [
        migrations.AlterField(
            model_name='engine',
            name='bench',
            field=models.IntegerField(blank=True, default=0, null=True),
        ),
    ]
