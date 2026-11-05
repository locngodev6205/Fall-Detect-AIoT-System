"""Resumable, non-destructive local-to-Cloudinary migration and reconciliation CLI.

Run inside the backend container so the MEDIA_ROOT volume and restricted Neon worker
credential are available. Originals are retained. Default operation is a read-only dry run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from . import media_storage, pgdb as db


def _hash(path: Path) -> bytes:
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024),b''):
            digest.update(chunk)
    return digest.digest()


def _assets():
    result=[]
    with db.connect('auth') as conn:
        homes=[str(row['id']) for row in conn.execute('SELECT id FROM annha.homes WHERE archived_at IS NULL')]
    for home in homes:
        with db.connect('worker',home) as conn:
            result.extend((home,dict(row)) for row in conn.execute(
                "SELECT * FROM annha.media_assets WHERE status='ready' AND provider='local' ORDER BY created_at,id"))
    return result


def _eligible(root: Path, rows):
    eligible=[]
    counts={'local_ready':0,'eligible':0,'demo_skipped':0,'missing_key':0,
            'missing_file':0,'size_mismatch':0,'checksum_mismatch':0,'unsafe_key':0}
    for home,row in rows:
        counts['local_ready']+=1
        key=row.get('local_object_key')
        if str(row.get('upload_key','')).startswith('demo:'):
            counts['demo_skipped']+=1;continue
        if not key:
            counts['missing_key']+=1;continue
        if Path(key).name!=key:
            counts['unsafe_key']+=1;continue
        path=root/key
        if not path.is_file():
            counts['missing_file']+=1;continue
        if path.stat().st_size!=row['size_bytes']:
            counts['size_mismatch']+=1;continue
        digest=_hash(path)
        if row.get('sha256') and bytes(row['sha256'])!=digest:
            counts['checksum_mismatch']+=1;continue
        eligible.append((home,row,path,digest))
    counts['eligible']=len(eligible)
    return eligible,counts


def _commit_cloud_metadata(home,row,metadata,digest):
    with db.connect('worker',home,camera=row['camera_id']) as conn:
        current=conn.execute('SELECT * FROM annha.media_assets WHERE id=%s FOR UPDATE',(row['id'],)).fetchone()
        if not current or current['status']!='ready':
            raise RuntimeError('Asset changed during migration.')
        if current['provider']=='cloudinary':
            return False
        if current['provider']!='local' or current['size_bytes']!=metadata.size_bytes:
            raise RuntimeError('Asset metadata changed during migration.')
        conn.execute('''UPDATE annha.media_assets SET provider='cloudinary',provider_environment=%s,
            provider_asset_id=%s,public_id=%s,resource_type=%s,delivery_type=%s,provider_version=%s,
            sha256=%s,width=%s,height=%s,duration_s=%s
            WHERE id=%s AND provider='local' AND status='ready' ''',
            (metadata.provider_environment,metadata.provider_asset_id,metadata.public_id,
             metadata.resource_type,metadata.delivery_type,metadata.provider_version,digest,
             metadata.width,metadata.height,metadata.duration_s,row['id']))
        return True


def migrate(eligible,root: Path,limit=None,batch_size=10):
    provider=media_storage.CloudinaryStorage()
    target=eligible[:limit] if limit else eligible
    counts={'attempted':0,'migrated':0,'already_cloud':0,'failed':0,'provider_verified':0,
            'local_originals_retained':0}
    errors=[]
    for start in range(0,len(target),batch_size):
        batch=target[start:start+batch_size]
        verified=[]
        for home,row,path,digest in batch:
            counts['attempted']+=1
            try:
                metadata=provider.upload(path,str(row['id']),row['mime_type'])
                check={'public_id':metadata.public_id,'resource_type':metadata.resource_type,
                       'delivery_type':metadata.delivery_type,'provider_version':metadata.provider_version,
                       'mime_type':row['mime_type']}
                if metadata.size_bytes!=path.stat().st_size or not provider.verify(check,path.stat().st_size,digest):
                    raise RuntimeError('Provider verification failed.')
                counts['provider_verified']+=1
                if _commit_cloud_metadata(home,row,metadata,digest):
                    counts['migrated']+=1
                else:
                    counts['already_cloud']+=1
                counts['local_originals_retained']+=int(path.is_file())
                verified.append((home,row,metadata,digest))
            except Exception as error:
                counts['failed']+=1
                errors.append(type(error).__name__)
                # Fail closed at the first incomplete batch; a later run resumes from
                # provider='local' rows and reuses the deterministic provider public ID.
                return counts,sorted(set(errors))
        # Verify the committed first batch before continuing to the next one.
        for home,row,metadata,digest in verified:
            with db.connect('worker',home) as conn:
                saved=conn.execute("SELECT provider,provider_asset_id,public_id,provider_version FROM annha.media_assets WHERE id=%s",(row['id'],)).fetchone()
            if (not saved or saved['provider']!='cloudinary' or saved['provider_asset_id']!=metadata.provider_asset_id
                    or saved['public_id']!=metadata.public_id or saved['provider_version']!=metadata.provider_version):
                errors.append('MetadataVerificationFailed')
                return counts,sorted(set(errors))
    return counts,sorted(set(errors))


def cloudinary_inventory(provider, expected, admin_api=None):
    """Read app-scoped authenticated resources and compare their identities with Neon."""
    provider._configure()
    if admin_api is None:
        from cloudinary import api as admin_api
    prefix=f'annha/{provider.environment}/'
    expected=set(expected)
    found=set()
    counts={'image':0,'video':0,'raw':0}
    for resource_type in counts:
        cursor=None
        seen_cursors=set()
        while True:
            page=admin_api.resources(resource_type=resource_type,type=provider.delivery_type,
                prefix=prefix,max_results=500,next_cursor=cursor)
            resources=page.get('resources',[])
            for item in resources:
                counts[resource_type]+=1
                found.add((item.get('public_id'),item.get('resource_type'),item.get('type'),item.get('asset_id')))
            cursor=page.get('next_cursor')
            if not cursor:
                break
            if cursor in seen_cursors:
                raise RuntimeError('Cloudinary inventory pagination repeated a cursor.')
            seen_cursors.add(cursor)
    return {'cloud_inventory_status':'complete','cloud_provider_assets':sum(counts.values()),
        'cloud_assets_by_resource_type':counts,'cloudinary_orphans':len(found-expected),
        'cloud_metadata_missing_from_inventory':len(expected-found)}


def inventory(root: Path):
    """Metadata-only scheduled reconciliation; never deletes media or reads cloud bytes."""
    report={'cloud_assets_checked':0,'cloud_assets_missing':0,
        'local_assets_checked':0,'local_assets_missing':0,'local_size_mismatch':0,
        'cloud_inventory_status':'not_checked','cloud_provider_assets':None,
        'cloud_assets_by_resource_type':None,'cloudinary_orphans':None,
        'cloud_metadata_missing_from_inventory':None,'content_checksum_checked':False}
    with db.connect('auth') as conn:
        homes=[str(row['id']) for row in conn.execute('SELECT id FROM annha.homes WHERE archived_at IS NULL')]
    expected_cloud=[]
    for home in homes:
        with db.connect('worker',home) as conn:
            rows=conn.execute("SELECT * FROM annha.media_assets WHERE status='ready'").fetchall()
        for row in rows:
            if row['provider']=='local':
                report['local_assets_checked']+=1
                try:
                    path=media_storage.LocalStorage(root).path_for(row)
                    if row['size_bytes'] is not None and path.stat().st_size!=row['size_bytes']:
                        report['local_size_mismatch']+=1
                except media_storage.MediaStorageError:
                    report['local_assets_missing']+=1
            elif row['provider']=='cloudinary':
                report['cloud_assets_checked']+=1
                expected_cloud.append((row['public_id'],row['resource_type'],row['delivery_type'],row['provider_asset_id']))
    if expected_cloud:
        try:
            result=cloudinary_inventory(media_storage.CloudinaryStorage(),expected_cloud)
            report.update(result)
            report['cloud_assets_missing']=result['cloud_metadata_missing_from_inventory']
        except Exception:
            report['cloud_inventory_status']='unavailable'
    elif media_storage.cloudinary_configured():
        try:
            report.update(cloudinary_inventory(media_storage.CloudinaryStorage(),[]))
        except Exception:
            report['cloud_inventory_status']='unavailable'
    return report


def reconcile(root: Path):
    report={'cloud_assets_checked':0,'cloud_assets_missing':0,'cloud_checksum_mismatch':0,
            'local_assets_checked':0,'local_assets_missing':0,'local_checksum_mismatch':0,
            'unmapped_local_files':0,'cloud_inventory_status':'not_checked',
            'cloud_provider_assets':None,'cloud_assets_by_resource_type':None,
            'cloudinary_orphans':None,'cloud_metadata_missing_from_inventory':None}
    with db.connect('auth') as conn:
        homes=[str(row['id']) for row in conn.execute('SELECT id FROM annha.homes WHERE archived_at IS NULL')]
    mapped=set()
    expected_cloud=[]
    for home in homes:
        with db.connect('worker',home) as conn:
            rows=conn.execute("SELECT * FROM annha.media_assets WHERE status='ready'").fetchall()
        for row in rows:
            if row['local_object_key'] and Path(row['local_object_key']).name==row['local_object_key']:
                mapped.add(row['local_object_key'])
            if row['provider']=='local':
                report['local_assets_checked']+=1
                try:
                    path=media_storage.LocalStorage(root).path_for(row)
                    if row['size_bytes']!=path.stat().st_size: report['local_checksum_mismatch']+=1
                    elif row['sha256'] and bytes(row['sha256'])!=_hash(path): report['local_checksum_mismatch']+=1
                except media_storage.MediaStorageError:
                    report['local_assets_missing']+=1
            elif row['provider']=='cloudinary':
                report['cloud_assets_checked']+=1
                expected_cloud.append((row['public_id'],row['resource_type'],row['delivery_type'],row['provider_asset_id']))
                try:
                    provider=media_storage.CloudinaryStorage()
                    if not provider.verify(row,row['size_bytes'],bytes(row['sha256'])):
                        report['cloud_checksum_mismatch']+=1
                except media_storage.MediaNotFound:
                    report['cloud_assets_missing']+=1
                except Exception:
                    report['cloud_assets_missing']+=1
    try:
        report.update(cloudinary_inventory(media_storage.CloudinaryStorage(),expected_cloud))
    except Exception:
        # Reconciliation still reports per-row delivery checks if Admin API inventory is
        # unavailable; never log provider exceptions that could include request details.
        report['cloud_inventory_status']='unavailable'
    staging=root/'.staging'
    for path in root.iterdir() if root.exists() else ():
        if path.is_file() and path.name not in mapped:
            report['unmapped_local_files']+=1
    report['unmapped_staged_files']=sum(1 for p in staging.iterdir() if p.is_file()) if staging.is_dir() else 0
    return report


def save_report(path,mode,counts):
    report={'generated_at':datetime.now(timezone.utc).isoformat(),'mode':mode,'counts':counts}
    if path:
        target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        target.chmod(0o600)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true',help='read-only migration eligibility report (default)')
    mode.add_argument('--apply',action='store_true',help='upload eligible assets and update Neon metadata')
    mode.add_argument('--reconcile',action='store_true',help='compare Neon metadata with local/Cloudinary media')
    parser.add_argument('--limit',type=int,default=0,help='maximum assets to migrate; 0 means no limit')
    parser.add_argument('--batch-size',type=int,default=10)
    parser.add_argument('--backup-reference',help='Required recovery branch/snapshot identifier before --apply')
    parser.add_argument('--report',help='write aggregate JSON report; keep private because it describes account state')
    args=parser.parse_args(argv)
    if args.limit<0 or not 1<=args.batch_size<=100:
        parser.error('limit/batch-size is outside the permitted range')
    try:
        db.open_pools()
        if args.reconcile:
            counts=reconcile(db.MEDIA_ROOT);save_report(args.report,'reconcile',counts);return 0
        rows=_assets();eligible,counts=_eligible(db.MEDIA_ROOT,rows)
        if not args.apply:
            save_report(args.report,'dry_run',counts);return 0
        if not media_storage.cloudinary_configured():
            raise RuntimeError('Cloudinary is not configured.')
        if not args.backup_reference:
            raise RuntimeError('A confirmed Neon recovery branch/snapshot reference is required before --apply.')
        result,errors=migrate(eligible,db.MEDIA_ROOT,args.limit or None,args.batch_size)
        save_report(args.report,'apply',{**counts,**result,'errors':errors,
            'local_originals_retained':result['local_originals_retained'],
            'recovery_reference_provided':bool(args.backup_reference)})
        return 0 if not errors and result['failed']==0 else 1
    except Exception as error:
        print('Media migration stopped safely: '+type(error).__name__,file=sys.stderr)
        return 1
    finally:
        db.close_pools()


if __name__=='__main__':
    raise SystemExit(main())
