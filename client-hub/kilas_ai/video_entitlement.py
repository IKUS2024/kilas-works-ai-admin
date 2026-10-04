"""Video uses existing paid Premium capacity; no separate prices or free model calls."""
from . import usage, capacity, topups


def state(user):
    conn=usage._connect()
    try:
        now=usage._now()
        if usage._qa_quota_exempt(conn,user,now):return {'allowed':True,'reason':''}
        plan,start,end=usage._plan(conn,user,now)
        if plan=='FREE':return {'allowed':False,'reason':'missing','message':'Kuota Kilas Video belum tersedia','cta':'Lihat Paket'}
        period=usage._period(plan,start,end,'CHAT',now)[0]
        predicted=capacity.forecast('CHAT','EXPERT')
        remaining=capacity.allowance()-capacity.spent(conn,user,period,now)
        extra=sum(max(0,int(total)-int(spent)) for _,total,spent in topups._lots(conn,user,now))
        if remaining<predicted and extra<int(predicted*1000000):
            return {'allowed':False,'reason':'exhausted','message':'Kuota Kilas Video kamu habis','cta':'Tambah Kuota'}
        return {'allowed':True,'reason':''}
    finally:conn.close()
