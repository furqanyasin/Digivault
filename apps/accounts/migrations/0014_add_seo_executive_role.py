from django.db import migrations, models

_CHOICES = [
    ("owner", "Owner"),
    ("manager", "Manager"),
    ("developer", "Developer"),
    ("viewer", "Viewer"),
    ("custom", "Custom"),
    ("seo_executive", "SEO Executive"),
    ("editor", "Editor"),
    ("seo", "SEO"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_subteam_teammembership_sub_team_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="teammembership",
            name="role",
            field=models.CharField(
                choices=_CHOICES, default="developer", max_length=20
            ),
        ),
        migrations.AlterField(
            model_name="teaminvitation",
            name="role",
            field=models.CharField(
                choices=_CHOICES, default="developer", max_length=20
            ),
        ),
    ]
