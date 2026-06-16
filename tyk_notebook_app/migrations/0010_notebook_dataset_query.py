from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tyk_notebook_app', '0009_add_venn_chart_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='notebook',
            name='dataset_query',
            field=models.TextField(blank=True, help_text='The search query used to generate this dataset'),
        ),
    ]
