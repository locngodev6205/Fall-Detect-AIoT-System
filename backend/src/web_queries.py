"""Bounded web responses; all SQL executes under the caller's existing RLS context."""
from datetime import datetime, timezone, timedelta
import math
from fastapi import HTTPException


def page_result(items,total,page,size):
    return dict(items=items,total=total,page=page,page_size=size,total_pages=max(1,math.ceil(total/size)))


def select_page(conn,columns,source,args,order,page,size,legacy=200):
    if not 1<=size<=100 or (page is not None and page<1):
        raise HTTPException(422,'Trang hoặc kích thước trang không hợp lệ.')
    total=conn.execute('SELECT count(*) AS n'+source,args).fetchone()['n'] if page is not None else 0
    sql='SELECT '+columns+source+' ORDER BY '+order
    values=list(args)
    if page is not None or legacy is not None:
        sql+=' LIMIT %s OFFSET %s';values += [size if page is not None else legacy,(page-1)*size if page is not None else 0]
    rows=conn.execute(sql,values).fetchall()
    return rows,total


def time_range(start=None,end=None,hours=None,default_hours=None):
    if hours is not None and not 1<=hours<=87600: raise HTTPException(422,'Khoảng thời gian không hợp lệ.')
    if hours and (start or end): raise HTTPException(422,'Chọn khoảng nhanh hoặc ngày bắt đầu/kết thúc.')
    def parse(value):
        if not value:return None
        try:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            if parsed.tzinfo is None:raise ValueError()
            return parsed.astimezone(timezone.utc)
        except (ValueError,TypeError): raise HTTPException(422,'Ngày giờ phải có múi giờ hợp lệ.') from None
    a,b=parse(start),parse(end)
    if a and b and a>=b:raise HTTPException(422,'Ngày kết thúc phải sau ngày bắt đầu.')
    if hours or (not a and not b and default_hours):
        b=datetime.now(timezone.utc);a=b-timedelta(hours=hours or default_hours)
    return a,b


def asset_usage(conn,items):
    ids=[item['id'] for item in items]
    used={}
    if ids:
        for row in conn.execute('''SELECT v.asset_id,r.id,r.name,r.enabled FROM annha.reminder_revisions v
          JOIN annha.reminders r ON r.id=v.reminder_id AND r.current_version=v.version
          WHERE v.asset_id=ANY(%s::uuid[]) AND r.deleted_at IS NULL ORDER BY r.name,r.id''',(ids,)):
            used.setdefault(str(row['asset_id']),[]).append({'id':str(row['id']),'name':row['name'],'enabled':row['enabled']})
    return [{**item,'used_by':used.get(str(item['id']),[]),'used_count':len(used.get(str(item['id']),[]))} for item in items]
