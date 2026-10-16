"""Read-only account group presentation; never changes balances or liability signs."""
import finance_service as finance
import finance_fx


def is_credit(label):
    return (label or '').strip().casefold() in ('credit','kredit')


def group_summaries(rows, labels, currency, fx):
    result={}
    for label in labels:
        selected=[row for row in rows if row['account_type_label']==label and row['is_active']]
        if not selected:continue
        native=finance.aggregate_account_balances_by_currency(selected)
        amount=finance_fx.convert_total(native,currency,fx)
        # Missing conversion cannot turn unlike currencies into one numeric total.
        display=(' · '.join(finance_fx.format_money(row['balance_minor'],row['currency']) for row in native)
                 if amount is None else finance_fx.format_money(amount,currency))
        result[label]=dict(display_total=display,total_minor=amount,native_totals=native,
                           is_credit=is_credit(label),count=len(selected))
    return result
