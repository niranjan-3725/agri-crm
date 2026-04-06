import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0009_sprint10_backfill_moving_avg'),
    ]

    operations = [
        # 1. Create Village master
        migrations.CreateModel(
            name='Village',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),

        # 2. Add Farm Profile optional fields
        migrations.AddField(
            model_name='customer',
            name='father_name',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name="Father's Name"),
        ),
        migrations.AddField(
            model_name='customer',
            name='land_size',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True, verbose_name='Land Size (acres)'),
        ),

        # 3. Add village FK (null=True so existing rows are unaffected)
        migrations.AddField(
            model_name='customer',
            name='village',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='master_data.village',
                verbose_name='City/Village',
            ),
        ),

        # 4. Drop the old free-text city CharField
        migrations.RemoveField(
            model_name='customer',
            name='city',
        ),

        # 5. Enforce uniqueness on mobile_no at DB level
        migrations.AlterField(
            model_name='customer',
            name='mobile_no',
            field=models.CharField(max_length=20, unique=True, verbose_name='Mobile Number'),
        ),

        # 6. Named unique constraint (Rule 31: Identity Uniqueness Invariant)
        migrations.AddConstraint(
            model_name='customer',
            constraint=models.UniqueConstraint(fields=['mobile_no'], name='unique_customer_mobile_no'),
        ),
    ]
