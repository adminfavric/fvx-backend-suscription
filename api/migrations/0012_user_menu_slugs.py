# Permisos por persona: lista de slugs de páginas que cada usuario puede ver
# (vacío = según su rol). Ver api/models/user.py (User.menu_slugs).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0011_historial_icon"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="menu_slugs",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "Permisos por persona: lista de slugs de páginas que este usuario "
                    "puede ver. Vacío = ve según su rol. Se ignora para staff (ve todo)."
                ),
                verbose_name="menu slugs",
            ),
        ),
    ]
