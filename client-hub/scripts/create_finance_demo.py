#!/usr/bin/env python3
"""Explicit disposable SQLite demo. Refuses production, PostgreSQL, and existing databases."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True)
    parser.add_argument('--allow-disposable-fixtures',action='store_true')
    args=parser.parse_args()
    path=Path(args.db).resolve()
    production=any(os.environ.get(k,'').lower()=='production' for k in ('APP_ENV','CLIENT_HUB_ENV')) or bool(os.environ.get('RENDER'))
    password=os.environ.get('DEMO_FIXTURE_PASSWORD','')
    if production or os.environ.get('DATABASE_URL') or not args.allow_disposable_fixtures or path.exists() or not path.name.startswith('kilas-demo-') or len(password)<12:
        parser.error('Gunakan database SQLite BARU bernama kilas-demo-*, tanpa konfigurasi production/PostgreSQL, flag eksplisit dan DEMO_FIXTURE_PASSWORD minimal 12 karakter.')
    path.parent.mkdir(parents=True,exist_ok=True)
    os.environ['CLIENT_HUB_DB_PATH']=str(path)
    os.environ['CLIENT_HUB_ENV']='development'
    os.environ['KILAS_FINANCE_ACCESS_MODE']='self_service'
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import db,repo,security,catalog_service
    import finance_entitlements as e
    from datetime import timedelta
    db.init_schema();catalog_service.seed_catalog_if_needed()
    owner=repo.create_user('customer.finance@example.test',security.hash_password(password),role='CLIENT_OWNER')
    repo.create_user('admin.finance@example.test',security.hash_password(password),role='KILAS_ADMIN')
    for label,status in (('Trial','trial'),('Aktif','active'),('Kedaluwarsa','expired')):
        bid=repo.create_business(owner,'UJI LOKAL Finance '+label,package='NONE')
        e.setup(bid,owner,'Kas','CASH',0)
        start=e.now();end=start+timedelta(days=7)
        if status=='trial':e.start_trial(bid,owner)
        else:
            if status=='expired':start-=timedelta(days=8);end=start+timedelta(days=7)
            with db.app_purchase_transaction(bid,None):
                db.execute('INSERT INTO finance_entitlements (business_id,trial_started_at,trial_until,paid_until,updated_at) VALUES (?,?,?,?,?)',
                           (bid,start.isoformat() if status=='expired' else None,end.isoformat() if status=='expired' else None,(start+timedelta(days=30)).isoformat() if status=='active' else None,e.now().isoformat()))
                repo.write_audit(owner,bid,'FINANCE_DISPOSABLE_TEST_FIXTURE_CREATED','')
    print('Fixture lokal selesai. Akun customer.finance@example.test dan admin.finance@example.test memakai DEMO_FIXTURE_PASSWORD yang Anda tentukan. Data aktif merupakan fixture uji, bukan pembayaran nyata.')


if __name__=='__main__':main()
