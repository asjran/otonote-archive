"""Digest-checked reusable conversion outputs; recipes change on encoder changes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from tools.global_remote_sync import file_hash, read_json, write_json


def directory(source_sha, recipe):
    root = Path(os.environ.get('OURNOTES_CONVERSION_CACHE', str(Path(__file__).resolve().parents[1] / 'output/global-update-workflow/conversions')))
    key = hashlib.sha256((recipe + ':' + source_sha).encode()).hexdigest()
    return root / key[:2] / key


def restore(source_sha, recipe, target):
    root = directory(source_sha, recipe)
    if not (root / 'receipt.json').exists(): return False
    record = read_json(root / 'receipt.json')
    blob = root / 'content'
    if record['sourceSha256'] != source_sha or record['recipe'] != recipe or not blob.is_file() or file_hash(blob) != record['sha256']:
        raise ValueError('conversion cache integrity mismatch')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(blob, target)
    return True


def save(source_sha, recipe, source):
    root = directory(source_sha, recipe)
    if (root / 'receipt.json').exists(): return
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.conversion-', dir=root.parent) as folder:
        stage = Path(folder) / 'entry'; stage.mkdir()
        shutil.copyfile(source, stage / 'content')
        write_json(stage / 'receipt.json', {'sourceSha256': source_sha, 'recipe': recipe, 'sha256': file_hash(stage / 'content')})
        if not root.exists(): stage.rename(root)
