# Pre-Existing Test Failure Report

## Issue Overview
During Sprint 3 verification, a single pre-existing test failure was identified in `transactions.test_legacy_tests.PurchaseCreateViewTest.test_valid_submission`.

**The Error:**
```python
FAIL: test_valid_submission (transactions.test_legacy_tests.PurchaseCreateViewTest.test_valid_submission)
Traceback (most recent call last):
    self.assertEqual(invoice.loading_charges, 50.00)
AssertionError: Decimal('10.00') != 50.0
```

## Root Cause Analysis
The failure is **not** a bug in the application code, but rather a mismatch within the test file itself. 

In `transactions/test_legacy_tests.py`, the test data payload (`self.valid_data`) is mocking the form submission as follows:
```python
self.valid_data = {
    # ...
    'loading_charges': '10',
    'discount': '5'
}
```

However, the specific test `test_valid_submission` (around line 64) asserts that these fields should be saved differently:
```python
def test_valid_submission(self):
    # ...
    self.assertEqual(invoice.loading_charges, 50.00)
    self.assertEqual(invoice.additional_discount, 10.00)
```

The test is sending `10` but expecting `50`, and sending `5` but expecting `10`.

## How to Fix It
We have two simple options to resolve this mismatch:

**Option 1: Update the Assertions (Recommended)**
Update the test assertions to match the `self.valid_data` payload.
```python
self.assertEqual(invoice.loading_charges, 10.00)
self.assertEqual(invoice.additional_discount, 5.00)
```

**Option 2: Update the Test Payload**
Update the `test_valid_submission` to explicitly inject `50` and `10` before submitting.
```python
def test_valid_submission(self):
    custom_data = self.valid_data.copy()
    custom_data['loading_charges'] = '50'
    custom_data['discount'] = '10'
    response = self.client.post(self.create_url, custom_data)
    # ...
```

Please let me know which option you prefer, and I will execute the fix!
