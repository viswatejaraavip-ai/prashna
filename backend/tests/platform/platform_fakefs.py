"""Tiny in-memory Firestore stand-in for platform tests (no emulator needed).

Supports what the platform code uses: documents/collections/subcollections,
set(merge)/update/create/delete, Increment/ArrayUnion/ArrayRemove, simple
where/order_by/limit queries, transactions (applied immediately) and
recursive_delete.
"""

import copy
import uuid
from typing import Any, Dict, List, Tuple


class AlreadyExists(Exception):
    pass


def _apply_value(old: Any, new: Any) -> Any:
    name = type(new).__name__
    if name == "Increment":
        return (old or 0) + new.value
    if name == "ArrayUnion":
        cur = list(old or [])
        return cur + [v for v in new.values if v not in cur]
    if name == "ArrayRemove":
        return [v for v in (old or []) if v not in new.values]
    return copy.deepcopy(new)


def _set_path(data: Dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    for p in parts[:-1]:
        data = data.setdefault(p, {})
    data[parts[-1]] = _apply_value(data.get(parts[-1]), value)


class Snapshot:
    def __init__(self, ref, data):
        self.reference = ref
        self.id = ref.id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self._data) if self._data is not None else None


class DocRef:
    def __init__(self, client, path: Tuple[str, ...]):
        self._c = client
        self._path = path
        self.id = path[-1]

    @property
    def path(self):
        return "/".join(self._path)

    def collection(self, name):
        return CollRef(self._c, self._path + (name,))

    def get(self, transaction=None):
        return Snapshot(self, copy.deepcopy(self._c.docs.get(self._path)))

    def set(self, data, merge=False):
        cur = self._c.docs.get(self._path) if merge else None
        cur = copy.deepcopy(cur) if cur is not None else {}
        for k, v in data.items():
            if merge:
                _set_path(cur, k, v)
            else:
                cur[k] = _apply_value(None, v)
        self._c.docs[self._path] = cur

    def create(self, data):
        if self._path in self._c.docs:
            raise AlreadyExists(self.path)
        self.set(data)

    def update(self, fields):
        if self._path not in self._c.docs:
            raise KeyError("No document to update: " + self.path)
        cur = self._c.docs[self._path]
        for k, v in fields.items():
            _set_path(cur, k, v)

    def delete(self):
        self._c.docs.pop(self._path, None)


class Query:
    def __init__(self, client, path, filters=None, orders=None, limit_n=None):
        self._c = client
        self._path = path
        self._filters = filters or []
        self._orders = orders or []
        self._limit = limit_n

    def _copy(self, **kw):
        q = Query(self._c, self._path, list(self._filters), list(self._orders), self._limit)
        for k, v in kw.items():
            setattr(q, k, v)
        return q

    def where(self, field=None, op=None, value=None, filter=None):  # noqa: A002
        if filter is not None:
            field, op, value = filter.field_path, filter.op_string, filter.value
        return self._copy(_filters=self._filters + [(field, op, value)])

    def order_by(self, field, direction="ASCENDING"):
        return self._copy(_orders=self._orders + [(field, direction)])

    def limit(self, n):
        return self._copy(_limit=n)

    def _match(self, data):
        for field, op, value in self._filters:
            cur = data
            for p in field.split("."):
                cur = cur.get(p) if isinstance(cur, dict) else None
            if op == "==" and cur != value:
                return False
            if op in ("<", "<=", ">", ">=") and (cur is None or not {
                    "<": cur < value, "<=": cur <= value,
                    ">": cur > value, ">=": cur >= value}[op]):
                return False
            if op == "in" and cur not in value:
                return False
            if op == "array_contains" and value not in (cur or []):
                return False
        return True

    def stream(self):
        n = len(self._path)
        rows = [(p, d) for p, d in self._c.docs.items()
                if len(p) == n + 1 and p[:n] == self._path and self._match(d)]
        for field, direction in reversed(self._orders):
            rows.sort(key=lambda r: (r[1].get(field) is None, r[1].get(field) or ""),
                      reverse=(direction == "DESCENDING"))
        if self._limit:
            rows = rows[: self._limit]
        return iter([Snapshot(DocRef(self._c, p), copy.deepcopy(d)) for p, d in rows])

    def get(self):
        return list(self.stream())


class CollRef(Query):
    def __init__(self, client, path):
        super().__init__(client, path)
        self.id = path[-1]

    def document(self, doc_id=None):
        return DocRef(self._c, self._path + (doc_id or uuid.uuid4().hex[:20],))

    def add(self, data):
        ref = self.document()
        ref.set(data)
        return None, ref

    def list_documents(self):
        n = len(self._path)
        return [DocRef(self._c, p) for p in list(self._c.docs)
                if len(p) == n + 1 and p[:n] == self._path]


class Txn:
    def __init__(self, client):
        self._c = client

    def set(self, ref, data, merge=False):
        ref.set(data, merge=merge)

    def update(self, ref, fields):
        ref.update(fields)

    def create(self, ref, data):
        ref.create(data)

    def delete(self, ref):
        ref.delete()


class FakeFirestore:
    def __init__(self):
        self.docs: Dict[Tuple[str, ...], Dict] = {}

    def collection(self, name):
        return CollRef(self, (name,))

    def document(self, path):
        return DocRef(self, tuple(path.split("/")))

    def transaction(self):
        return Txn(self)

    def get_all(self, refs):
        for r in refs:
            yield r.get()

    def recursive_delete(self, ref):
        prefix = ref._path
        for p in [p for p in self.docs if p[: len(prefix)] == prefix]:
            del self.docs[p]

    def run_transaction(self, fn):
        """Stand-in for store.run_transaction: all-or-nothing via snapshot."""
        backup = copy.deepcopy(self.docs)
        try:
            return fn(Txn(self))
        except Exception:
            self.docs = backup
            raise

    # helpers for assertions
    def data(self, path: str) -> Dict:
        return copy.deepcopy(self.docs.get(tuple(path.split("/"))))

    def children(self, path: str) -> List[Dict]:
        pre = tuple(path.split("/"))
        return [d for p, d in self.docs.items() if len(p) == len(pre) + 1 and p[: len(pre)] == pre]
