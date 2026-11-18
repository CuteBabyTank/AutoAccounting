"""The documented setup invocation must reach the backup verification update."""
import json
from pathlib import Path
import subprocess
import sys


def test_setup_ca_invocations_reach_backup_update(tmp_path):
    source = Path(__file__).resolve().parents[2] / 'deploy' / 'setup-gcp.sh'
    if not source.exists():
        # The backend-only container mount has no deploy tree; parent can run this check from the repository.
        import pytest
        pytest.skip('deploy tree is not mounted in this backend container')
    deploy = tmp_path / 'deploy'
    deploy.mkdir()
    cert = tmp_path / 'backend' / 'certs' / 'supabase-prod-ca-2021.crt'
    cert.parent.mkdir(parents=True)
    cert.write_text('dummy CA')
    script = deploy / 'setup-gcp.sh'
    script.write_text(source.read_text().replace('/tmp/aa-', str(tmp_path / 'aa-')))
    (deploy / 'config.sh').write_text('\n'.join(f'{key}=dummy' for key in (
        'PROJECT_ID', 'REGION', 'REPO', 'UPLOADS_BUCKET', 'BACKUPS_BUCKET', 'BUILD_BUCKET')))
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    cli = bin_dir / 'gcloud'
    cli.write_text(f'#!{sys.executable}\n' + '''import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if 'describe' in args and 'AA_SUPABASE_CA' in args:
    sys.exit(0 if os.environ['EXISTING_CA'] == '1' else 1)
if 'create' in args and 'AA_SUPABASE_CA' in args:
    path = next(a.split('=', 1)[1] for a in args if a.startswith('--data-file='))
    sys.exit(0 if pathlib.Path(path).is_file() else 23)
if any('projectNumber' in a for a in args):
    print('123')
''')
    cli.chmod(0o755)
    openssl = bin_dir / 'openssl'
    openssl.write_text('#!/bin/sh\necho dummy\n')
    openssl.chmod(0o755)
    log = tmp_path / 'calls.jsonl'
    for cwd, invocation, existing in [
        (tmp_path, 'deploy/setup-gcp.sh', '0'), (tmp_path, 'deploy/setup-gcp.sh', '1'),
        (deploy, 'setup-gcp.sh', '0'), (tmp_path, str(script), '0'),
    ]:
        log.write_text('')
        result = subprocess.run(['/bin/bash', invocation], cwd=cwd, capture_output=True, text=True, timeout=20,
                                env={'PATH': f'{bin_dir}:/usr/bin:/bin', 'CALL_LOG': str(log),
                                     'EXISTING_CA': existing, 'HOME': str(tmp_path)})
        assert result.returncode == 0, result.stderr
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        update = next(args for args in calls if 'update' in args and 'aa-db-backup' in args)
        assert any('sslmode=verify-full' in arg for arg in update)
        assert any('/certs/supabase-ca.crt=AA_SUPABASE_CA:latest' in arg for arg in update)
