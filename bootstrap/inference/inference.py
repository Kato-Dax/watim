from typing import Tuple, Dict, Literal, List
from dataclasses import dataclass

from format import Formattable

import resolving.module as resolved
from resolving.resolver import FunctionSignature
from resolving.words import LocalId
from resolving.types import CustomTypeHandle
from resolving.type_without_holes import Type

import unstacking.unstacker as unstacked
from unstacking.unstacker import Holes
from unstacking.source import Source, MultiReturnNode, InferenceHole

from inference.top_items import Function

def infer_function(modules: Tuple[resolved.Module, ...], globals: Tuple[resolved.Global, ...], function: unstacked.Function) -> Function:
    ctx = Ctx(
            modules=modules,
            locals=function.locals,
            globals=globals,
            holes=function.holes,
            field_holes=[],
            states={},
            nodes=function.nodes,
            struct_signatures={})
    for local in function.locals.values():
        if local.parameter is not None:
            ctx.fill_hole(local.taip, local.parameter)

    if function.returns is not None:
        assert len(function.signature.returns) == len(function.returns)
        for source, expected in zip(function.returns, function.signature.returns):
            ctx.check(source, expected)

    for void in function.voids:
        match void:
            case _other:
                assert False

    for local in function.locals.values():
        local_type = ctx.lookup_hole(local.taip)
        if local_type is None:
            inferred = ctx.infer_local(local)
            assert inferred is not None
            local_type = inferred

        ctx.check_local_assignments(local, local_type)

    assert False

@dataclass(frozen=True)
class Known(Formattable):
    taip: Type

type InferenceState = Literal["BeingInferred"] | Literal["BeingChecked"] | Known

@dataclass
class Ctx:
    modules: Tuple[resolved.Module, ...]
    locals: Dict[LocalId, unstacked.Local]
    states: Dict[Source, InferenceState]
    globals: Tuple[resolved.Global, ...]
    holes: Holes
    nodes: Tuple[MultiReturnNode, ...]
    field_holes: List[int | None]
    struct_signatures: Dict[CustomTypeHandle, FunctionSignature]

    def fill_hole(self, hole: InferenceHole, known: Type):
        assert False

    def lookup_hole(self, hole: InferenceHole) -> Type | None:
        return self.holes.lookup(hole)

    def check(self, source: Source, taip: Type):
        assert False

    def infer(self, source: Source) -> Type | None:
        assert False

    def infer_local(self, local: unstacked.Local) -> Type | None:
        assert False

    def check_local_assignments(self, local: unstacked.Local, expected_local_type: Type):
        assert False

