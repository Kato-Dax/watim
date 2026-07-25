from __future__ import annotations

from lexer import Token
from util import Ref

from resolving.top_items import Local
from resolving.words import LocalId, ScopeId


class Env:
    parent: Env | None
    scope_counter: Ref[int]
    scope_id: ScopeId
    vars: dict[str, list[tuple[Local, LocalId]]]
    vars_by_id: dict[LocalId, Local]

    def __init__(self, parent: Env | list[Local]):
        if isinstance(parent, Env):
            self.parent = parent
        else:
            self.parent = None
        self.scope_counter = parent.scope_counter if isinstance(parent, Env) else Ref(0)
        self.scope_id = ScopeId(self.scope_counter.value)
        self.scope_counter.value += 1
        self.vars = {}
        self.vars_by_id = parent.vars_by_id if isinstance(parent, Env) else {}
        if isinstance(parent, list):
            for param in parent:
                self.insert(param)

    def lookup(self, name: Token) -> LocalId | None:
        if name.lexeme not in self.vars:
            if self.parent is not None:
                return self.parent.lookup(name)
            return None
        vars = self.vars[name.lexeme]
        if len(vars) == 0:
            if self.parent is not None:
                return self.parent.lookup(name)
            return None
        return vars[-1][1]

    def insert(self, var: Local) -> LocalId:
        if var.name.get() in self.vars:
            id = LocalId(var.name.get(), self.scope_id, len(self.vars[var.name.get()]))
            self.vars[var.name.get()].append((var, id))
            self.vars_by_id[id] = var
            return id
        id = LocalId(var.name.get(), self.scope_id, 0)
        self.vars[var.name.get()] = [(var, id)]
        self.vars_by_id[id] = var
        return id

    def child(self) -> Env:
        return Env(self)
