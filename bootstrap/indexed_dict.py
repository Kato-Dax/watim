from typing import Dict, Tuple, List, Iterable, Callable

from util import Ref
import format

class IndexedDict[K, V]:
    inner: Dict[K, Ref[Tuple[V, int]]]
    pairs: List[Tuple[K, Ref[Tuple[V, int]]]]

    def __init__(self, inner: Dict[K, Ref[Tuple[V, int]]] | None = None, pairs: List[Tuple[K, Ref[Tuple[V, int]]]] | None = None):
        assert((inner is None) == (pairs is None))
        self.inner = inner or {}
        self.pairs = pairs or []

    @staticmethod
    def from_values(values: Iterable[V], key: Callable[[V], K]) -> 'IndexedDict[K, V]':
        inner = { key(value): Ref((value, i)) for i,value in enumerate(values) }
        pairs = list(inner.items())
        return IndexedDict(inner, pairs)

    @staticmethod
    def from_items(items: Iterable[Tuple[K, V]]) -> 'IndexedDict[K, V]':
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

    def __iter__(self) -> Iterable[K]:
        for k in self.inner:
            yield k

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

    def keys(self) -> Iterable[K]:
        return self.inner.keys()

    def values(self) -> Iterable[V]:
        return map(lambda ref: ref.value[0], self.inner.values())

    def items(self) -> Iterable[Tuple[K, V]]:
        return map(lambda kv: (kv[0], kv[1].value[0]), self.inner.items())

    def indexed_values(self) -> Iterable[Tuple[int, V]]:
        return enumerate(map(lambda kv: kv[1].value[0], self.pairs))

    def __len__(self) -> int:
        return len(self.pairs)

    def delete(self, index: int):
        del self.inner[self.pairs.pop(index)[0]]

    def formattable(self, format_key: Callable[[K], format.Writable], format_value: Callable[[V], format.Writable]) -> format.Formattable:
        return format.Dict(dict((format_key(k), format_value(v)) for k,v in self.items()))
