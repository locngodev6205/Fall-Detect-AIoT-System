"""Remove fixture presentation prefixes without deleting records or changing credentials."""
import json
from pathlib import Path
import re
import ssl
import sys
import psycopg
from psycopg import sql
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from backend.src.demo_metadata import DEMO_CAMERAS

pattern=r'(?i)^(demo[\s·:_-]+)+|[\s·:_-]+demo$'
settings=dotenv_values(ROOT/'.env');url=settings['DATABASE_URL_UNPOOLED']
counts={}
with psycopg.connect(url,sslmode='verify-full',sslrootcert=ssl.get_default_verify_paths().cafile) as conn:
    for schema,table in [('annha_private','users'),('annha','homes'),('annha','rooms'),('annha','cameras'),('annha','reminders'),('annha','media_assets')]:
        statement=sql.SQL('UPDATE {}.{} SET name=regexp_replace(name,%s,\'\',\'g\') WHERE name ~ %s').format(sql.Identifier(schema),sql.Identifier(table))
        counts[table]=conn.execute(statement,(pattern,pattern)).rowcount
    for table in ('reminders','media_assets'):
        conn.execute(sql.SQL("UPDATE annha.{} SET name=regexp_replace(name,'(?i)^smoke[\\s·:_-]+','','g') WHERE camera_id=ANY(%s::uuid[]) AND name ~* '^smoke[\\s·:_-]+'").format(sql.Identifier(table)),(list(DEMO_CAMERAS),))
    conn.execute("UPDATE annha.events SET reason=CASE kind WHEN 'fall' THEN 'Cần kiểm tra tư thế và tình trạng người trong phòng.' WHEN 'immobility' THEN 'Đã ghi nhận vận động trở lại trong khu vực theo dõi.' ELSE 'Các chỉ số môi trường đã trở lại ngưỡng cấu hình.' END WHERE camera_id=ANY(%s::uuid[]) AND (source_id IN ('demo:fall','demo:immobility','demo:environment') OR (source_id ~ '^(smoke:|mqtt-smoke:)' AND reason ~* '^smoke'))",(list(DEMO_CAMERAS),))
    conn.execute("UPDATE annha.event_updates u SET payload=jsonb_set(u.payload,'{reason}',to_jsonb(e.reason),true) FROM annha.events e WHERE e.id=u.event_id AND e.camera_id=ANY(%s::uuid[]) AND (e.source_id IN ('demo:fall','demo:immobility','demo:environment') OR e.source_id ~ '^(smoke:|mqtt-smoke:)')",(list(DEMO_CAMERAS),))
    conn.execute("UPDATE annha.reminder_executions SET detail='Đã ghi nhận phát theo lịch.' WHERE camera_id=ANY(%s::uuid[]) AND occurrence_key='demo-occurrence'",(list(DEMO_CAMERAS),))
# Preserve the existing account email/password and all device tokens.
p=ROOT/'.secrets/demo-credentials.json'
if p.exists():
    value=json.loads(p.read_text())
    for group in ('accounts','devices'):
        for item in value[group]: item['name']=re.sub(pattern,'',item.get('name','')).strip()
    temp=p.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));temp.chmod(0o600);temp.replace(p)
print('Presentation labels updated:',counts)
print('All identifiers, ownership, emails, password hashes and device credentials retained.')
