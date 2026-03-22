from typing import List, Dict, Sequence
from dataclasses import dataclass

from indexed_dict import IndexedDict

from monomorphization import Monomized, Extern, Function, LocalId, ScopeId, Scope, Local, GlobalId, Word
import monomorphization as mono

def merge_locals(monomized: Monomized):
    for module in monomized.modules.values():
        for function in module.functions:
            if isinstance(function, Extern):
                continue
            for instance in function:
                merge_locals_function(monomized.sizes, instance)

@dataclass
class Disjoint:
    scopes: List[ScopeId]
    reused: List[LocalId]
    substitutions: Dict[LocalId, LocalId]


def merge_locals_function(sizes: Sequence[int], function: Function):
    disjoint = Disjoint([], [], {})
    merge_locals_scope(sizes, function.body, function.locals, disjoint)

def merge_locals_scope(sizes: Sequence[int], scope: Scope, locals: IndexedDict[LocalId, Local], disjoint: Disjoint):
    for word in scope.words:
        merge_locals_word(sizes, word, locals, disjoint, scope.id)

def merge_locals_word(sizes: Sequence[int], word: Word, locals: IndexedDict[LocalId, Local], disjoint: Disjoint, scope: ScopeId):
    match word:
        case mono.InitLocal():
            local = locals[word.local]
            reused_local = find_disjoint_local(sizes, locals, disjoint, local)
            if reused_local is None:
                return
            del locals[word.local]
            disjoint.substitutions[word.local] = reused_local
            word.local = reused_local
        case mono.GetLocal() | mono.SetLocal() | mono.RefLocal() | mono.StoreLocal():
            fixup_var(word, disjoint)
        case mono.If():
            outer_reused = len(disjoint.reused)
            merge_locals_scope(sizes, word.true_branch, locals, disjoint)
            del disjoint.reused[outer_reused:]

            disjoint.scopes.append(word.true_branch.id)
            outer_reused = len(disjoint.reused)
            merge_locals_scope(sizes, word.false_branch, locals, disjoint)
            del disjoint.reused[outer_reused:]
            disjoint.scopes.pop()

            disjoint.scopes.append(word.true_branch.id)
            disjoint.scopes.append(word.false_branch.id)
        case mono.Block():
            outer_reused = len(disjoint.reused)
            merge_locals_scope(sizes, word.body, locals, disjoint)
            del disjoint.reused[outer_reused:]
            disjoint.scopes.append(word.body.id)
        case mono.Loop():
            outer_reused = len(disjoint.reused)
            merge_locals_scope(sizes, word.body, locals, disjoint)
            del disjoint.reused[outer_reused:]
            disjoint.scopes.append(word.body.id)
        case mono.MakeStructNamed():
            outer_reused = len(disjoint.reused)
            merge_locals_scope(sizes, word.body, locals, disjoint)
            del disjoint.reused[outer_reused:]
            disjoint.scopes.append(word.body.id)
        case mono.Match():
            for case in word.cases:
                outer_reused = len(disjoint.reused)
                merge_locals_scope(sizes, case.body, locals, disjoint)
                del disjoint.reused[outer_reused:]
                disjoint.scopes.append(case.body.id)
            if word.default is not None:
                outer_reused = len(disjoint.reused)
                merge_locals_scope(sizes, word.default, locals, disjoint)
                del disjoint.reused[outer_reused:]
                disjoint.scopes.append(word.default.id)

def fixup_var(word: mono.GetLocal | mono.SetLocal | mono.StoreLocal | mono.RefLocal, disjoint: Disjoint):
    match word.var:
        case GlobalId():
            pass
        case LocalId():
            if word.var in disjoint.substitutions:
                word.var = disjoint.substitutions[word.var]

def find_disjoint_local(sizes: Sequence[int], locals: IndexedDict[LocalId, Local], disjoint: Disjoint, to_be_replaced: Local) -> LocalId | None:
    local_size = mono.type_size(sizes, to_be_replaced.type)
    if len(disjoint.scopes) == 0:
        return None
    for local_id, local in locals.items():
        if local_size == mono.type_size(sizes, local.type) and mono.local_lives_in_memory(sizes, to_be_replaced) == mono.local_lives_in_memory(sizes, local):
            if local_id.scope in disjoint.scopes and local_id not in disjoint.reused:
                disjoint.reused.append(local_id)
                return local_id
    return None
