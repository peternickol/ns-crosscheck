#!/usr/bin/env python3
"""Install or update NS Cross-check directly from its GitHub repository."""
# MIT License
#
# Copyright (c) 2026 Peter Nickol
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import ast
import io
import os
from pathlib import Path
import shlex
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

APP_ID = 'ns-crosscheck-update'
VERSION = '0.1.0'
MIN_PYTHON = (3, 10)
REPOSITORY = 'peternickol/ns-crosscheck'
SOURCE_URL = f'https://codeload.github.com/{REPOSITORY}/zip/refs/heads/master'
MAX_DOWNLOAD = 8 * 1024 * 1024
MAX_PROGRAM = 2 * 1024 * 1024
PROGRAMS = {'ns-crosscheck': 'ns-crosscheck', 'ns-crosscheck-update': 'install.py'}


def program_version(data, name):
    """Inspect metadata without executing downloaded or existing programs."""
    try:
        tree = ast.parse(data)
        values = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        values[target.id] = node.value.value
        version = values.get('VERSION')
        if values.get('APP_ID') != name or not isinstance(version, str) or not version:
            raise ValueError('Missing program identity or version')
        return version
    except (SyntaxError, UnicodeError, ValueError, TypeError) as error:
        raise RuntimeError(f'{name} is not a recognized NS Cross-check program: {error}') from None


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': f'ns-crosscheck-installer/{VERSION}'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if not response.geturl().startswith('https://'):
                raise RuntimeError('Refusing a download redirected away from HTTPS.')
            data = response.read(MAX_DOWNLOAD + 1)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 404:
            raise RuntimeError('Repository download not found. Check that peternickol/ns-crosscheck and its master branch are public.') from None
        if error.code in (403, 429):
            raise RuntimeError('GitHub refused the request or its rate limit was reached. Try again later.') from None
        raise RuntimeError(f'Download failed: HTTP {error.code}') from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f'Download failed: {error}') from None
    if len(data) > MAX_DOWNLOAD:
        raise RuntimeError('Download exceeded the expected size limit.')
    return data


def repository_payload():
    """Read both programs from one repository snapshot without extracting files."""
    data = download(SOURCE_URL)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            payload = {}
            for name, source in PROGRAMS.items():
                member = archive.getinfo(f'ns-crosscheck-master/{source}')
                if member.file_size > MAX_PROGRAM:
                    raise ValueError(f'{source} exceeds the expected size limit')
                payload[name] = archive.read(member)
    except (zipfile.BadZipFile, KeyError, ValueError) as error:
        raise RuntimeError(f'Invalid repository download: {error}') from None
    return checked_payload(payload)


def checked_payload(payload):
    versions = {program_version(data, name) for name, data in payload.items()}
    if len(versions) != 1:
        raise RuntimeError('The application and installer have different versions.')
    return versions.pop(), payload


def local_payload(directory):
    directory = Path(directory).expanduser().resolve()
    payload = {}
    for name, source in PROGRAMS.items():
        path = directory / source
        if not path.is_file():
            raise RuntimeError(f'Missing {source} in {directory}.')
        payload[name] = path.read_bytes()
    return checked_payload(payload)


def install(bin_dir, version, payload):
    bin_dir = Path(bin_dir).expanduser().resolve()
    targets = {name: bin_dir / name for name in PROGRAMS}
    for name, target in targets.items():
        if target.is_symlink():
            raise RuntimeError(f'Refusing to replace a symlink: {target}')
        if target.exists():
            if not target.is_file():
                raise RuntimeError(f'Not a regular file: {target}')
            if any((parent / '.git/HEAD').is_file() or (parent / '.git').is_file() for parent in (bin_dir, *bin_dir.parents)):
                raise RuntimeError(f'Refusing to overwrite a source checkout: {target}')
            program_version(target.read_bytes(), name)
    if all(target.is_file() and target.read_bytes() == payload[name] and os.access(target, os.X_OK)
           for name, target in targets.items()):
        print(f'NS Cross-check {version} is already installed in {bin_dir}.')
        return
    bin_dir.mkdir(parents=True, exist_ok=True)
    staged = {}
    previous = {name: (target.read_bytes(), target.stat().st_mode & 0o777) if target.exists() else None
                for name, target in targets.items()}
    replaced = []
    try:
        for name, data in payload.items():
            with tempfile.NamedTemporaryFile(prefix=f'.{name}-', dir=bin_dir, delete=False) as stream:
                staged[name] = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            staged[name].chmod(0o755)
        for name in PROGRAMS:
            os.replace(staged[name], targets[name])
            replaced.append(name)
    except BaseException:
        for name in reversed(replaced):
            if previous[name] is None:
                targets[name].unlink()
            else:
                data, mode = previous[name]
                with tempfile.NamedTemporaryFile(prefix='.ns-crosscheck-restore-', dir=bin_dir, delete=False) as stream:
                    restore = Path(stream.name)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    restore.chmod(mode)
                    os.replace(restore, targets[name])
                finally:
                    restore.unlink(missing_ok=True)
        raise
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
    print(f'Installed NS Cross-check {version} in {bin_dir}.')
    print('Run: ns-crosscheck example.com --old ns1.old.example --new ns1.new.example')
    print('Update: ns-crosscheck-update (or ns-crosscheck --update)')
    path_entries = {Path(entry).expanduser().resolve() for entry in os.get_exec_path() if entry}
    if bin_dir not in path_entries:
        print(f'Add this directory to your PATH: export PATH={shlex.quote(str(bin_dir))}:"$PATH"')


def default_bin_dir(script):
    script = Path(script).resolve()
    sibling = script.with_name('ns-crosscheck')
    if script.name == 'ns-crosscheck-update' and sibling.is_file() and os.access(sibling, os.X_OK):
        try:
            program_version(sibling.read_bytes(), 'ns-crosscheck')
        except (OSError, RuntimeError):
            pass
        else:
            return script.parent
    return Path.home() / '.local/bin'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', default=str(default_bin_dir(__file__)), help='Installation directory (default: ~/.local/bin, or this updater\'s directory)')
    parser.add_argument('--from-dir', help='Install from a local source checkout without downloading')
    args = parser.parse_args()
    if sys.version_info < MIN_PYTHON:
        parser.error('Python 3.10 or newer is required.')
    if os.name != 'posix':
        parser.error('The installer supports Linux and macOS. On Windows, use WSL.')
    print('Preparing local files…' if args.from_dir else 'Downloading NS Cross-check from GitHub…', flush=True)
    version, payload = local_payload(args.from_dir) if args.from_dir else repository_payload()
    install(args.bin_dir, version, payload)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, RuntimeError) as error:
        print(f'ns-crosscheck installer: {error}', file=sys.stderr)
        raise SystemExit(1)
