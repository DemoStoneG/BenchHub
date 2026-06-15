from django.db import migrations, models
import django.db.models.deletion


def create_default_session_and_backfill(apps, schema_editor):
    """为历史数据创建默认 session，并把 benchmark 字段回填为 dataset。"""
    Session = apps.get_model('papers', 'Session')
    Paper = apps.get_model('papers', 'Paper')
    ExperimentRecord = apps.get_model('papers', 'ExperimentRecord')

    default_session, _ = Session.objects.get_or_create(
        name='默认项目',
        defaults={'description': '系统升级前已存在的论文集合'}
    )

    Paper.objects.filter(session__isnull=True).update(session=default_session)
    ExperimentRecord.objects.filter(benchmark='').update(benchmark=models.F('dataset'))


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('papers', '0002_paper_progress_message_alter_paper_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='Session',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
        migrations.AddField(
            model_name='paper',
            name='session',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='papers', to='papers.session'),
        ),
        migrations.AddField(
            model_name='experimentrecord',
            name='benchmark',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterModelOptions(
            name='experimentrecord',
            options={'ordering': ['benchmark', 'dataset', 'model_name']},
        ),
        migrations.RunPython(create_default_session_and_backfill, reverse_noop),
        migrations.AlterField(
            model_name='paper',
            name='session',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='papers', to='papers.session'),
        ),
    ]
