from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('papers', '0004_tableimage'),
    ]

    operations = [
        migrations.AddField(
            model_name='experimentrecord',
            name='table_image',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='records',
                to='papers.tableimage',
            ),
        ),
    ]
