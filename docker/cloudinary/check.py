"""Cloudinary setup/checks. Only --setup-preset writes config; never uploads/deletes media."""
import argparse
import base64
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import urllib.parse


def load_config(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ValueError('Config must use KEY=value lines.')
        key, value = line.split('=', 1)
        if key.strip() in result:
            raise ValueError('Duplicate configuration key.')
        result[key.strip()] = value.strip()
    for key in ('CLOUDINARY_CLOUD_NAME','CLOUDINARY_API_KEY','CLOUDINARY_API_SECRET','CLOUDINARY_UPLOAD_PRESET'):
        if not result.get(key) or 'REPLACE_' in result[key]:
            raise ValueError('Fill the ignored Cloudinary config before checking.')
    for key in ('CLOUDINARY_CLOUD_NAME','CLOUDINARY_UPLOAD_PRESET'):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', result[key]):
            raise ValueError('Cloud name and preset must be safe path identifiers.')
    if result.get('CLOUDINARY_DELIVERY_TYPE') != 'authenticated':
        raise ValueError('Family media must use authenticated delivery.')
    if not 0 < int(result.get('CLOUDINARY_MAX_FILE_BYTES', '0')) <= 26214400:
        raise ValueError('File limit must be positive and at most 25 MiB.')
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None  # Do not forward an Authorization header to a redirected host.


def get_admin(config, resource, data=None):
    credential = f"{config['CLOUDINARY_API_KEY']}:{config['CLOUDINARY_API_SECRET']}".encode()
    request = urllib.request.Request(
        f"https://api.cloudinary.com/v1_1/{config['CLOUDINARY_CLOUD_NAME']}/{resource}",
        headers={'Authorization':'Basic ' + base64.b64encode(credential).decode()},
        data=urllib.parse.urlencode(data).encode() if data is not None else None,
    )
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
        result = json.loads(response.read(131072))
        if not isinstance(result, dict):
            raise ValueError('Unexpected Cloudinary response shape.')
        return result


def validate_preset(preset):
    settings = preset.get('settings', {})
    if preset.get('unsigned') is not False or not isinstance(settings, dict) or settings.get('type') != 'authenticated':
        raise ValueError('Preset must be signed and use authenticated delivery.')


def setup_preset(config):
    resource = 'upload_presets/' + config['CLOUDINARY_UPLOAD_PRESET']
    try:
        existing = get_admin(config, resource)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        validate_preset(existing)
        print('PASS: existing secure preset kept unchanged.')
        return
    get_admin(config, 'upload_presets', data={
        'name':config['CLOUDINARY_UPLOAD_PRESET'], 'unsigned':'false',
        'type':'authenticated', 'overwrite':'false',
        'allowed_formats':'jpg,jpeg,png,mp4,webm,mp3,wav,ogg',
    })
    validate_preset(get_admin(config, resource))
    print('PASS: signed/authenticated preset created. No media uploaded.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/run/secrets/cloudinary.env')
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--ping', action='store_true')
    parser.add_argument('--check-preset', action='store_true')
    parser.add_argument('--setup-preset', action='store_true', help='Create the named secure preset only if absent; never overwrite an existing preset.')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.validate_only and (args.ping or args.check_preset or args.setup_preset):
            raise ValueError('Choose validation only OR an online read-only check.')
        if args.ping or args.check_preset or args.setup_preset:
            if get_admin(config, 'ping').get('status') != 'ok':
                raise ValueError('Cloudinary did not return a successful ping.')
            print('PASS: Cloudinary credentials accepted (read-only ping).')
        if args.check_preset:
            preset = get_admin(config, 'upload_presets/' + config['CLOUDINARY_UPLOAD_PRESET'])
            validate_preset(preset)
            print('PASS: preset is signed and authenticated. Upload limits still require server enforcement.')
        if args.setup_preset:
            setup_preset(config)
        if not args.ping and not args.check_preset and not args.setup_preset:
            print('PASS: local config is structurally valid. No cloud connection was made.')
        return 0
    except urllib.error.HTTPError as error:
        print(f'Cloudinary check failed: HTTP {error.code}. No response body or credential logged.', file=sys.stderr)
    except (OSError, ValueError, json.JSONDecodeError):
        print('Cloudinary check failed: config, network or response is invalid. Check the setup guide; secrets are not logged.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
