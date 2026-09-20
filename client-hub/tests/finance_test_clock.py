"""Historical regression fixtures must not depend on the wall clock."""
from datetime import date
from contextlib import ExitStack
from functools import wraps
from unittest.mock import patch

class ClosedPeriodDate(date):
    @classmethod
    def today(cls):return cls(2026,12,31)

def closed_period(test):
    @wraps(test)
    def run(*args,**kwargs):
        import finance_service, routes_finance, finance_reports, finance_collections
        with ExitStack() as stack:
            for module in (finance_service,routes_finance,finance_reports,finance_collections):stack.enter_context(patch.object(module,'date',ClosedPeriodDate))
            return test(*args,**kwargs)
    return run
