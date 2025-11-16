from typing import Iterable, List, Tuple
from dataclasses import dataclass

from format import Formattable
from lexer import Token

from unstacking.source import Source, FromNode

@dataclass
class Parent(Formattable):
    stack: 'Stack'
    node: int
    token: Token

    def clone(self) -> 'Parent':
        return Parent(self.stack.clone(), self.node, self.token)

@dataclass
class Stack(Formattable):
    parent: Parent | None
    positive: List[Source]
    negative: List[Source]

    @staticmethod
    def root() -> 'Stack':
        return Stack(None, [], [])

    def child(self, parent_node: int, parent_token: Token) -> 'Stack':
        return Stack(Parent(self, parent_node, parent_token), [], [])

    def clone(self) -> 'Stack':
        return Stack(self.parent.clone() if self.parent is not None else None, self.positive.copy(), self.negative.copy())

    def push(self, source: Source):
        self.positive.append(source)

    def push_many(self, sources: Iterable[Source]):
        self.positive.extend(sources)

    def pop(self) -> Source | None:
        if len(self.positive) == 0:
            if self.parent is None:
                return None
            source = self.parent.stack.pop()
            if source is None:
                return source
            self.negative.append(source)
            return FromNode(self.parent.token, self.parent.node, len(self.negative) - 1)
        return self.positive.pop()

    def pop_n(self, n: int) -> Tuple[Source, ...]:
        sources: List[Source] = []
        for _ in range(n):
            source = self.pop()
            if source is None:
                break
            sources.append(source)
        return tuple(reversed(sources))

    def ensure_negatives(self, n: int):
        while len(self.negative) < n:
            if self.parent is None:
                return
            taip = self.parent.stack.pop()
            if taip is None:
                return
            self.negative.append(taip)
            self.positive.insert(0, taip)

    def __len__(self) -> int:
        return len(self.positive) + (0 if self.parent is None else len(self.parent.stack))

    def dump(self) -> Tuple[Source, ...]:
        return self.pop_n(len(self))

    def index(self, index: int) -> Source:
        if index < len(self.positive):
            return self.positive[-(index + 1)]
        assert(self.parent is not None)
        return self.parent.stack.index(index - len(self.positive))

