"""Read-only dashboard presentation. All ledger reads use existing scoped services."""
import calendar
from datetime import date

import finance_service as finance
import finance_fx


def month_at(index):
    return f'{index // 12:04d}-{index % 12 + 1:02d}'


def build(business_id, user_id, month, today, currency, fx, bill_projection,
          *, personal=False, trend_months=6, query=''):
    actor = {'actor_user_id': user_id}
    index = int(month[:4]) * 12 + int(month[5:]) - 1
    start = month + '-01'
    last = date(int(month[:4]), int(month[5:]), calendar.monthrange(int(month[:4]), int(month[5:]))[1])
    end = min(last, today).isoformat()
    trend_start = month_at(max(12, index - trend_months + 1))
    native = finance.get_monthly_cashflow_trends(
        business_id, trend_start, month, end_date=end, **actor)
    rules = finance.list_recurring_expenses(business_id, include_inactive=True, **actor)
    bills = bill_projection(business_id, rules, start, last.isoformat(), today.isoformat(), user_id)
    invoices = finance.get_report_invoices(
        business_id, end, start_date=start, end_date=end, open_only=True, **actor)
    horizon = max((r['next_due_on'] for r in rules if r['is_active']), default=end)
    upcoming = finance.preview_due_recurring_expenses(business_id, horizon, **actor) if rules else []
    upcoming = [r for r in upcoming if r['next_due_on'] >= max(start, today.isoformat())][:5]
    codes = {currency} | {r['currency'] for r in native + bills + invoices + upcoming}
    if codes.difference(fx.get('rates', {})):
        fx = finance_fx.snapshot(sorted(codes))

    def converted(rows, field):
        return finance_fx.convert_total(rows, currency, fx, field=field) if rows else 0

    def money(value):
        return 'Kurs belum lengkap' if value is None else finance_fx.format_money(value, currency)

    trend = []
    for key in sorted({r['month'] for r in native}):
        rows = [r for r in native if r['month'] == key]
        income, expense = converted(rows, 'income_minor'), converted(rows, 'expense_minor')
        net = None if income is None or expense is None else income - expense
        trend.append(dict(month=key, currency=currency, income_minor=income, expense_minor=expense,
                          net_minor=net, income_display=money(income), expense_display=money(expense),
                          net_display=money(net)))
    chart_valid = all(r['net_minor'] is not None for r in trend)
    maximum = max([1] + [max(r['income_minor'], r['expense_minor']) for r in trend if r['net_minor'] is not None])
    for row in trend:
        row['income_percent'] = 0 if row['income_minor'] is None else round(row['income_minor'] * 100 / maximum, 2)
        row['expense_percent'] = 0 if row['expense_minor'] is None else round(row['expense_minor'] * 100 / maximum, 2)
    income = sum(r['income_minor'] for r in trend) if chart_valid else None
    expense = sum(r['expense_minor'] for r in trend) if chart_valid else None
    # Compare matching month-to-date windows; a zero previous base is not a percentage.
    prev = month_at(index - 1)
    prev_end = date(int(prev[:4]), int(prev[5:]), calendar.monthrange(int(prev[:4]), int(prev[5:]))[1] if end == last.isoformat() else min(int(end[-2:]), calendar.monthrange(int(prev[:4]), int(prev[5:]))[1]))
    previous = finance.get_finance_summaries(business_id, prev+'-01', prev_end.isoformat(), **actor)
    if {r['currency'] for r in previous}.difference(fx.get('rates', {})):
        previous_fx = finance_fx.snapshot(sorted(codes | {r['currency'] for r in previous}))
    else:
        previous_fx = fx
    changes = {}
    for direction in ('income', 'expense'):
        before = finance_fx.convert_total(previous, currency, previous_fx, field=f'total_{direction}_minor') if previous else 0
        current = trend[-1][f'{direction}_minor'] if trend else None
        changes[direction] = round((current-before)*100/before, 1) if before and current is not None else None

    previous_range_end = month_at(index-trend_months)
    previous_days = calendar.monthrange(int(previous_range_end[:4]), int(previous_range_end[5:]))[1]
    previous_range_end += f'-{(previous_days if end == last.isoformat() else min(int(end[-2:]), previous_days)):02d}'
    previous_range = finance.get_finance_summaries(
        business_id, month_at(max(12, index-2*trend_months+1))+'-01', previous_range_end, **actor)
    previous_codes = {r['currency'] for r in previous_range}
    comparison_fx = finance_fx.snapshot(sorted(codes | previous_codes)) if previous_codes.difference(fx.get('rates', {})) else fx
    previous_net = finance_fx.convert_total(previous_range, currency, comparison_fx, field='net_cashflow_minor') if previous_range else 0
    net_change = round(((income-expense)-previous_net)*100/abs(previous_net), 1) if chart_valid and previous_net else None
    for row in upcoming:
        row['amount_display'] = finance_fx.format_money(row['amount_minor'], row['currency'])
    search = []
    if query:
        needle = query.casefold()
        for position, row in enumerate(reversed(finance.get_report_transactions(business_id, start, end, user_id))):
            label = row.get('description') or row.get('counterparty_name') or row.get('category_name') or 'Transaksi'
            if needle in ' '.join(str(row.get(k) or '') for k in ('description','counterparty_name','category_name')).casefold():
                search.append(dict(kind='transaction', label=label, page=position//10+1))
        search += [dict(kind='bill', label=r['name'], day=r['next_due_on']) for r in rules if needle in r['name'].casefold()]
        search += [dict(kind='payee', label=r['name']) for r in finance.list_payees(business_id, **actor) if needle in r['name'].casefold()]
    return dict(trend=trend, trend_months=trend_months, trend_start=trend_start+'-01', trend_end=end,
                chart_valid=chart_valid, chart_empty=chart_valid and not income and not expense,
                chart_divisor=int(finance_fx.minor_scale(currency)), net_change=net_change,
                income_display=money(income), expense_display=money(expense),
                net_display=money(None if income is None or expense is None else income-expense),
                net_minor=None if income is None or expense is None else income-expense,
                changes=changes, upcoming=upcoming, rules=rules,
                bills_display=money(converted([r for r in bills if r['status'] not in ('paid','void')], 'amount_minor')),
                payments_display=money(converted([r for r in bills if r['status']=='paid'], 'amount_minor')),
                invoice_display=money(converted(invoices, 'outstanding_minor')),
                search=search[:15], query=query)


def unavailable(month, trend_months):
    """Keep unavailable aggregates distinct from a genuine zero balance."""
    return dict(error='Data terlalu banyak untuk periode ini. Pilih periode yang lebih pendek.',
                trend=[], trend_months=trend_months, trend_start=month+'-01', trend_end=month+'-01',
                chart_valid=False, chart_empty=False, chart_divisor=100, net_change=None,
                income_display='Tidak tersedia', expense_display='Tidak tersedia', net_display='Tidak tersedia',
                net_minor=None, changes={'income':None,'expense':None}, upcoming=[], rules=[],
                bills_display='Tidak tersedia', payments_display='Tidak tersedia', invoice_display='Tidak tersedia',
                search=[], query='')
