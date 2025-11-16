from typing import List, Sequence
from dataclasses import dataclass

import format
from format import Formattable, Formatter
from resolving.types import Type

@dataclass
class Stack(Formattable):
    parent: 'Stack | None'
    stack: List[Type]
    negative: List[Type]

    @staticmethod
    def empty() -> 'Stack':
        return Stack(None, [], [])

    def append(self, taip: Type):
        self.push(taip)

    def push(self, taip: Type):
        self.stack.append(taip)

    def push_many(self, taips: Sequence[Type]):
        for taip in taips:
            self.append(taip)

    def pop(self) -> Type | None:
        if len(self.stack) != 0:
            return self.stack.pop()
        if self.parent is None:
            return None
        taip = self.parent.pop()
        if taip is None:
            return None
        self.negative.append(taip)
        return taip

    def drop_n(self, n: int):
        for _ in range(n):
            self.pop()

    def pop_n(self, n: int) -> List[Type]:
        popped: List[Type] = []
        while n != 0:
            popped_type = self.pop()
            if popped_type is None:
                break
            popped.append(popped_type)
            n -= 1
        popped.reverse()
        return popped

    def clone(self) -> 'Stack':
        return Stack(self.parent.clone() if self.parent is not None else None, list(self.stack), list(self.negative))

    def dump(self) -> List[Type]:
        dump: List[Type] = []
        while True:
            t = self.pop()
            if t is None:
                dump.reverse()
                return dump
            dump.append(t)

    def make_child(self) -> 'Stack':
        return Stack(self.clone(), [], [])

    def use(self, n: int):
        popped = []
        for _ in range(n):
            taip = self.pop()
            assert(taip is not None)
            popped.append(taip)
        for taip in reversed(popped):
            self.append(taip)

    def compatible_with(self, other: 'Stack') -> bool:
        if len(self) != len(other):
            return False
        self.use(len(other.stack))
        other.use(len(self.stack))
        negative_is_fine = self.negative == other.negative
        positive_is_fine = self.stack == other.stack
        return negative_is_fine and positive_is_fine

    def __len__(self) -> int:
        return len(self.stack) + (len(self.parent) if self.parent is not None else 0)

    def __getitem__(self, index: int) -> Type:
        if index > 0:
            return self.stack[index]
        if abs(index) <= len(self.stack):
            return self.stack[index]
        assert(self.parent is not None)
        return self.parent[index + len(self.stack)]

    def format(self, fmt: Formatter):
        fmt.named_record("Stack", [
            ("parent", self.parent),
            ("stack", format.Seq(self.stack)),
            ("negative", format.Seq(self.negative))])

