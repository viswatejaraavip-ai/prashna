"""Tiny in-memory stand-in for google.cloud.firestore.Client (only what the
features workstream uses: documents, subcollections, set/merge/update/delete,
where('==') on dotted paths, limit, start_after, stream)."""

import copy
import uuid


def _get_path(d, dotted):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)


class Snapshot:
    def __init__(self, ref, data):
        self.reference = ref
        self.id = ref.id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self._data) if self._data is not None else None


class DocRef:
    def __init__(self, db, path):
        self._db, self._path = db, path
        self.id = path[-1]

    def get(self):
        return Snapshot(self, self._db.docs.get(self._path))

    def set(self, data, merge=False):
        if merge and self._path in self._db.docs:
            _merge(self._db.docs[self._path], data)
        else:
            self._db.docs[self._path] = copy.deepcopy(data)

    def update(self, data):
        if self._path not in self._db.docs:
            raise KeyError("No document to update: %s" % "/".join(self._path))
        _merge(self._db.docs[self._path], data)

    def delete(self):
        self._db.docs.pop(self._path, None)

    def collection(self, name):
        return CollectionRef(self._db, self._path + (name,))


class Query:
    def __init__(self, col, filters=(), limit_n=None, after=None):
        self._col, self._filters, self._limit, self._after = col, list(filters), limit_n, after

    def where(self, field, op, value):
        assert op == "==", "fake supports == only"
        return Query(self._col, self._filters + [(field, value)], self._limit, self._after)

    def limit(self, n):
        return Query(self._col, self._filters, n, self._after)

    def start_after(self, snap):
        return Query(self._col, self._filters, self._limit, snap.id)

    def stream(self):
        db, base = self._col._db, self._col._path
        rows = sorted((p, d) for p, d in db.docs.items()
                      if len(p) == len(base) + 1 and p[:-1] == base)
        out = []
        for path, data in rows:
            if any(_get_path(data, f) != v for f, v in self._filters):
                continue
            if self._after is not None and path[-1] <= self._after:
                continue
            out.append(Snapshot(DocRef(db, path), data))
            if self._limit and len(out) >= self._limit:
                break
        return iter(out)


class CollectionRef(Query):
    def __init__(self, db, path):
        self._db, self._path = db, path
        super().__init__(self)

    def document(self, doc_id=None):
        return DocRef(self._db, self._path + (doc_id or uuid.uuid4().hex[:20],))

    def add(self, data):
        ref = self.document()
        ref.set(data)
        return None, ref


class FakeFirestore:
    def __init__(self):
        self.docs = {}

    def collection(self, name):
        return CollectionRef(self, (name,))
