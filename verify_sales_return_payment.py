
import os
import django
from decimal import Decimal
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from transactions.models import CustomerPayment, SalesReturn, Customer
from django.db import IntegrityError

def verify_sales_return_integration():
    print("Verifying Sales Return Financial Integration...")
    
    # Setup
    customer, _ = Customer.objects.get_or_create(name="Test Customer 57")
    
    print(f"Customer created: {customer}")

    # 1. Create Sales Return
    sr = SalesReturn.objects.create(
        customer=customer,
        date=timezone.now().date(),
        refund_amount=Decimal("500.00")
    )
    print(f"Sales Return created: {sr.pk}")

    # 2. Simulate View Logic: Create Payment
    try:
        payment = CustomerPayment.objects.create(
            invoice=None, # Should differ from None if not nullable, but we made it nullable
            amount=sr.refund_amount,
            payment_mode='WALLET_CREDIT',
            payment_date=sr.date,
            notes=f"Auto-credit for Return #{sr.pk}",
            sales_return=sr
        )
        print(f"Payment created successfully: {payment.pk}")
        print(f"  Mode: {payment.payment_mode}")
        print(f"  Amount: {payment.amount}")
        print(f"  Sales Return ID: {payment.sales_return.pk}")
        print(f"  Invoice: {payment.invoice}")
        
    except IntegrityError as e:
        print(f"FAILED: IntegrityError - {e}")
        return

    # 3. Verify Query for Statement
    # Query used in view: Q(invoice__customer=customer) | Q(sales_return__customer=customer)
    from django.db.models import Q
    payments = CustomerPayment.objects.filter(
        Q(invoice__customer=customer) | Q(sales_return__customer=customer)
    )
    
    if payment in payments:
        print("SUCCESS: Payment found in statement query.")
    else:
        print("FAILED: Payment NOT found in statement query.")
        
    # Cleanup
    payment.delete()
    sr.delete()
    customer.delete()

if __name__ == "__main__":
    verify_sales_return_integration()
