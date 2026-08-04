#!/usr/bin/env python3
"""Build the Autodesk App Store .bundle package under dist/.

Run from the repo root:
  python3 scripts/build_store_bundle.py

Copies runtime add-in files into:
  dist/LamelloPSystemCNC.bundle/PackageContents.xml
  dist/LamelloPSystemCNC.bundle/Contents/...
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDIN_SRC = ROOT / 'LamelloPSystemCNC'
BUNDLE_NAME = 'LamelloPSystemCNC.bundle'
DIST_BUNDLE = ROOT / 'dist' / BUNDLE_NAME
CONTENTS = DIST_BUNDLE / 'Contents'

# Keep ProductCode in sync with LamelloPSystemCNC.manifest "id".
UPGRADE_CODE = '{ec90305f-5701-4557-a54e-7890ee00979a}'

EXCLUDE_DIR_NAMES = {
    '__pycache__',
    '.vscode',
    '.git',
}
EXCLUDE_FILE_NAMES = {
    'ARCHITECTURE.md',
    'clamex_settings.json',
    '.DS_Store',
}
EXCLUDE_SUFFIXES = {'.pyc', '.pyo'}


def load_manifest() -> dict:
    path = ADDIN_SRC / 'LamelloPSystemCNC.manifest'
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


def should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in EXCLUDE_DIR_NAMES for part in rel.parts):
        return True
    if path.is_file():
        if path.name in EXCLUDE_FILE_NAMES:
            return True
        if path.suffix in EXCLUDE_SUFFIXES:
            return True
    return False


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    for item in src.rglob('*'):
        if should_skip(item, src):
            continue
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def write_package_contents(manifest: dict) -> None:
    product_code = manifest['id']
    if not product_code.startswith('{'):
        product_code = '{' + product_code + '}'
    description = manifest.get('description', {}).get('', '')
    version = manifest.get('version', '1.0.0')
    author = manifest.get('author', 'NatureBoy Carpentry')

    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage
    SchemaVersion="1.0"
    AutodeskProduct="Fusion360"
    Name="Lamello P-System CNC"
    Description="{description}"
    AppVersion="{version}"
    ProductCode="{product_code}"
    UpgradeCode="{UPGRADE_CODE}"
    Author="{author}"
    Icon="./Contents/resources/64x64.png"
    HelpFile="./Contents/Help/QuickStart.html"
>
  <CompanyDetails
      Name="{author}"
  />
  <Components>
    <ComponentEntry ModuleName="./Contents/LamelloPSystemCNC.manifest"/>
  </Components>
</ApplicationPackage>
'''
    DIST_BUNDLE.mkdir(parents=True, exist_ok=True)
    (DIST_BUNDLE / 'PackageContents.xml').write_text(xml, encoding='utf-8')


def main() -> int:
    if not ADDIN_SRC.is_dir():
        print(f'Add-in source not found: {ADDIN_SRC}', file=sys.stderr)
        return 1

    manifest = load_manifest()
    if manifest.get('editEnabled') is not False:
        print('Warning: manifest editEnabled should be false for store builds.', file=sys.stderr)

    product_id = manifest.get('id', '')
    # Basic UUID shape check (8-4-4-4-12 hex)
    import re
    if not re.fullmatch(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        product_id,
    ):
        print(f'Error: manifest id is not a valid UUID: {product_id}', file=sys.stderr)
        return 1

    write_package_contents(manifest)
    copy_tree(ADDIN_SRC, CONTENTS)

    print(f'Built {DIST_BUNDLE}')
    print(f'  version {manifest.get("version")}')
    print(f'  ProductCode {{{product_id}}}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
