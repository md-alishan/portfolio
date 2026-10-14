"""Decrypt a repository payload into a temporary directory and run it privately."""
import base64
import io
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HEADER = b'PORTFOLIO_STATE_V1\x00'
FILES = ('increment_counter.py', 'test_increment_counter.py')


def decrypt_payload(payload, encoded_key):
    key = base64.b64decode(encoded_key, validate=True)
    if len(key) != 32 or not payload.startswith(HEADER):
        raise ValueError('Invalid encrypted package')
    nonce = payload[len(HEADER):len(HEADER) + 12]
    plaintext = AESGCM(key).decrypt(nonce, payload[len(HEADER) + 12:], HEADER)
    with zipfile.ZipFile(io.BytesIO(plaintext)) as archive:
        if sorted(archive.namelist()) != sorted(FILES):
            raise ValueError('Invalid package contents')
        return {name: archive.read(name) for name in FILES}


def execute(payload_path, encoded_key, validate_only=False):
    files = decrypt_payload(Path(payload_path).read_bytes(), encoded_key)
    env = os.environ.copy()
    env.pop('PORTFOLIO_SCRIPT_KEY', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    temporary_root = os.environ.get('RUNNER_TEMP')
    with tempfile.TemporaryDirectory(prefix='portfolio-state-', dir=temporary_root) as folder:
        private = Path(folder)
        for name, content in files.items():
            path = private / name
            path.write_bytes(content)
            path.chmod(0o600)
        # Capture output: tracebacks and test failures can contain source lines.
        tests = subprocess.run(
            [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', folder, '-p', 'test_*.py'],
            env=env, capture_output=True,
        )
        if tests.returncode:
            raise RuntimeError('Private validation failed; output suppressed')
        print('Private validation passed.')
        if not validate_only:
            result = subprocess.run(
                [sys.executable, '-B', str(private / 'increment_counter.py')],
                env=env, capture_output=True,
            )
            if result.returncode:
                raise RuntimeError('Private execution failed; output suppressed')
            print('State maintenance completed.')


def main():
    encoded_key = os.environ.pop('PORTFOLIO_SCRIPT_KEY', '')
    if not encoded_key:
        print('Required repository secret is missing.', file=sys.stderr)
        return 1
    try:
        execute(Path(__file__).with_name('portfolio-state.enc'), encoded_key,
                validate_only='--validate-only' in sys.argv[1:])
    except Exception:
        # Never include decrypted source, key material, or exception contents in logs.
        print('Private package validation or execution failed; details suppressed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
