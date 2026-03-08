from django.db import migrations


def add_venn_chart_type(apps, schema_editor):
    ChartType = apps.get_model('tyk_notebook_app', 'ChartType')
    ChartType.objects.get_or_create(
        key='venn_diagram',
        defaults={'name': 'Venn Diagram', 'is_active': True}
    )


def remove_venn_chart_type(apps, schema_editor):
    ChartType = apps.get_model('tyk_notebook_app', 'ChartType')
    ChartType.objects.filter(key='venn_diagram').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tyk_notebook_app', '0008_add_cell_is_active'),
    ]

    operations = [
        migrations.RunPython(add_venn_chart_type, remove_venn_chart_type),
    ]
