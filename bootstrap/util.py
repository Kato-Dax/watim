from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import reduce


def indent_non_first(s: str) -> str:
    return reduce(lambda a,b: f"{a}  {b}", (f"{s}" for s in s.splitlines(keepends=True)))

def indent(s: str) -> str:
    return reduce(lambda a,b: f"{a}{b}", (f"  {s}" for s in s.splitlines(keepends=True)))

def listtostr[T](seq: Sequence[T], tostr: Callable[[T], str] | None = None, multi_line: bool = False) -> str:
    if len(seq) == 0:
        return "[]"
    s = "[\n" if multi_line else "["
    for e in seq:
        v = str(e) if tostr is None else tostr(e)
        s += indent(v) if multi_line else v
        s += ",\n" if multi_line else ", "
    return s[0:-2] + "]"

def intersperse[T](sep: T, seq: Iterable[T]) -> Iterator[T]:
    first = True
    for item in seq:
        if not first:
            yield sep
        first = False
        yield item

def intercalate(sep: str, seq: Iterable[str]) -> str:
    return reduce(lambda a, b: a + b, intersperse(sep, seq), "")

def seq_eq[T](a: Sequence[T], b: Sequence[T]) -> bool:
    if len(a) != len(b):
        return False
    return all(x == y for x, y in zip(a, b, strict=True))

@dataclass
class Lazy[T]:
    produce: Callable[[], T]
    inner: T | None = None

    def get(self) -> T:
        if self.inner is not None:
            return self.inner
        v = self.produce()
        self.inner = v
        self.produce = lambda: v
        return self.inner

    def has_value(self) -> bool:
        return self.inner is not None

sys_stdin = Lazy(lambda: sys.stdin.read())

@dataclass
class Ref[T]:
    value: T

def bag[K, V](items: Iterator[tuple[K, V]]) -> dict[K, list[V]]:
    bag: dict[K, list[V]] = {}
    for k,v in items:
        if k in bag:
            bag[k].append(v)
        else:
            bag[k] = [v]
    return bag

def normalize_path(path: str) -> str:
    if not path.startswith("./"):
        path = "./" + path
    path = path.replace("//", "/").replace("/./", "/")
    splits = path.split("/")
    outsplits = []
    i = 0
    while i < len(splits):
        split = splits[i]
        if i + 1 != len(splits) and splits[i + 1] == ".." and split != "." and split != "..":
            i += 2
            continue
        outsplits.append(split)
        i += 1

    out = "/".join(outsplits)
    if out != path:
        return normalize_path(out)

    return out

def uhex(n: int) -> str:
    return "0x" + hex(n)[2:].upper()

def align_to(n: int, to: int) -> int:
    if to == 0:
        return n
    return n + (to - (n % to)) * ((n % to) > 0)

