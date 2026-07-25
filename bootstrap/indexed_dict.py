from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator

import format
from util import Ref


class IndexedDict[K, V]:
    inner: dict[K, Ref[tuple[V, int]]]
    pairs: list[tuple[K, Ref[tuple[V, int]]]]

    def __init__(self, inner: dict[K, Ref[tuple[V, int]]] | None = None, pairs: list[tuple[K, Ref[tuple[V, int]]]] | None = None):
        assert((inner is None) == (pairs is None))
        self.inner = inner or {}
        self.pairs = pairs or []

    @staticmethod
    def from_values(values: Iterable[V], key: Callable[[V], K]) -> IndexedDict[K, V]:
        inner = { key(value): Ref((value, i)) for i,value in enumerate(values) }
        pairs = list(inner.items())
        return IndexedDict(inner, pairs)

    @staticmethod
    def from_items(items: Iterable[tuple[K, V]]) -> IndexedDict[K, V]:
        inner = { key: Ref((value, i)) for i,(key,value) in enumerate(items) }
        pairs = list(inner.items())
        return IndexedDict(inner, pairs)

    def index(self, index: int) -> V:
        assert(len(self.inner) == len(self.pairs))
        return self.pairs[index][1].value[0]

    def index_key(self, index: int) -> K:
        assert(len(self.inner) == len(self.pairs))
        return self.pairs[index][0]

    def index_of(self, key: K) -> int:
        return self.inner[key].value[1]

    def __contains__(self, key: K) -> bool:
        return key in self.inner

    def __iter__(self) -> Iterator[K]:
        yield from self.inner

    def __getitem__(self, key: K) -> V:
        return self.inner[key].value[0]

    def __setitem__(self, key: K, value: V):
        if key in self.inner:
            pair = self.inner[key].value
            self.inner[key].value = (value, pair[1])
        else:
            ref = Ref((value, len(self.pairs)))
            self.inner[key] = ref
            self.pairs.append((key, ref))

    def __delitem__(self, key: K):
        index = self.inner[key].value[1]
        for _, ref in self.pairs[index:]:
            ref.value = (ref.value[0], ref.value[1] - 1)
        del self.pairs[index]
        del self.inner[key]

    def keys(self) -> Iterable[K]:
        return self.inner.keys()

    def values(self) -> Iterable[V]:
        return (ref.value[0] for ref in self.inner.values())

    def items(self) -> Iterable[tuple[K, V]]:
        return ((kv[0], kv[1].value[0]) for kv in self.inner.items())

    def indexed_values(self) -> Iterable[tuple[int, V]]:
        return enumerate(kv[1].value[0] for kv in  self.pairs)

    def __len__(self) -> int:
        return len(self.pairs)

    def delete(self, index: int):
        del self.inner[self.pairs.pop(index)[0]]

    def formattable(self, format_key: Callable[[K], format.Writable], format_value: Callable[[V], format.Writable]) -> format.Formattable:
        return format.Dict({ format_key(k): format_value(v) for k,v in self.items()})
