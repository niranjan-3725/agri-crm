from django.utils import timezone


def farming_context(request):
    """Injects season_transition_needed into every template context.
    True in October (end of Kharif) and March (end of Rabi).
    """
    month = timezone.now().month
    return {'season_transition_needed': month in (3, 10)}
