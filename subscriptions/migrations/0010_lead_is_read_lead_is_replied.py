from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0009_alter_contentitem_options_remove_contentitem_module_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="is_read",
            field=models.BooleanField(default=False, verbose_name="read"),
        ),
        migrations.AddField(
            model_name="lead",
            name="is_replied",
            field=models.BooleanField(default=False, verbose_name="replied"),
        ),
    ]
