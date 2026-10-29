"""Administrator-only local provisioning; device token is printed once, never exposed in UI."""
import argparse
import json
import os
if os.getenv("DATABASE_BACKEND")=="postgres":
    from . import pgdb as db
    from .pgservices import provision_device
else:
    from . import db
    from .services import provision_device

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--name',required=True)
    args=parser.parse_args()
    db.open_pools() if os.getenv("DATABASE_BACKEND")=="postgres" else db.initialize()
    print(json.dumps(provision_device(args.name),ensure_ascii=False,indent=2))
