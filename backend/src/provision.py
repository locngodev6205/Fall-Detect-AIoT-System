"""Provision and recover device credentials from the backend host."""
import argparse
import json
import os
from uuid import UUID

POSTGRES = os.getenv("DATABASE_BACKEND") == "postgres"
if POSTGRES:
    from . import pgdb as db
    from .pgservices import provision_device, refresh_device
else:
    from . import db
    from .services import provision_device, refresh_device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--name')
    operation.add_argument('--reissue-code', type=UUID, metavar='DEVICE_ID')
    operation.add_argument('--rotate-token', type=UUID, metavar='DEVICE_ID')
    args = parser.parse_args()

    if POSTGRES:
        db.open_pools()
    else:
        db.initialize()
    try:
        if args.name is not None:
            result = provision_device(args.name)
        else:
            result = refresh_device(
                str(args.rotate_token or args.reissue_code),
                rotate_token=args.rotate_token is not None,
            )
    except ValueError as error:
        parser.exit(1, f'{error}\n')
    finally:
        if POSTGRES:
            db.close_pools()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
