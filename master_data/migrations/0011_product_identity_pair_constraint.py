from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Enforce the Product Identity Pair Invariant:
    A product is uniquely identified by (name, manufacturer).
    Two manufacturers may sell a product of the same name;
    one manufacturer may never list the same product twice.
    """

    dependencies = [
        ('master_data', '0010_village_customer_identity'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='product',
            constraint=models.UniqueConstraint(
                fields=['name', 'manufacturer'],
                name='unique_product_name_manufacturer',
            ),
        ),
    ]
