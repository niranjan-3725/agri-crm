import os
import django
import sys
from decimal import Decimal

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from transactions.models import SalesReturn, SalesReturnItem, CustomerPayment, Customer, SalesInvoice
from inventory.models import Batch
from master_data.models import Product, Category, Manufacturer
from django.db import transaction
from django.utils import timezone

def verify_safe_delete():
    print("--- Starting Verification: Safe Delete Sales Return ---")
    
    # 1. Setup Test Data
    try:
        # Get or Create dependencies
        customer = Customer.objects.first()
        category = Category.objects.first() or Category.objects.create(name="TestCat", cgst_rate=0, sgst_rate=0)
        manufacturer = Manufacturer.objects.first() or Manufacturer.objects.create(name="TestMan")
        product = Product.objects.first() or Product.objects.create(
            name="Test Product", 
            category=category,
            manufacturer=manufacturer,
            unit_type="Kg",
            hsn_code="1234"
        )
        batch = Batch.objects.create(
            product=product, 
            batch_number="TEST-BATCH-REVERSAL", 
            mrp=100, 
            purchase_price=80, 
            base_selling_price=90,
            current_quantity=100 # Initial Stock
        )
        
        print(f"Initial Stock: {batch.current_quantity}")
        
        # 2. Simulate Sales Return (Item IN, Money Credit)
        with transaction.atomic():
            sales_return = SalesReturn.objects.create(
                customer=customer,
                date=timezone.now().date(),
                refund_amount=500
            )
            
            SalesReturnItem.objects.create(
                return_invoice=sales_return,
                batch=batch,
                quantity=10
            )
            
            # Simulate View Logic: Update Stock
            batch.current_quantity += 10
            batch.save()
            
            # Simulate View Logic: Create Payment Credit
            payment = CustomerPayment.objects.create(
                invoice=None,
                amount=500,
                payment_mode='WALLET_CREDIT',
                sales_return=sales_return
            )
            
        # Refresh Data
        batch.refresh_from_db()
        print(f"After Return (Stock +10): {batch.current_quantity}")
        if batch.current_quantity != 110:
             print("ERROR: Stock did not increase!")
             return

        if not CustomerPayment.objects.filter(sales_return=sales_return).exists():
             print("ERROR: Payment not created!")
             return
             
        # 3. Call Delete Logic (Using the view function logic, simplified for script)
        # We can't call view directly easily, so we reproduce the logic exactly.
        print("Executing Delete Logic...")
        
        with transaction.atomic():
            # Inventory Reversal
            for item in sales_return.items.all():
                b = item.batch
                print(f"Reversing Stock for {b.batch_number}: {b.current_quantity} - {item.quantity}")
                b.current_quantity -= item.quantity
                b.save()
            
            # Financial Reversal
            if hasattr(sales_return, 'payment_entry'):
                print("Deleting Payment Entry...")
                sales_return.payment_entry.delete()
            
            # Delete Return
            sales_return.delete()
            
        # 4. Verify Final State
        batch.refresh_from_db()
        print(f"Final Stock: {batch.current_quantity}")
        
        if batch.current_quantity == 100:
            print("SUCCESS: Stock Reversal Verified (110 -> 100)")
        else:
            print(f"ERROR: Stock Reversal Failed. Expected 100, got {batch.current_quantity}")

        if not CustomerPayment.objects.filter(pk=payment.pk).exists():
             print("SUCCESS: Payment Deletion Verified")
        else:
             print("ERROR: Payment Deletion Failed")

    except Exception as e:
        print(f"Exception: {e}")
    finally:
        # Cleanup
        try:
            batch.delete()
        except: pass

if __name__ == "__main__":
    verify_safe_delete()
