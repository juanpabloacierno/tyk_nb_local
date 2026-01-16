# Generated migration for ChartType model and DashboardChart FK

import django.db.models.deletion
from django.db import migrations, models


# Default chart types to create (matching the old CHART_TYPE_CHOICES)
DEFAULT_CHART_TYPES = [
    ('world_map', 'Global Publications Map'),
    ('clusters_network', 'TOP Clusters Network'),
    ('subclusters_network', 'Subclusters Network'),
    ('cooc_network', 'Co-occurrence Network'),
    ('cluster_stats', 'Cluster Statistics'),
]


def create_chart_types_and_migrate(apps, schema_editor):
    """Create default ChartType entries and migrate existing DashboardChart records"""
    ChartType = apps.get_model('tyk_notebook_app', 'ChartType')
    DashboardChart = apps.get_model('tyk_notebook_app', 'DashboardChart')

    # Create default chart types
    chart_type_map = {}
    for key, name in DEFAULT_CHART_TYPES:
        ct, _ = ChartType.objects.get_or_create(
            key=key,
            defaults={'name': name, 'is_active': True}
        )
        chart_type_map[key] = ct

    # Migrate existing DashboardChart records
    for dc in DashboardChart.objects.all():
        old_chart_type = dc.chart_type_old
        if old_chart_type in chart_type_map:
            dc.chart_type_new = chart_type_map[old_chart_type]
            dc.save()


def reverse_migration(apps, schema_editor):
    """Reverse the migration by restoring old chart_type values"""
    DashboardChart = apps.get_model('tyk_notebook_app', 'DashboardChart')

    for dc in DashboardChart.objects.all():
        if dc.chart_type_new:
            dc.chart_type_old = dc.chart_type_new.key
            dc.save()


class Migration(migrations.Migration):

    dependencies = [
        ('tyk_notebook_app', '0005_dashboardchart'),
    ]

    operations = [
        # Step 1: Create ChartType model
        migrations.CreateModel(
            name='ChartType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(help_text="Internal identifier (e.g., 'world_map')", max_length=50, unique=True)),
                ('name', models.CharField(help_text="Display name (e.g., 'Global Publications Map')", max_length=255)),
                ('description', models.TextField(blank=True, help_text='Description of what this chart shows')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),

        # Step 2: Rename old chart_type field
        migrations.RenameField(
            model_name='dashboardchart',
            old_name='chart_type',
            new_name='chart_type_old',
        ),

        # Step 3: Remove old unique_together constraint
        migrations.AlterUniqueTogether(
            name='dashboardchart',
            unique_together=set(),
        ),

        # Step 4: Add new FK field (nullable for now)
        migrations.AddField(
            model_name='dashboardchart',
            name='chart_type_new',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='dashboard_charts_new',
                to='tyk_notebook_app.charttype'
            ),
        ),

        # Step 5: Migrate data
        migrations.RunPython(create_chart_types_and_migrate, reverse_migration),

        # Step 6: Remove old field
        migrations.RemoveField(
            model_name='dashboardchart',
            name='chart_type_old',
        ),

        # Step 7: Rename new field to chart_type
        migrations.RenameField(
            model_name='dashboardchart',
            old_name='chart_type_new',
            new_name='chart_type',
        ),

        # Step 8: Make FK non-nullable and update field definition
        migrations.AlterField(
            model_name='dashboardchart',
            name='chart_type',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='dashboard_charts',
                to='tyk_notebook_app.charttype'
            ),
        ),

        # Step 9: Restore unique_together constraint
        migrations.AlterUniqueTogether(
            name='dashboardchart',
            unique_together={('notebook', 'chart_type')},
        ),
    ]
