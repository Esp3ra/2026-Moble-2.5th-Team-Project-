"""Persistent local face templates. Raw camera images are never stored here."""
import json
import os
from pathlib import Path
import tempfile
import uuid

import numpy as np


def unit(vector):
    vector = np.asarray(vector, dtype=np.float32)
    if vector.shape != (128,) or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-6:
        raise ValueError('얼굴 특징값이 올바르지 않습니다.')
    return vector / np.linalg.norm(vector)


class IdentityStore:
    def __init__(self, path, threshold=0.5):
        self.path = Path(path)
        self.threshold = threshold
        self.people = []
        self.signature = None
        self.reload()

    def reload(self):
        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            self.people, self.signature = [], None
            return
        if signature == self.signature:
            return
        if stat.st_size > 2 * 1024 * 1024:
            raise ValueError('등록자 파일 크기가 올바르지 않습니다.')
        try:
            data = json.loads(self.path.read_text())
            if data['version'] != 1 or not isinstance(data['people'], list) or len(data['people']) > 50:
                raise ValueError()
            ids = set()
            for person in data['people']:
                if (not isinstance(person['id'], str) or person['id'] in ids or not person['id']
                        or not isinstance(person['name'], str) or not 1 <= len(person['name']) <= 24
                        or not 1 <= len(person['samples']) <= 12):
                    raise ValueError()
                ids.add(person['id'])
                for sample in person['samples']:
                    unit(sample)
            self.people, self.signature = data['people'], signature
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('등록자 파일을 읽을 수 없습니다. 기존 파일을 확인해 주세요.') from exc

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix='.identities-', dir=str(self.path.parent))
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'version': 1, 'people': self.people}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, str(self.path))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.signature = None
        self.reload()

    def enroll(self, name, samples):
        self.reload()
        name = name.strip()
        if not 1 <= len(name) <= 24 or any(ord(c) < 32 for c in name):
            raise ValueError('등록자 이름은 1~24자로 입력해 주세요.')
        if any(p['name'] == name for p in self.people):
            raise ValueError('같은 이름이 이미 등록돼 있습니다. 기존 등록을 삭제하거나 다른 이름을 사용해 주세요.')
        if len(self.people) >= 50 or not 5 <= len(samples) <= 12:
            raise ValueError('등록자 수 또는 얼굴 표본 수를 확인해 주세요.')
        vectors = [unit(s) for s in samples]
        if any(float(np.dot(vectors[0], v)) < self.threshold for v in vectors[1:]):
            raise ValueError('등록 중 얼굴이 바뀌었거나 영상이 불안정합니다. 다시 등록해 주세요.')
        person = {'id': uuid.uuid4().hex, 'name': name, 'samples': [v.tolist() for v in vectors]}
        previous = list(self.people)
        self.people.append(person)
        try:
            self.save()
        except Exception:
            self.people = previous
            raise
        return person['id']

    def remove(self, identifier):
        self.reload()
        previous = list(self.people)
        self.people = [p for p in self.people if p['id'] != identifier]
        if len(previous) == len(self.people):
            raise ValueError('등록자를 찾을 수 없습니다.')
        try:
            self.save()
        except Exception:
            self.people = previous
            raise

    def match(self, vector):
        query = unit(vector)
        scores = sorted([(float(np.dot(query, unit(np.mean(p['samples'], axis=0)))), p)
                         for p in self.people], key=lambda item: item[0], reverse=True)
        if not scores or scores[0][0] < self.threshold:
            return None
        if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.08:
            return None
        return {'id': scores[0][1]['id'], 'name': scores[0][1]['name'], 'score': scores[0][0]}
