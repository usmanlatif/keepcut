#!/usr/bin/env python3
"""Check product text for protected terms without displaying those terms."""

import argparse
import csv
import os
from pathlib import Path
import subprocess
import sys
import unicodedata


def normalize(text):
    """Return normalized text and the source line for each output character."""
    characters, lines = [], []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        for char in unicodedata.normalize('NFKC', line).casefold():
            if char.isalnum():
                characters.append(char)
                lines.append(number)
            elif characters and characters[-1] != ' ':
                characters.append(' ')
                lines.append(number)
    if characters and characters[-1] == ' ':
        characters.pop()
        lines.pop()
    return ''.join(characters), lines


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def files(root, staged):
    if staged:
        paths = git(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMRT',
                    '-z', '--', 'app/').split(b'\0')
        for raw_path in paths:
            if raw_path:
                path = os.fsdecode(raw_path)
                yield path, git(root, 'show', ':' + path)
    else:
        app = root / 'app'
        if not app.is_dir():
            raise ValueError('Missing app')
        for path in sorted(app.rglob('*')):
            if path.is_file():
                yield str(path.relative_to(root)), path.read_bytes()


def decode(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16')
    if b'\x00' in data:
        return None
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('latin-1')


def main():
    root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--golden', type=Path,
                        default=root / 'evaluation/golden_set.csv')
    parser.add_argument('--staged', action='store_true',
                        help='Scan staged app files using their index content')
    args = parser.parse_args()
    try:
        with args.golden.open(encoding='utf-8-sig', newline='') as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames or 'search_term' not in reader.fieldnames:
                raise ValueError('Missing column')
            terms = [normalize(row.get('search_term') or '')[0] for row in reader]
            terms = [term for term in terms if term]
        if not terms:
            raise ValueError('No terms')
        matches = set()
        for path, data in files(root, args.staged):
            content = decode(data)
            if content is None:
                continue
            text, lines = normalize(content)
            padded = ' ' + text + ' '
            for term in terms:
                needle = ' ' + term + ' '
                start = padded.find(needle)
                while start != -1:
                    matches.add((path, lines[start]))
                    start = padded.find(needle, start + 1)
    except (OSError, ValueError, csv.Error, subprocess.CalledProcessError):
        print('Leak check could not complete: verify the CSV, app files, and Git index.',
              file=sys.stderr)
        return 1
    if matches:
        print('Golden-set term found at:')
        for path, line in sorted(matches):
            print(f'{path}:{line}')
        return 1
    print(f'Leak check passed: checked {len(terms)} terms.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
