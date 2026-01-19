from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from transactions.models import SalesInvoice, CustomerPayment, SalesItem
from master_data.models import Customer, Product, Category, Manufacturer
from inventory.models import Batch

class WalletReversalScenarioTest(TestCase):
    def setUp(self):
        # 1. Setup Master Data
        self.category = Category.objects.create(name="TestCat", cgst_rate=0, sgst_rate=0)
        self.manufacturer = Manufacturer.objects.create(name="TestMan")
        self.product = Product.objects.create(
            name="TestProduct", 
            category=self.category, 
            manufacturer=self.manufacturer,
            unit_type="Kg"
        )
        self.batch = Batch.objects.create(
            product=self.product,
            batch_number="B001",
            purchase_price=100,
            base_selling_price=150,
            current_quantity=100,
            mrp=200
        )
        
        # 2. Create 'Test Zero' Customer
        self.customer = Customer.objects.create(
            name="Test Zero",
            mobile_no="9999999999",
            address="Test Address",
            wallet_balance=0.00
        )

    def test_reversal_flow(self):
        print("\n--- Starting Wallet Reversal Simulation ---")
        
        # Step 1: Create Invoice (Debts: 10 Rupees)
        # We'll make an invoice for 10 rupees.
        invoice = SalesInvoice.objects.create(
            customer=self.customer,
            total_taxable=10,
            total_cgst=0,
            total_sgst=0,
            grand_total=10,
            balance_due=10,
            payment_status='UNPAID'
        )
        print(f"1. Created Invoice #{invoice.invoice_number}. Grand Total: {invoice.grand_total}, Status: {invoice.payment_status}, Balance Due: {invoice.balance_due}")
        
        # Step 2: Add Money to Wallet (5 Rupees)
        # We simulate this by just setting the balance, or adding a credit transaction.
        # User said "Add some money". Let's update model directly as per typical flow.
        self.customer.wallet_balance = Decimal('5.00')
        self.customer.save()
        self.customer.refresh_from_db()
        print(f"2. Added 5 to Wallet. Current Wallet Balance: {self.customer.wallet_balance}")
        
        # Step 3: Pay Invoice with Wallet (5 Rupees)
        # Logic: Calls settle_invoice_via_wallet OR creates a payment mode='WALLET'
        print("3. Paying Invoice with Wallet (5.00)...")
        payment = CustomerPayment.objects.create(
            invoice=invoice,
            amount=Decimal('5.00'),
            payment_mode='WALLET',
            notes='Partial Payment via Wallet'
        )
        
        # Verify Post-Payment State
        self.customer.refresh_from_db()
        invoice.refresh_from_db()
        
        print(f"   -> Wallet Balance should be 0. Actual: {self.customer.wallet_balance}")
        print(f"   -> Invoice Balance Due should be 5. Actual: {invoice.balance_due}")
        print(f"   -> Invoice Status should be PARTIAL. Actual: {invoice.payment_status}")
        
        self.assertEqual(self.customer.wallet_balance, 0, "Wallet failed to deduct.")
        self.assertEqual(invoice.balance_due, 5, "Invoice balance failed to update.")
        
        # Step 4: Reverse the Payment
        # We call the logic that reverse_wallet_transaction uses: Create a counter-entry.
        print("4. Reversing the Payment...")
        reverse_amount = -payment.amount
        reversal = CustomerPayment.objects.create(
            invoice=invoice,
            amount=reverse_amount,
            payment_mode=payment.payment_mode, # WALLET
            notes=f"Reversal of #{payment.id}"
        )
        
        # Step 5: Verify Final State
        self.customer.refresh_from_db()
        invoice.refresh_from_db()
        
        print(f"5. Final Verification:")
        print(f"   -> Wallet Balance should be restored to 5.00. Actual: {self.customer.wallet_balance}")
        print(f"   -> Invoice Balance Due should be 10.00. Actual: {invoice.balance_due}")
        print(f"   -> Invoice Status should be UNPAID. Actual: {invoice.payment_status}")
        
        self.assertEqual(self.customer.wallet_balance, 5.00, "Wallet failed to restore fund.")
        self.assertEqual(invoice.balance_due, 10.00, "Invoice balance failed to revert.")
        self.assertEqual(invoice.payment_status, 'UNPAID', "Invoice status failed to revert.")
        
        print("--- Simulation Passed Successfully ---")
