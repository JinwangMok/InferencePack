#!/usr/bin/env python3
"""Prepare local configuration without starting containers or disclosing secrets.

Only a deliberately small, literal subset of dotenv syntax is accepted. This
keeps validation consistent with Compose: no expansion, escapes, or multiline
values. Existing configuration is never replaced with newly generated secrets.
"""
import argparse
import base64
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = (
    'VLLM_API_KEY', 'NEXTAUTH_SECRET', 'SALT', 'ENCRYPTION_KEY',
    'REDIS_AUTH', 'POSTGRES_PASSWORD', 'CLICKHOUSE_PASSWORD', 'MINIO_ROOT_PASSWORD',
)
HEADER = 'OTEL_EXPORTER_OTLP_TRACES_HEADERS'


def read_env(path):
    if path.is_symlink():
        raise ValueError('.env must be a regular, private file, not a symlink')
    if not path.is_file():
        raise ValueError('.env is missing. For a NEW installation run scripts/configure_env.py --init; for existing data restore the original .env (see SECURITY.md)')
    if path.stat().st_mode & 0o077:
        raise ValueError('.env must be owner-only: review its ownership, then chmod 600 .env')
    text = path.read_text()
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)=(.*)', line)
        if not match:
            raise ValueError(f'Unsupported .env syntax at line {number}; use literal KEY=value entries')
        key, value = match.groups()
        if key in values:
            raise ValueError(f'Duplicate .env variable: {key}')
        value = value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'Invalid quoting at line {number}')
            value = value[1:-1]
        if any(c in value for c in ('$', '\\', '\n', '\r', '#', '"', "'")):
            raise ValueError(f'Unsupported expansion, escape, quote or inline comment at line {number}')
        values[key] = value
    return text, values


def validate(values, environ):
    effective = dict(values)
    effective.update(environ)  # Compose gives the calling environment precedence.
    for name in SECRET_NAMES:
        value = effective.get(name, '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{32,}', value):
            raise ValueError(f'{name} must be a unique secret of at least 32 URL-safe characters; see SECURITY.md')
        if ('change-me' in value.lower() or 'your-' in value.lower()
                or len(set(value)) < 4):
            raise ValueError(f'{name} uses a placeholder or weak value; see SECURITY.md')
    if len({effective[name] for name in SECRET_NAMES}) != len(SECRET_NAMES):
        raise ValueError('Use different secrets for each service')
    if not re.fullmatch(r'[0-9a-fA-F]{64}', effective['ENCRYPTION_KEY']):
        raise ValueError('ENCRYPTION_KEY must be 64 hexadecimal characters; preserve existing encryption keys during migration')
    if any(effective.get(k) for k in ('LANGFUSE_INIT_USER_EMAIL', 'LANGFUSE_INIT_USER_PASSWORD', 'LANGFUSE_INIT_USER_NAME')):
        raise ValueError('Legacy LANGFUSE_INIT_USER_* settings found; complete the account migration in SECURITY.md before removing these entries')
    if 'WEBUI_AUTH' in effective and effective['WEBUI_AUTH'].lower() != 'true':
        raise ValueError('WEBUI_AUTH must be true; authentication is required')
    for name, default in [('ENABLE_SIGNUP', 'false'), ('AUTH_DISABLE_SIGNUP', 'true')]:
        if effective.get(name, default) not in ('true', 'false'):
            raise ValueError(f'{name} must be true or false')
    pk, sk = effective.get('LANGFUSE_PUBLIC_KEY', ''), effective.get('LANGFUSE_SECRET_KEY', '')
    if bool(pk) != bool(sk):
        raise ValueError('Set both Langfuse API keys, or leave both empty until local setup is complete')
    for key in (pk, sk):
        if key and (not re.fullmatch(r'[A-Za-z0-9_-]+', key) or 'xxxx' in key.lower()):
            raise ValueError('Langfuse API keys must be literal values, not placeholders')
    header = ''
    if pk:
        token = base64.b64encode(f'{pk}:{sk}'.encode()).decode()
        header = f'Authorization=Basic {token},x-langfuse-ingestion-version=4'
    if HEADER in environ and environ[HEADER] != header:
        raise ValueError('Unset the exported OTEL trace header; it must match the effective Langfuse keys')
    return header


def initialize(path):
    # O_EXCL also refuses existing files and symlinks; never reset an installation.
    values = {name: secrets.token_hex(32) for name in SECRET_NAMES}
    lines = ['# Private InferencePack configuration. Do not commit or share.',
             '# Keep a secure backup, especially ENCRYPTION_KEY and SALT.', 'HF_TOKEN=']
    lines += [f'{key}={value}' for key, value in values.items()]
    lines += ['ENABLE_SIGNUP=false', 'AUTH_DISABLE_SIGNUP=true',
              'NEXTAUTH_URL=http://localhost:3000', 'LANGFUSE_PUBLIC_KEY=',
              'LANGFUSE_SECRET_KEY=',
              'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://langfuse-web:3000/api/public/otel/v1/traces',
              'OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf']
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('\n'.join(lines) + '\n')


def prepare(path, text, header):
    lines = [line for line in text.splitlines() if not line.strip().startswith(HEADER + '=')]
    updated = '\n'.join(lines + [f'{HEADER}={header}']) + '\n'
    if updated == text:
        return
    fd, tmp = tempfile.mkstemp(prefix='.env.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(updated)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--init', action='store_true', help='NEW installations only: create a private .env; never overwrite')
    mode.add_argument('--check', action='store_true', help='validate effective configuration without changing it')
    mode.add_argument('--prepare', action='store_true', help='validate and refresh the derived OTEL header only')
    args = parser.parse_args()
    path = ROOT / '.env'
    try:
        if args.init:
            initialize(path)
            print('Created private .env. Follow SECURITY.md for local first-user setup.')
        else:
            text, values = read_env(path)
            header = validate(values, os.environ)
            if args.prepare:
                prepare(path, text, header)
            print('Security configuration validated. No secrets printed.')
    except (ValueError, OSError) as error:
        # Filesystem errors do not include file contents; validation never quotes values.
        print(f'Configuration blocked: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
