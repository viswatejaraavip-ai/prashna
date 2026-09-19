"""Tiny in-memory stand-in for google.cloud.firestore.Client.

Supports what the admin module uses: collection/document refs, sub-collections,
get/set(merge)/update/add, where(==,!=,<,<=,>,>=,in), order_by, limit, stream,
get_all. Documents are deep-copied in and out so tests can't alias state.
"""

import copy
import itertools
import operator

_ids = itertools.count(1)

_OPS = {"==": operator.eq, "!=": operator.ne, "<": operator.lt, "<=": operator.le,
        ">": operator.gt, ">=": operator.ge, "in": lambda a, b: a in b}


class Snapshot:
    def __init__(self, ref, data):
        self.reference = ref
        self.id = ref.id
        self._data = copy.deepcopy(data)
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self._data) if self.exists else None


class DocumentRef:
    def __init__(self, client, path, doc_id):
        self._client = client
        self._path = path          # collection path
        self.id = doc_id

    @property
    def _key(self):
        return (self._path, self.id)

    def get(self):
        return Snapshot(self, self._client._docs.get(self._key))

    def set(self, data, merge=False):
        cur = self._client._docs.get(self._key)
        if merge and cur is not None:
            new = copy.deepcopy(cur)
            new.update(copy.deepcopy(data))
        else:
            new = copy.deepcopy(data)
        self._client._docs[self._key] = new

    def update(self, data):
        if self._key not in self._client._docs:
            raise KeyError("No document to update: %s/%s" % self._key)
        self._client._docs[self._key].update(copy.deepcopy(data))

    def delete(self):
        self._client._docs.pop(self._key, None)

    def collection(self, name):
        return CollectionRef(self._client, "%s/%s/%s" % (self._path, self.id, name))


class Query:
    def __init__(self, client, path, filters=(), orders=(), lim=None):
        self._client, self._path = client, path
        self._filters, self._orders, self._limit = list(filters), list(orders), lim

    def _clone(self, **kw):
        q = Query(self._client, self._path, self._filters, self._orders, self._limit)
        for k, v in kw.items():
            setattr(q, k, v)
        return q

    def where(self, field, op, value):
        return self._clone(_filters=self._filters + [(field, op, value)])

    def order_by(self, field, direction="ASCENDING"):
        return self._clone(_orders=self._orders + [(field, direction)])

    def limit(self, n):
        return self._clone(_limit=n)

    def stream(self):
        self._client.queries.append((self._path, list(self._filters),
                                     list(self._orders), self._limit))
        rows = [(k[1], v) for k, v in self._client._docs.items() if k[0] == self._path]
        for field, op, value in self._filters:
            rows = [(i, d) for i, d in rows
                    if field in d and d[field] is not None and _OPS[op](d[field], value)]
        for field, direction in reversed(self._orders):
            rows = [(i, d) for i, d in rows if field in d]
            rows.sort(key=lambda r: r[1][field], reverse=direction == "DESCENDING")
        if self._limit is not None:
            rows = rows[: self._limit]
        for doc_id, d in rows:
            yield Snapshot(DocumentRef(self._client, self._path, doc_id), d)


class CollectionRef(Query):
    def __init__(self, client, path):
        super().__init__(client, path)

    def document(self, doc_id=None):
        return DocumentRef(self._client, self._path, doc_id or "auto%06d" % next(_ids))

    def add(self, data):
        ref = self.document()
        ref.set(data)
        return None, ref


class FakeFirestore:
    def __init__(self):
        self._docs = {}
        self.queries = []  # log of (path, filters, orders, limit) for index checks

    def collection(self, name):
        return CollectionRef(self, name)

    def get_all(self, refs):
        for r in refs:
            yield r.get()

    def dump(self, path):
        return {k[1]: v for k, v in self._docs.items() if k[0] == path}
