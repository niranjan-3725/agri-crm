from django import template
register = template.Library()

@register.filter
def filter_wallet_amount(payments):
    """
    Returns the total amount paid via WALLET for a given queryset of payments.
    Usage: {{ invoice.payments.all|filter_wallet_amount }}
    """
    total = 0
    if not payments:
        return 0
    
    for payment in payments:
        if payment.payment_mode == 'WALLET':
            total += payment.amount
    return total

@register.filter
def multiply(value, arg):
    """Multiply two numbers. Usage: {{ qty|multiply:price }}"""
    try:
        from decimal import Decimal
        return Decimal(str(value)) * Decimal(str(arg))
    except (ValueError, TypeError):
        return 0
