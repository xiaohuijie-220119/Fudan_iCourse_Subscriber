"""Encrypted, incremental persistence independent of legacy data branch."""
import gzip
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from cloud_notes.crypto import encrypt, decrypt, blob_name
from cloud_notes.github import GitHub

BRANCH = 'cloud-workspace-v1'

def safe_path(root, relative):
    if not isinstance(relative,str) or '\\' in relative or ':' in relative:
        raise ValueError('文件路径无效')
    path = (Path(root)/relative).resolve()
    if not path.is_relative_to(Path(root).resolve()) or path == Path(root).resolve():
        raise ValueError('文件路径无效')
    return path

class Store:
    def __init__(self, root, api=None, key=None):
        self.root = Path(root)
        self.api = api or GitHub(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_TOKEN'])
        self.key = key or os.environ['WORKSPACE_KEY']
        self.manifest = {'version':1, 'documents':[], 'status':{}}
        self.known = {}

    def restore(self):
        self.known = self.api.files(BRANCH)
        if not self.known: return
        if 'workspace.enc' not in self.known: raise RuntimeError('云端清单缺失，停止运行以保护历史进度')
        self.manifest = json.loads(decrypt(self.api.blob(self.known['workspace.enc']), self.key, 'manifest'))
        database = self.manifest.get('database')
        if database:
            raw = decrypt(self.api.blob(self.known[database]),self.key,'database')
            dest = self.root/'data/icourse.db'; dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(gzip.decompress(raw))

    def save(self, db, status):
        updates = {}
        existing = {d['path']:d for d in self.manifest['documents']}
        for path in (self.root/'documents').glob('*/*.docx'):
            relative = path.relative_to(self.root/'documents').as_posix()
            if relative in existing: continue
            identity = 'document:' + relative
            blob = 'files/' + blob_name(identity)
            updates[blob] = encrypt(path.read_bytes(), self.key, identity)
            existing[relative] = {'path':relative, 'blob':blob, 'size':path.stat().st_size}
        self.manifest['documents'] = list(existing.values())
        if db is not None:
            from cloud_notes.lecture_status import snapshot
            self.manifest['lectures']=snapshot(db,documents=self.manifest['documents'])
            with tempfile.TemporaryDirectory() as directory:
                snapshot = Path(directory)/'state.db'
                copy = sqlite3.connect(snapshot)
                with db._lock: db.conn.backup(copy)
                copy.close()
                updates['database.enc'] = encrypt(gzip.compress(snapshot.read_bytes()), self.key, 'database')
                self.manifest['database'] = 'database.enc'
        self.manifest['status'] = status
        updates['workspace.enc'] = encrypt(json.dumps(self.manifest,ensure_ascii=False).encode(),self.key,'manifest')
        self.api.commit(BRANCH, updates, 'Save encrypted course checkpoint')
