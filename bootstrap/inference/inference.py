from typing import Never, Tuple, Dict, Literal, List, Sequence, assert_never, cast
from dataclasses import dataclass
import sys

from format import Formattable, Formatter
from indexed_dict import IndexedDict

from lexer import Token

import resolving.module as resolved
from resolving.resolver import FunctionSignature
from resolving.words import LocalId, IntrinsicType
from resolving.top_items import TypeDefinition, Variant, Struct, MustBeOneOf, MustSatisfyPredicate, IntrinsicSignature, Signature
from resolving.types import CustomTypeHandle
from resolving.type_resolver import TypeLookup
from resolving.type_without_holes import Type, PtrType, CustomTypeType, GenericType, FunctionType, I8, I32, I64, Bool
import resolving.type_without_holes as without_holes

import unstacking as unstacked
from unstacking.unstacker import Holes, StackVoid, intrinsic_signatures
from unstacking.source import (
        FromCast,
        Source,
        MultiReturnNode,
        InferenceHole,
        FromLocal,
        FromNumber,
        FromNode,
        FromCall,
        FromMakeStruct,
        FromString,
        FromFunRef,
        FromIfExit,
        FromIfEntry,
        FromMatchEntry,
        FromMatchExit,
        FromBlockEntry,
        FromBlockExit,
        FromLoopEntry,
        FromCase,
        FromGlobal,
        FromLoad,
        FromProxied,
        FromGetField,
        FromMakeVariant,
        FromIndirectCall,
        FromAdd,
        FromStackAnnotation,
        PlaceHolder,
)
from unstacking.voids import NonSpecificVoid, CallVoid, ImpossibleMatchVoid, SetGlobalVoid, StoreVoid, IndirectCallVoid
from unstacking import InferenceFieldHole

from inference.top_items import Function, Scope, Local
from inference.words import (
        Word,
        InitLocal,
        GetLocal,
        SetLocal,
        StoreLocal,
        FieldAccess,
        Drop,
        Eq,
        NotEq,
        Call,
        Uninit,
        Cast,
        MakeStruct,
        RefLocal,
        FunRef,
        If,
        Mul,
        Div,
        Mod,
        Add,
        Sub,
        Match,
        MatchCase,
        Block,
        Loop,
        Load,
        Flip,
        Store,
        Lt,
        Le,
        Ge,
        Gt,
        And,
        Or,
        Shl,
        Shr,
        Rotl,
        Rotr,
        MakeVariant,
        Not,
        GetField,
        FieldInit,
        MakeStructNamed,
        IndirectCall,
)

def assert_is_number(t: Type) -> I8 | I32 | I64:
    assert isinstance(t, I8) or isinstance(t, I32) or isinstance(t, I64)
    return t

def assert_is_addable(t: Type) -> I8 | I32 | I64 | PtrType:
    assert isinstance(t, I8) or isinstance(t, I32) or isinstance(t, I64) or isinstance(t, PtrType)
    return t

def assert_is_primitive(t: Type) -> Bool | I8 | I32 | I64:
    assert isinstance(t, Bool) or isinstance(t, I8) or isinstance(t, I32) or isinstance(t, I64)
    return t

@dataclass
class InferenceException(Exception):
    path: str
    token: Token
    message: str

    def display(self) -> str:
        line = self.token.line
        column = self.token.column
        return f"{self.path}:{line}:{column} {self.message}"

def infer_function(path: str, modules: Tuple[resolved.Module, ...], globals: Tuple[resolved.Global, ...], function: unstacked.Function) -> Function:
    ctx = Ctx(
            path=path,
            modules=modules,
            locals=function.locals,
            globals=globals,
            holes=function.holes,
            field_holes=[],
            states={},
            nodes=function.nodes,
            struct_signatures={},
            type_lookup=TypeLookup(None, modules, None),
            progress=1,
            deferred_infers=[])
    for local in function.locals.values():
        if local.parameter is not None:
            ctx.fill_hole(local.taip, local.parameter)

    if function.returns is not None:
        if len(function.signature.returns) != len(function.returns):
            fmt = Formatter("  ", 0, [])
            fmt.write("unexpected return values:\n\texpected: ")
            fmt.write(ctx.type_lookup.types_pretty_bracketed(function.signature.returns))
            fmt.write("\n\tactual:    [")
            for ret in function.returns:
                inferred = ctx.infer(ret)
                if inferred is None:
                    fmt.write("_")
                else:
                    fmt.write(ctx.type_lookup.type_pretty(inferred))
                fmt.write(", ")
            ctx.abort(function.name, fmt.to_string())
        for source, expected in zip(function.returns, function.signature.returns):
            ctx.check(source, expected)

    for void in function.voids:
        ctx.deferred_infers.append(DeferredStackVoid(ctx.progress, void))

    ctx.progress += 1

    while len(ctx.deferred_infers) != 0:
        deferred = ctx.deferred_infers.pop()
        void = deferred.deferred
        if deferred.progress == ctx.progress:
            ctx.abort(deferred.deferred.token, "failed to infer type of void")
        void = deferred.deferred
        def defer():
            ctx.deferred_infers.insert(0, DeferredStackVoid(ctx.progress, void))
        match void:
            case NonSpecificVoid():
                assert(void.source is not None)
                if void.known is None:
                    taip = ctx.infer(void.source)
                    if taip is None:
                        defer()
                        continue
                else:
                    ctx.check(void.source, void.known)
                    taip = void.known
                if void.taip is not None:
                    ctx.fill_hole(void.taip, taip)
            case CallVoid():
                signature = ctx.lookup_signature(void.function)
                argument_types = ctx.infer_over_array(void.arguments)
                if len(void.arguments) != len(signature.parameters):
                    ctx.call_argument_mismatch_error(void.token, signature, void.generic_arguments, argument_types)
                there_are_no_generic_arguments = True
                for argument_source, parameter, argument in zip(void.arguments, signature.parameters, argument_types):
                    parameter_taip = parameter.taip if isinstance(parameter, without_holes.NamedType) else parameter
                    if without_holes.contains_generic(parameter_taip):
                        there_are_no_generic_arguments = False
                        if argument is not None:
                            match ctx.unify_types(void.generic_arguments, parameter_taip, argument):
                                case "Success":
                                    continue
                                case "TypeMismatch":
                                    ctx.abort(void.token, "type mismatch")
                                case contradiction:
                                    ctx.abort(void.token, f"{contradiction}")
                        continue
                    if argument is None:
                        ctx.check(argument_source, parameter_taip)
                    else:
                        if parameter_taip != argument:
                            ctx.call_argument_mismatch_error(void.token, signature, void.generic_arguments, argument_types)

                if not there_are_no_generic_arguments:
                    generic_arguments = ctx.lookup_holes(void.generic_arguments)
                    if generic_arguments is not None:
                        for argument_source, argument, param in zip(void.arguments, argument_types, signature.parameters):
                            param_taip = param.taip if isinstance(param, without_holes.NamedType) else param
                            param_type = without_holes.with_generics(param_taip, generic_arguments)
                            if argument is None:
                                ctx.check(argument_source, param_type)
                            else:
                                if param_type != argument:
                                    ctx.call_argument_mismatch_error(void.token, signature, void.generic_arguments, argument_types)
                    else:
                        for parameter, argument in zip(signature.parameters, argument_types):
                            if argument is None:
                                defer()
                                continue
                            parameter_taip = parameter.taip if isinstance(parameter, without_holes.NamedType) else parameter
                            match ctx.unify_types(void.generic_arguments, parameter_taip, argument):
                                case GenericsContradict():
                                    pass
                                case "TypeMismatch":
                                    pass
                                case "Success":
                                    pass
                                case other:
                                    assert_never(other)
            case ImpossibleMatchVoid():
                if void.source is None:
                    ctx.abort(void.token, "match expected value")
                taip = ctx.infer(void.source)
                if taip is None:
                    defer()
                    continue
                if isinstance(taip, PtrType):
                    taip = taip.child
                if not isinstance(taip, CustomTypeType):
                    ctx.abort(void.token, "expected to match on a variant")
                varint = ctx.lookup_type_definition(taip.type_definition)
                if isinstance(varint, Struct):
                    ctx.abort(void.token, "expected to match on a variant")
                if len(varint.cases) != 0:
                    ctx.abort(void.token, "expected a variant with zero cases")
            case SetGlobalVoid():
                field_type = ctx.traverse_fields(void.global_type, void.fields)
                if void.source is None:
                    ctx.abort(void.token, "set global expected item")
                ctx.fill_hole(void.type, field_type)
                ctx.check(void.source, field_type)
            case StoreVoid():
                if void.dst is None:
                    ctx.abort(void.token, "dst is missing")
                if void.src is None:
                    ctx.abort(void.token, "src is missing")
                dst = ctx.infer(void.dst)
                if dst is None:
                    src = ctx.infer(void.src)
                    if src is None:
                        ctx.abort(void.token, "failed to infer type of store")
                    ctx.check(void.dst, PtrType(src))
                    taip = src
                else:
                    if not isinstance(dst, PtrType):
                        ctx.abort(void.token, "cannot store into non-ptr")
                    ctx.check(void.src, dst.child)
                    taip = dst.child
                ctx.fill_hole(void.taip, taip)
            case IndirectCallVoid():
                if void.function is None:
                    ctx.abort(void.token, "expected function on stack")
                parameters = ctx.lookup_holes(void.parameters)
                if parameters is None:
                    defer()
                    continue
                returns = ctx.lookup_holes(void.returns)
                if returns is None:
                    defer()
                    continue
                known = FunctionType(void.token, parameters, returns)
                ctx.check(void.function, known)
            case other:
                assert_never(other)

    for local in function.locals.values():
        local_type = ctx.lookup_hole(local.taip)
        if local_type is None:
            inferred = ctx.infer_local(local)
            assert inferred is not None
            local_type = inferred

        ctx.check_local_assignments(local, local_type)

    foo: Dict[LocalId, unstacked.Local] = function.locals

    body = ctx.fill_holes_scope(function.body)
    return Function(
        function.name,
        function.export,
        function.signature,
        ctx.fill_holes_locals(foo),
        body)

@dataclass(frozen=True)
class Known(Formattable):
    taip: Type

type InferenceState = Literal["BeingInferred"] | Literal["BeingChecked"] | Known

@dataclass(frozen=True)
class GenericsContradict:
    generic: int
    previous: Type
    now: Type

type UnificationResult = Literal["Success"] | Literal["TypeMismatch"] | GenericsContradict

@dataclass
class DeferredStackVoid:
    progress: int
    deferred: StackVoid

type DeferredInfer = DeferredStackVoid

@dataclass
class Ctx:
    path: str
    modules: Tuple[resolved.Module, ...]
    type_lookup: TypeLookup
    locals: Dict[LocalId, unstacked.Local]
    states: Dict[Source, InferenceState]
    globals: Tuple[resolved.Global, ...]
    holes: Holes
    nodes: Tuple[MultiReturnNode, ...]
    field_holes: List[int | None]
    struct_signatures: Dict[CustomTypeHandle, FunctionSignature]
    deferred_infers: List[DeferredInfer]
    progress: int
    log_level: Literal["NoLogs"] | Literal["OnlyStructure"] | Literal["FullSources"] = "NoLogs"

    def abort(self, token: Token, msg: str) -> Never:
        raise InferenceException(self.path, token, msg)

    def full_sources(self) -> bool:
        return self.log_level == "FullSources"

    def fill_hole(self, hole: InferenceHole, known: Type):
        if self.full_sources():
            print(f"fill-hole: {hole}, {known}", file=sys.stderr)
        self.holes.fill(hole, known)
        self.progress += 1

    def lookup_hole(self, hole: InferenceHole) -> Type | None:
        return self.holes.lookup(hole)

    def lookup_holes(self, holes: Sequence[InferenceHole]) -> Tuple[Type, ...] | None:
        res: List[Type] = []
        for hole in holes:
            taip = self.lookup_hole(hole)
            if taip is None:
                return None
            res.append(taip)
        return tuple(res)

    def fill_field_hole(self, hole: InferenceFieldHole, field: int):
        while len(self.field_holes) <= hole.index:
            self.field_holes.append(None)
        assert(self.field_holes[hole.index] is None or self.field_holes[hole.index] == field)
        self.field_holes[hole.index] = field

    def lookup_type_definition(self, handle: CustomTypeHandle) -> TypeDefinition:
        return self.modules[handle.module].type_definitions.index(handle.index)

    def lookup_signature(self, function: resolved.FunctionHandle | IntrinsicType) -> Signature:
        match function:
            case resolved.FunctionHandle():
                return self.modules[function.module].functions.index(function.index).signature
            case IntrinsicType():
                return intrinsic_signatures[function].signature

    def infer_over_array(self, sources: Sequence[Source]) -> Tuple[Type | None, ...]:
        return tuple(self.infer(source) for source in sources)

    def check_inner(self, source: Source, known: Type):
        match source:
            case FromLocal():
                result_type = self.lookup_hole(source.result_type)
                if result_type is not None:
                    if result_type != known:
                        self.abort(source.token, "expected local to have different type")
                    return

                local = self.locals[source.var]
                local_type = self.lookup_hole(local.taip)
                if local_type is None:
                    if len(source.fields) == 0:
                        initialization = local.assignments[0]
                        if source.by_reference:
                            assert(isinstance(known, PtrType))
                            expected_local_type = known.child
                        else:
                            expected_local_type = known
                        self.fill_hole(local.taip, expected_local_type)
                        if initialization.source is None:
                            self.abort(initialization.token, "expected item")
                        self.check(initialization.source, expected_local_type)
                        self.fill_hole(source.result_type, known)
                        self.check_local_assignments(local, expected_local_type)
                    else:
                        del self.states[source]
                        type = self.infer(source)
                        if type is None:
                            self.abort(source.token, "check FromLocal: cannot infer type of local")
                        if type != known:
                            self.abort(source.token, "check FromLocal: mismatch")
                else:
                    result_type = self.traverse_fields(local_type, source.fields)
                    if source.by_reference:
                        result_type = PtrType(result_type)
                    self.fill_hole(source.result_type, result_type)
                    self.check_local_assignments(local, local_type)
            case FromNumber():
                if not isinstance(known, I32):
                    self.abort(source.token, "check FromNumber: known /= i32")
            case FromCast():
                dst_type = without_holes.without_holes(source.dst_type)
                if isinstance(dst_type, Token):
                    self.abort(dst_type, "Holes are not yet supported here")
                if dst_type != known:
                    self.abort(source.token, "check FromCast: known /= dst-type")
                if source.src is None:
                    self.abort(source.token, "check FromCast: src is None")
                src_type = self.infer(source.src)
                if src_type is None:
                    self.abort(source.token, "LOL")
                self.fill_hole(source.src_type, src_type)
            case FromString():
                if known != PtrType(I8()):
                    self.abort(source.token, "check FromString: known /= .i8")
            case FromMakeStruct():
                struct = self.lookup_type_definition(source.type_definition)
                if isinstance(struct, Variant):
                    self.abort(source.token, "`make` expected struct")
                if len(source.arguments) != len(struct.fields):
                    self.abort(source.token, "`make struct` expected more arguments")
                if not isinstance(known, CustomTypeType):
                    self.abort(source.token, "`make struct` only makes custom types")
                if known.type_definition != source.type_definition:
                    self.abort(source.token, "expected different type")
                self.fill_hole(source.taip, known)
                self.check_make_struct_fields(struct, source.arguments, known)
            case FromFunRef():
                signature = self.lookup_signature(source.function)
                if not isinstance(known, FunctionType):
                    self.abort(source.token, "check: FromFunRef: got function expected different")
                if len(known.parameters) != len(signature.parameters) or len(known.returns) != len(signature.returns):
                    self.abort(source.token, "check: FromFunRef: expected different signature")

                for parameter, known_param in zip(signature.parameters, known.parameters):
                    res = self.unify_types(source.generic_arguments, parameter.taip if isinstance(parameter, without_holes.NamedType) else parameter, known_param)
                    if res != "Success":
                        self.abort(source.token, "check: FromFunRef: TODO")
                for ret, known_ret in zip(signature.returns, known.returns):
                    res = self.unify_types(source.generic_arguments, ret, known_ret)
                    if res != "Success":
                        self.abort(source.token, "check: FromFunRef: TODO")
            case FromNode():
                self.check_from_node(source, known)
            case FromCase():
                if source.scrutinee is None:
                    self.abort(source.token, "check FromCase: expected scrutinee")
                scrutinee_type = self.lookup_hole(source.scrutinee_type)
                if scrutinee_type is None:
                    scrutinee_type = self.infer(source.scrutinee)
                    if scrutinee_type is None:
                        return None
                    self.fill_hole(source.scrutinee_type, scrutinee_type)
                variant = self.lookup_type_definition(source.variant)
                if isinstance(variant, Struct):
                    self.abort(source.token, "`match` expected variant")
                case_type = variant.cases[source.tag].taip
                assert case_type is not None
                if isinstance(scrutinee_type, PtrType):
                    scrutinee_custom_type = scrutinee_type.child
                else:
                    scrutinee_custom_type = scrutinee_type
                if not isinstance(scrutinee_custom_type, CustomTypeType):
                    self.abort(source.token, "`match` can only match on variants")
                if scrutinee_custom_type.type_definition != source.variant:
                    self.abort(source.token, "`match` expected to match on a different type")
                case_type = without_holes.with_generics(case_type, scrutinee_custom_type.generic_arguments)
                if isinstance(scrutinee_type, PtrType):
                    case_type = PtrType(case_type)
                if case_type != known:
                    self.abort(source.token, "check: FromCase expected different")
            case FromLoad():
                if source.src is None:
                    self.abort(source.token, "check FromLoad: src is None")
                self.fill_hole(source.taip, known)
                self.check(source.src, PtrType(known))
            case FromProxied():
                self.check(source.source, known)
                self.fill_hole(source.taip, known)
            case FromGlobal():
                result_type = self.traverse_fields(source.taip, source.fields)
                if source.by_reference:
                    result_type = PtrType(result_type)
                self.fill_hole(source.result_type, result_type)
                if known != result_type:
                    self.abort(source.token, "expected global to have different type")
            case FromGetField():
                self.states[source] = "BeingInferred"
                taip = self.infer(source)
                if taip is None:
                    self.abort(source.token, "check: FromGetField: failed to infer type of struct")
                if taip != known:
                    self.abort(source.token, "expected different")
            case FromMakeVariant():
                self.check_from_make_variant(source, known)
            case FromAdd():
                if source.base is None or source.addition is None:
                    self.abort(source.token, "check: FromAdd: expected two items on stack")
                self.fill_hole(source.taip, known)
                self.check(source.base, known)
                if isinstance(known, PtrType):
                    self.check(source.addition, I32())
                else:
                    self.check(source.addition, known)
            case other:
                assert_never(other)

    def check_from_make_variant(self, source: FromMakeVariant, known: Type):
        if not isinstance(known, CustomTypeType):
            self.abort(source.token, "check FromMakeVariant expected different")
        variant = self.lookup_type_definition(source.type_definition)
        assert(not isinstance(variant, Struct))
        cays = variant.cases[source.tag]
        if cays.taip is not None:
            source_type = without_holes.with_generics(cays.taip, known.generic_arguments)
            if source.source is None:
                self.abort(source.token, "check FromMakeVariant expected input")
            self.check(source.source, source_type)
        self.fill_hole(source.taip, known)

    def check_from_node(self, source: FromNode, known: Type):
        return_depth = source.ret
        node = self.nodes[source.index]
        match node:
            case FromIfExit():
                inferred = self.infer_if_exit(node, return_depth)
                if inferred is not None:
                    if inferred != known:
                        self.abort(source.token, "check FromIfExit: expected different")
                    return
                return_index = len(node.return_types) - return_depth - 1
                self.fill_hole(node.return_types[return_index], known)
                false_source = node.false_branch_returns[return_index]
                self.check(false_source, known)
                if node.true_branch_returns is not None:
                    self.check(node.true_branch_returns[return_index], known)
                if node.condition is None:
                    self.abort(source.token, "If is missing condition")
                self.check(node.condition, Bool())
            case FromIfEntry():
                return_index = len(node.parameters) - return_depth - 1
                self.fill_hole(node.parameters[return_index], known)
                self.check(node.arguments[return_index], known)
                if node.condition is None:
                    self.abort(source.token, "If is missing condition")
                self.check(node.condition, Bool())
            case FromCall():
                signature = self.lookup_signature(node.function)
                return_index = len(signature.returns) - return_depth - 1
                ret = signature.returns[return_index]
                argument_types = self.infer_over_array(node.arguments)
                if len(node.arguments) != len(signature.parameters):
                    self.call_argument_mismatch_error(node.token, signature, node.generic_arguments, argument_types)
                res = self.unify_types(node.generic_arguments, ret, known)
                if res != "Success":
                    self.call_argument_mismatch_error(node.token, signature, node.generic_arguments, argument_types)

                for argument, argument_type, parameter in zip(node.arguments, argument_types, signature.parameters):
                    parameter_taip = parameter.taip if isinstance(parameter, without_holes.NamedType) else parameter
                    monomorphic_parameter = self.try_with_generics(parameter_taip, node.generic_arguments)
                    if monomorphic_parameter is None:
                        if argument_type is None:
                            self.abort(node.token, "check FromCall: TODO")
                        res = self.unify_types(node.generic_arguments, parameter_taip, argument_type)
                        if res != "Success":
                            self.call_argument_mismatch_error(node.token, signature, node.generic_arguments, argument_types)
                    else:
                        if argument_type is None:
                            self.check(argument, monomorphic_parameter)
                        else:
                            if monomorphic_parameter != argument_type:
                                self.call_argument_mismatch_error(node.token, signature, node.generic_arguments, argument_types)
                if isinstance(signature, IntrinsicSignature):
                    self.check_generic_parameter_constraints(node.token, node.generic_arguments, signature, node.arguments)
                return
            case FromBlockExit():
                inferred = self.infer_block_exit(node, return_depth)
                if inferred is not None:
                    if inferred != known:
                        self.abort(source.token, "check: FromBlockExit: expected different")
                    return
                return_index = len(node.return_types) - return_depth - 1
                self.fill_hole(node.return_types[return_index], known)
                for break_return in node.break_returns[return_index].sources:
                    if break_return.source is None:
                        self.abort(node.token, "TODO: implement function break-types-mismatch-error")
                    self.check(break_return.source, known)
            case FromMatchExit():
                return_index = len(node.return_types) - return_depth - 1
                self.fill_hole(node.return_types[return_index], known)
                for returns in node.returns:
                    self.check(returns.returns[return_index], known)
                if node.scrutinee is None:
                    self.abort(source.token, "check FromMatchExit: expected scrutinee")
                if self.lookup_hole(node.scrutinee_type) is None:
                    scrutinee_type = self.infer(node.scrutinee)
                    if scrutinee_type is None:
                        self.abort(node.token, "check FromMatchExit: failed to infer type of scrutinee")
                    self.fill_hole(node.scrutinee_type, scrutinee_type)
                    self.check_match_scrutinee_variant(node, scrutinee_type)
            case FromMatchEntry():
                return_index = len(node.parameters) - return_depth - 1
                self.fill_hole(node.parameters[return_index], known)
                self.check(node.arguments[return_index], known)
            case FromLoopEntry():
                return_index = len(node.parameters) - return_depth - 1
                self.fill_hole(node.parameters[return_index], known)
                self.check(node.arguments[return_depth], known)
                self.check(node.next_arguments[return_index], known)
            case FromBlockEntry():
                return_index = len(node.parameters) - return_depth - 1
                self.fill_hole(node.parameters[return_index], known)
                self.check(node.arguments[return_index], known)
            case FromIndirectCall():
                return_index = len(node.return_types) - return_depth - 1
                return_type = self.lookup_hole(node.return_types[return_index])
                if return_type is None:
                    if node.function is None:
                        self.abort(node.token, "check IndirectCall: expected function as item on stack")
                    function_type = self.infer(node.function)
                    if function_type is None:
                        self.abort(node.token, "check IndirectCall: failed to infer function type")
                    if not isinstance(function_type, FunctionType):
                        self.abort(node.token, "check IndirectCall: expected function")
                    if len(function_type.parameters) != len(node.parameters) or len(function_type.returns) != len(node.return_types):
                        self.abort(node.token, "check IndirectCall: invalid annotation")
                    for param_hole, param in zip(node.parameters, function_type.parameters):
                        self.fill_hole(param_hole, param)
                    for ret_hole, ret in zip(node.return_types, function_type.returns):
                        self.fill_hole(ret_hole, ret)
                    for arg, param in zip(node.arguments, function_type.parameters):
                        self.check(arg, param)
                    return_type = function_type.returns[return_index]
                if return_type != known:
                    self.abort(node.token, "check IndirectCall: expected different")
            case PlaceHolder():
                assert False
            case FromStackAnnotation():
                return_index = len(node.types) - return_depth - 1
                annotated_with_holes = node.types[return_index]
                annotated = without_holes.without_holes(annotated_with_holes)
                if isinstance(annotated, Token):
                    self.abort(annotated, "TODO")
                if annotated != known:
                    self.stack_annotation_mismatch_error(node)
                self.check(node.arguments[return_index], known)
            case other:
                assert_never(other)

    def stack_annotation_mismatch_error(self, source: FromStackAnnotation):
        self.abort(source.token, "Stack doesn't match annotation")

    def check_match_scrutinee_variant(self, source: FromMatchExit, scrutinee_type: Type):
        if isinstance(scrutinee_type, PtrType):
            scrutinee_type = scrutinee_type.child
        if not isinstance(scrutinee_type, CustomTypeType):
            self.abort(source.token, "check FromMatchExit: expected variant")
        if scrutinee_type.type_definition != source.variant:
            self.abort(source.token, "match argument mismatch")

    def if_returns_mismatch_error(self, source: FromIfExit) -> Never:
        assert(source.true_branch_returns is not None)
        self.abort(source.token, "stack mismatch between if and else branch: ... TODO")

    def infer_block_exit(self, node: FromBlockExit, return_depth: int) -> Type | None:
        return_index = len(node.return_types) - return_depth - 1
        returns_of_breaks = node.break_returns[return_index]
        inferred_break_types: List[Type | None] = []
        for source in returns_of_breaks.sources:
            if source.source is None:
                self.abort(source.token, "TODO: implement function break-types-mismatch-error")
            inferred_break_types.append(self.infer(source.source))
        inferred = next((t for t in inferred_break_types if t is not None), None)
        if inferred is None:
            return None
        self.fill_hole(node.return_types[return_index], inferred)

        for taip in inferred_break_types:
            if taip is not None and taip != inferred:
                self.abort(node.token, "TODO: implement function break-types-mismatch-error")

        for inferred_break_type, source in zip(inferred_break_types, returns_of_breaks.sources):
            if inferred_break_type is not None:
                continue
            if source.source is None:
                self.abort(node.token, "TODO: implement function break-types-mismatch-error")
            self.check(source.source, inferred)

        return inferred


    def check(self, source: Source, known: Type):
        if source in self.states:
            state = self.states[source]
            if state == "BeingChecked":
                return
            if state == "BeingInferred":
                return
            if state.taip != known:
                raise InferenceException(self.path, source.token, "check expected different")
        self.states[source] = "BeingChecked"
        self.check_inner(source, known)
        self.states[source] = Known(known)

    def infer_inner(self, source: Source) -> Type | None:
        match source:
            case FromLocal():
                taip = self.lookup_hole(source.result_type)
                if taip is not None:
                    return taip
                local = self.locals[source.var]
                inferred = self.lookup_hole(local.taip)
                if inferred is None:
                    inferred = self.infer_local(local)
                    if inferred is None:
                        return None
                self.fill_hole(local.taip, inferred)
                taip = self.traverse_fields(inferred, source.fields)
                if source.by_reference:
                    taip = PtrType(taip)
                self.states[source] = Known(taip)
                self.check_local_assignments(local, inferred)
                self.fill_hole(source.result_type, taip)
                return taip
            case FromNumber():
                return I32()
            case FromNode():
                return self.infer_from_node(source)
            case FromMakeStruct():
                struct = self.lookup_type_definition(source.type_definition)
                if isinstance(struct, Variant):
                    self.abort(source.token, "`make` expected struct")
                if len(source.arguments) != len(struct.fields):
                    self.abort(source.token, "`make struct` expected more arguments")
                signature: Signature = self.signature_of_struct(source.type_definition)
                inferred = self.infer_signature_application(source.token, source.generic_arguments, source.arguments, signature, 0)
                if inferred is None:
                    return None
                self.fill_hole(source.taip, inferred)
                assert(isinstance(inferred, CustomTypeType))
                self.check_make_struct_fields(struct, source.arguments, inferred)
                return inferred
            case FromCast():
                if source.src is None:
                    self.abort(source.src_type.token, "cast expected item")
                src_type = self.infer(source.src)
                if src_type is None:
                    self.abort(source.src_type.token, "infer FromCast TODO: could not infer src-type")
                dst_type = without_holes.without_holes(source.dst_type)
                if isinstance(dst_type, Token):
                    self.abort(dst_type, "holes are not supported here yet")
                self.fill_hole(source.src_type, src_type)
                return dst_type
            case FromString():
                return PtrType(I8())
            case FromFunRef():
                signature = self.lookup_signature(source.function)
                generic_arguments = self.lookup_holes(source.generic_arguments)
                if generic_arguments is None:
                    return None
                parameters = tuple(param.taip if isinstance(param, without_holes.NamedType) else param for param in signature.parameters)
                parameters = tuple(without_holes.with_generics(t, generic_arguments) for t in parameters)
                returns = tuple(without_holes.with_generics(t, generic_arguments) for t in signature.returns)
                return FunctionType(source.token, parameters, returns)
            case FromCase():
                if source.scrutinee is None:
                    self.abort(source.token, "infer FromCase: expected scrutinee")
                scrutinee_type = self.lookup_hole(source.scrutinee_type)
                if scrutinee_type is None:
                    scrutinee_type = self.infer(source.scrutinee)
                    if scrutinee_type is None:
                        return None
                    self.fill_hole(source.scrutinee_type, scrutinee_type)
                variant = self.lookup_type_definition(source.variant)
                if isinstance(variant, Struct):
                    self.abort(source.token, "can only match on variants")
                if isinstance(scrutinee_type, PtrType):
                    scrutinee_variant_type = scrutinee_type.child
                else:
                    scrutinee_variant_type = scrutinee_type
                if not isinstance(scrutinee_variant_type, CustomTypeType):
                    self.abort(source.token, "can only match on variants")
                if scrutinee_variant_type.type_definition != source.variant:
                    self.abort(source.token, "match expected to match on different type")
                taip = variant.cases[source.tag].taip
                assert taip is not None
                taip = without_holes.with_generics(taip, scrutinee_variant_type.generic_arguments)
                if isinstance(scrutinee_type, PtrType):
                    taip = PtrType(taip)
                return taip
            case FromGlobal():
                known = self.traverse_fields(source.taip, source.fields)
                if source.by_reference:
                    known = PtrType(known)
                self.fill_hole(source.result_type, known)
                return known
            case FromLoad():
                if source.src is None:
                    self.abort(source.token, "`~` expected item")
                inferred = self.infer(source.src)
                if not isinstance(inferred, PtrType):
                    self.abort(source.token, "`~` expected ptr")
                self.fill_hole(source.taip, inferred.child)
                return inferred.child
            case FromProxied():
                taip = self.infer(source.source)
                if taip is None:
                    return None
                self.fill_hole(source.taip, taip)
                return taip
            case FromMakeVariant():
                inferred = self.lookup_hole(source.taip)
                if inferred is not None:
                    return inferred
                variant = self.lookup_type_definition(source.type_definition)
                assert(not isinstance(variant, Struct))
                cays = variant.cases[source.tag]
                generic_arguments = self.lookup_holes(source.generic_arguments)
                if generic_arguments is not None:
                    inferred = CustomTypeType(source.type_definition, generic_arguments)
                    self.fill_hole(source.taip, inferred)
                    self.check_from_make_variant(source, inferred)
                    if cays.taip is not None:
                        source_type = without_holes.with_generics(cays.taip, generic_arguments)
                        if source.source is None:
                            self.abort(source.token, "infer FromMakeVariant expected input")
                        self.check(source.source, source_type)
                    return inferred
                if cays.taip is None:
                    return None
                if source.source is None:
                    self.abort(source.token, "infer FromMakeVariant expected input")
                return None
            case FromGetField():
                if source.source is None:
                    self.abort(source.token, "infer FromGetField: expected item on stack")
                base_type = self.infer(source.source)
                if base_type is None:
                    return None
                self.fill_hole(source.base_type, base_type)
                if isinstance(base_type, PtrType):
                    on_ptr = True
                    custom_type = base_type.child
                else:
                    on_ptr = False
                    custom_type = base_type
                if not isinstance(custom_type, CustomTypeType):
                    self.abort(source.token, "infer FromGetField: expected struct or ptr to struct")
                struct = self.lookup_type_definition(custom_type.type_definition)
                if isinstance(struct, Variant):
                    self.abort(source.token, "infer FromGetField: expected struct")
                field_type = self.traverse_fields(base_type, source.fields)
                return PtrType(field_type) if on_ptr else field_type
            case FromAdd():
                if source.base is None or source.addition is None:
                    self.abort(source.token, "infer FromAdd: expected two items on stack")
                base_taip = self.infer(source.base)
                if base_taip is not None:
                    self.fill_hole(source.taip, base_taip)
                    if isinstance(base_taip, PtrType):
                        self.check(source.addition, I32())
                    else:
                        self.check(source.addition, base_taip)
                return base_taip
            case other:
                assert_never(other)

    def check_make_struct_fields(self, struct: Struct, arguments: Tuple[Source, ...], known: CustomTypeType):
        assert(len(arguments) == len(struct.fields))
        for field_source, field in zip(arguments, struct.fields):
            field_type = without_holes.with_generics(field.taip, known.generic_arguments)
            self.check(field_source, field_type)

    def signature_of_struct(self, handle: CustomTypeHandle) -> FunctionSignature:
        struct = self.lookup_type_definition(handle)
        assert(not isinstance(struct, Variant))
        generic_arguments = tuple(GenericType(struct.name, i) for i in range(len(struct.generic_parameters)))
        taip = CustomTypeType(handle, generic_arguments)
        return FunctionSignature(generic_parameters=struct.generic_parameters, parameters=struct.fields, returns=(taip,))

    def infer_from_node(self, source: FromNode) -> Type | None:
        node = self.nodes[source.index]
        return_depth = source.ret
        match node:
            case FromCall():
                signature = self.lookup_signature(node.function)
                return_index = len(signature.returns) - return_depth - 1
                inferred = self.infer_signature_application(node.token, node.generic_arguments, node.arguments, signature, return_index)
                if inferred is None:
                    return None
                if self.states[source] == "BeingInferred":
                    del self.states[source]
                self.check(source, inferred)
                return inferred
            case FromIfEntry():
                return_index = len(node.parameters) - return_depth - 1
                taip = self.infer(node.arguments[return_index])
                if taip is None:
                    return None
                self.fill_hole(node.parameters[return_index], taip)
                if node.condition is None:
                    self.abort(node.token, "If is missing condition")
                self.check(node.condition, Bool())
                return taip
            case FromMatchEntry():
                return_index = len(node.parameters) - return_depth - 1
                if node.scrutinee is None:
                    self.abort(node.token, "infer MatchEntry: expected scrutinee")
                argument_source = node.arguments[return_index]
                taip = self.infer(argument_source)
                if taip is None:
                    return None
                self.fill_hole(node.parameters[return_index], taip)
                if self.lookup_hole(node.scrutinee_type) is None:
                    scrutinee_type = self.infer(node.scrutinee)
                    if scrutinee_type is None:
                        return None
                    self.fill_hole(node.scrutinee_type, scrutinee_type)
                return taip
            case FromIfExit():
                return self.infer_if_exit(node, return_depth)
            case FromMatchExit():
                return_index = len(node.return_types) - return_depth - 1
                inferred_arms: List[Type | None] = []
                for returns in node.returns:
                    inferred_arms.append(self.infer(returns.returns[return_index]))
                inferred = next((t for t in inferred_arms if t is not None), None)
                if inferred is None:
                    return None
                for taip in inferred_arms:
                    if taip is None:
                        continue
                    if taip != inferred:
                        self.arms_type_mismatch_error(node)
                self.fill_hole(node.return_types[return_index], inferred)
                for returns in node.returns:
                    self.check(returns.returns[return_index], inferred)
                if node.scrutinee is None:
                    self.abort(node.token, "infer FromMatchExit: expected scrutinee")
                if self.lookup_hole(node.scrutinee_type) is None:
                    scrutinee_type = self.infer(node.scrutinee)
                    if scrutinee_type is None:
                        self.abort(node.token, "infer FromMatchExit: failed to infer type of scrutinee")
                    self.fill_hole(node.scrutinee_type, scrutinee_type)
                    self.check_match_scrutinee_variant(node, scrutinee_type)
                return inferred
            case FromBlockEntry():
                return_index = len(node.parameters) - return_depth - 1
                inferred = self.infer(node.arguments[return_index])
                if inferred is not None:
                    self.fill_hole(node.parameters[return_index], inferred)
                return inferred
            case FromBlockExit():
                return self.infer_block_exit(node, return_depth)
            case FromLoopEntry():
                return self.infer_loop_entry(node, return_depth)
            case FromIndirectCall():
                return_index = len(node.return_types) - return_depth - 1
                taip = self.lookup_hole(node.return_types[return_index])
                if taip is not None:
                    return taip
                if node.function is None:
                    self.abort(node.token, "infer IndirectCall: expected function as item on stack")
                function_type = self.infer(node.function)
                if function_type is None:
                    return None
                if not isinstance(function_type, FunctionType):
                    self.abort(node.token, "infer IndirectCall: expected function")
                if len(function_type.parameters) != len(node.parameters) or len(function_type.returns) != len(node.return_types):
                    self.abort(node.token, "infer IndirectCall: invalid annotation")
                for param_hole, param in zip(node.parameters, function_type.parameters):
                    self.fill_hole(param_hole, param)
                for ret_hole, ret in zip(node.return_types, function_type.returns):
                    self.fill_hole(ret_hole, ret)
                for arg, param in zip(node.arguments, function_type.parameters):
                    self.check(arg, param)
                return function_type.returns[return_index]
            case PlaceHolder():
                assert False
            case FromStackAnnotation():
                return_index = len(node.types) - return_depth - 1
                annotated = without_holes.without_holes(node.types[return_index])
                if isinstance(annotated, Token):
                    self.abort(annotated, "TODO")
                inferred = self.infer(node.arguments[return_index])
                if inferred is None:
                    self.check(node.arguments[return_index], annotated)
                    return annotated
                if inferred != annotated:
                    self.stack_annotation_mismatch_error(node)
                return inferred
            case other:
                assert_never(other)

    def infer_loop_entry(self, node: FromLoopEntry, return_depth: int) -> Type | None:
        return_index = len(node.parameters) - return_depth - 1
        inferred = self.infer(node.arguments[return_depth])
        if inferred is None:
            inferred = self.infer(node.next_arguments[return_index])
        if inferred is None:
            return None
        self.check(node.arguments[return_depth], inferred)
        self.check(node.next_arguments[return_index], inferred)
        self.fill_hole(node.parameters[return_index], inferred)
        return inferred

    def arms_type_mismatch_error(self, node: FromMatchExit) -> Never:
        self.abort(node.token, "TODO: arms_type_mismatch_error")

    def infer_if_exit(self, source: FromIfExit, return_depth: int) -> Type | None:
        return_index = len(source.return_types) - return_depth - 1
        if source.condition is None:
            self.abort(source.token, "If missing condition")
        self.check(source.condition, Bool())

        if source.true_branch_returns is not None:
            if len(source.true_branch_returns) != len(source.false_branch_returns):
                self.if_returns_mismatch_error(source)
            true_return = source.true_branch_returns[return_index]
            inferred = self.infer(true_return)
            if inferred is not None:
                inferred_from_false = self.infer(source.false_branch_returns[return_index])
                if inferred_from_false is not None:
                    if inferred_from_false != inferred:
                        self.if_returns_mismatch_error(source)
                    self.fill_hole(source.return_types[return_index], inferred)
                    return inferred
                self.fill_hole(source.return_types[return_index], inferred)
                self.check(source.false_branch_returns[return_index], inferred)
                return inferred
            else:
                inferred = self.infer(source.false_branch_returns[return_index])
                if inferred is None:
                    return None
                self.fill_hole(source.return_types[return_index], inferred)
                self.check(true_return, inferred)
                return inferred
        else:
            inferred = self.infer(source.false_branch_returns[return_index])
            if inferred is None:
                return None
            self.fill_hole(source.return_types[return_index], inferred)
            return inferred

    def infer_signature_application(
            self,
            token: Token,
            generic_arguments: Tuple[InferenceHole, ...],
            arguments: Tuple[Source, ...],
            signature: Signature,
            return_index: int) -> Type | None:
        if len(arguments) != len(signature.parameters):
            argument_types = self.infer_over_array(arguments)
            self.call_argument_mismatch_error(token, signature, generic_arguments, argument_types)
        for argument, parameter in zip(arguments, signature.parameters):
            argument_type = self.infer(argument)
            parameter_taip = parameter.taip if isinstance(parameter, without_holes.NamedType) else parameter
            if argument_type is not None:
                res = self.unify_types(generic_arguments, parameter_taip, argument_type)
                if res != "Success":
                    argument_types = self.infer_over_array(arguments)
                    self.call_argument_mismatch_error(token, signature, generic_arguments, argument_types)
        if isinstance(signature, IntrinsicSignature):
            self.check_generic_parameter_constraints(token, generic_arguments, signature, arguments)
        return self.try_with_generics(signature.returns[return_index], generic_arguments)

    def check_generic_parameter_constraints(self, token: Token, generic_arguments: Tuple[InferenceHole, ...], signature: IntrinsicSignature, arguments: Tuple[Source, ...]):
        for constraint in signature.constraints:
            match constraint:
                case MustBeOneOf():
                    taip = self.lookup_hole(generic_arguments[constraint.generic])
                    if taip is None:
                        continue
                    if taip in constraint.allowed or (isinstance(taip, PtrType) and "AnyPtr" in constraint.allowed):
                        continue
                    argument_types = self.infer_over_array(arguments)
                    self.call_argument_mismatch_error(token, signature, generic_arguments, argument_types)
                case MustSatisfyPredicate():
                    argument_types = self.infer_over_array(arguments)
                    error = constraint.predicate(argument_types)
                    if error is not None:
                        self.call_argument_mismatch_error(token, signature, generic_arguments, argument_types)

    def try_with_generics(self, taip: Type, generic_arguments: Tuple[InferenceHole, ...]) -> Type | None:
        match taip:
            case GenericType():
                return self.lookup_hole(generic_arguments[taip.generic_index])
            case PtrType(child):
                child_without_generics = self.try_with_generics(child, generic_arguments)
                if child_without_generics is None:
                    return None
                return PtrType(child_without_generics)
            case I8() | I32() | I64() | Bool():
                return taip
            case CustomTypeType():
                generic_args = self.try_all_with_generics(taip.generic_arguments, generic_arguments)
                if generic_args is None:
                    return None
                return CustomTypeType(taip.type_definition, generic_args)
            case FunctionType():
                parameters = self.try_all_with_generics(taip.parameters, generic_arguments)
                returns = self.try_all_with_generics(taip.returns, generic_arguments)
                if parameters is None or returns is None:
                    return None
                return FunctionType(taip.token, parameters, returns)

    def try_all_with_generics(self, types: Tuple[Type, ...], generic_arguments: Tuple[InferenceHole, ...]) -> Tuple[Type, ...] | None:
        without_generics: List[Type] = []
        for taip in types:
            t = self.try_with_generics(taip, generic_arguments)
            if t is None:
                return None
            without_generics.append(t)
        return tuple(without_generics)


    def infer(self, source: Source) -> Type | None:
        if source in self.states:
            state = self.states[source]
            match state:
                case Known():
                    return state.taip
                case "BeingInferred":
                    pass
                case "BeingChecked":
                    return None
        else:
            self.states[source] = "BeingInferred"

        taip = self.infer_inner(source)
        if taip is not None:
            self.states[source] = Known(taip)
        else:
            if source in self.states:
                if self.states[source] == "BeingInferred":
                    del self.states[source]
        return taip

    def infer_local(self, local: unstacked.Local) -> Type | None:
        taip = self.lookup_hole(local.taip)
        if taip is not None:
            return taip

        for assignment in local.assignments:
            if assignment.source is None:
                self.abort(assignment.token, "var assignment expected item on stack")
            if len(assignment.fields) == 0:
                taip = self.infer(assignment.source)
                if taip is not None:
                    if assignment.is_store:
                        return PtrType(taip)
                    else:
                        return taip
        return None

    def unify_types(self, generic_arguments: Tuple[InferenceHole, ...], holey: Type, known: Type) -> UnificationResult:
        match holey:
            case without_holes.GenericType():
                hole = generic_arguments[holey.generic_index]
                taip = self.lookup_hole(hole)
                if taip is None:
                    self.fill_hole(hole, known)
                    return "Success"
                if known != taip:
                    return GenericsContradict(holey.generic_index, taip, known)
                return "Success"
            case without_holes.PtrType():
                if not isinstance(known, without_holes.PtrType):
                    return "TypeMismatch"
                return self.unify_types(generic_arguments, holey.child, known.child)
            case without_holes.Bool() | without_holes.I8() | without_holes.I32() | without_holes.I64():
                if holey != known:
                    return "TypeMismatch"
                return "Success"
            case without_holes.CustomTypeType():
                if not isinstance(known, without_holes.CustomTypeType):
                    return "TypeMismatch"
                return self.unify_types_all(generic_arguments, holey.generic_arguments, known.generic_arguments)
            case without_holes.FunctionType():
                if not isinstance(known, without_holes.FunctionType):
                    return "TypeMismatch"
                res = self.unify_types_all(generic_arguments, holey.parameters, known.parameters)
                if res != "Success":
                    return res
                return self.unify_types_all(generic_arguments, holey.returns, known.returns)

    def unify_types_all(self, generic_arguments: Tuple[InferenceHole, ...], holey: Tuple[Type, ...], known: Tuple[Type, ...]) -> UnificationResult:
        for h, k in zip(holey, known):
            res = self.unify_types(generic_arguments, h, k)
            if res != "Success":
                return res
        return "Success"

    def traverse_fields(self, local_type: Type, fields: Tuple[unstacked.FieldAccess, ...]) -> Type:
        taip = local_type
        for access in fields:
            self.fill_hole(access.source_type, taip)
            if isinstance(taip, PtrType):
                taip = taip.child
            assert(isinstance(taip, CustomTypeType))
            custom_type = taip
            struc = self.lookup_type_definition(custom_type.type_definition)
            if isinstance(struc, Variant):
                self.abort(access.name, "variants do not have fields")

            type_at_field_index: None | Tuple[Type, int] = None
            for i, field in enumerate(struc.fields):
                if field.name.lexeme == access.name.lexeme:
                    type_at_field_index = (
                        without_holes.with_generics(field.taip, custom_type.generic_arguments),
                        i
                    )
                    break

            if type_at_field_index is None:
                self.abort(access.name, "field not found")
            (taip, field_index) = type_at_field_index
            self.fill_hole(access.target_type, taip)
            self.fill_field_hole(access.field_index, field_index)
        return taip


    def check_local_assignments(self, local: unstacked.Local, expected_local_type: Type):
        if local.assignments_checked:
            return
        local.assignments_checked = True
        for assignment in local.assignments:
            field_type = self.traverse_fields(expected_local_type, assignment.fields)
            if assignment.is_store:
                assert(isinstance(field_type, PtrType))
                source_type = field_type.child
            else:
                source_type = field_type

            self.fill_hole(assignment.taip, source_type)
            assert(assignment.source is not None)
            self.check(assignment.source, source_type)

    def fill_holes_scope(self, scope: unstacked.Scope) -> Scope:
        return Scope(scope.id, self.fill_holes_words(scope.words))

    def fill_holes_words(self, words: Tuple[unstacked.Word, ...]) -> Tuple[Word, ...]:
        return tuple(self.fill_holes_word(word) for word in words)

    def fill(self, hole: InferenceHole) -> Type:
        t = self.lookup_hole(hole)
        assert(t is not None)
        return t

    def fill_hole_field_access(self, field_access: unstacked.FieldAccess) -> FieldAccess:
        index = self.field_holes[field_access.field_index.index]
        assert(index is not None)
        source_type = self.fill(field_access.source_type)
        assert (isinstance(source_type, PtrType) and isinstance(source_type.child, CustomTypeType)) or isinstance(source_type, CustomTypeType)
        return FieldAccess(
                field_access.name,
                source_type,
                self.fill(field_access.target_type),
                index)

    def fill_holes_field_accesses(self, field_accesses: Tuple[unstacked.FieldAccess, ...]) -> Tuple[FieldAccess, ...]:
        return tuple(self.fill_hole_field_access(access) for access in field_accesses)

    def fill_holes_word(self, word: unstacked.Word) -> Word:
        match word:
            case unstacked.GetLocal():
                return GetLocal(
                    word.name,
                    word.var,
                    self.fill(word.var_type),
                    self.fill_holes_field_accesses(word.fields),
                    self.fill(word.result_type))
            case unstacked.Drop():
                return Drop(word.token, self.fill(word.taip))
            case unstacked.NumberWord():
                return word
            case unstacked.InitLocal():
                return InitLocal(word.name, self.fill(self.locals[word.local_id].taip), word.local_id)
            case unstacked.Eq():
                return Eq(word.token, self.fill(word.taip))
            case unstacked.NotEq():
                return NotEq(word.token, self.fill(word.taip))
            case unstacked.Ge():
                return Ge(word.token, assert_is_number(self.fill(word.taip)))
            case unstacked.Gt():
                return Gt(word.token, assert_is_number(self.fill(word.taip)))
            case unstacked.Le():
                return Le(word.token, assert_is_number(self.fill(word.taip)))
            case unstacked.Lt():
                return Lt(word.token, assert_is_number(self.fill(word.taip)))
            case unstacked.Add():
                return Add(word.token, assert_is_addable(self.fill(word.taip)))
            case unstacked.Sub():
                return Sub(word.token, assert_is_addable(self.fill(word.taip)))
            case unstacked.Mul():
                return Mul(word.token, assert_is_number(self.fill(word.taip)))
            case unstacked.Div():
                return Div(word.token, assert_is_number(self.fill(word.taip)))
            case unstacked.Mod():
                return Mod(word.token, assert_is_number(self.fill(word.taip)))
            case unstacked.Call():
                return Call(word.name, word.function, tuple(self.fill(t) for t in word.generic_arguments))
            case unstacked.Uninit():
                return Uninit(word.token, self.fill(word.taip))
            case unstacked.MatchVoid():
                return word
            case unstacked.Cast():
                dst = without_holes.without_holes(word.dst_type)
                assert(not isinstance(dst, Token)) # TODO: dst-type should have an InferenceHole which gets filled here
                return Cast(word.token, self.fill(word.src_type), dst)
            case unstacked.MakeStruct():
                taip = self.fill(word.taip)
                assert(isinstance(taip, CustomTypeType))
                return MakeStruct(word.token, taip)
            case unstacked.StringWord():
                return word
            case unstacked.RefLocal():
                return RefLocal(
                        word.name,
                        word.var,
                        self.fill_holes_field_accesses(word.fields))
            case unstacked.FunRef():
                return FunRef(Call(word.token, word.function, tuple(self.fill(t) for t in word.generic_arguments)))
            case unstacked.If():
                return If(word.token,
                          tuple(self.fill(p) for p in word.parameters),
                          tuple(self.fill(r) for r in word.returns) if word.returns is not None else None,
                          self.fill_holes_scope(word.true_branch),
                          self.fill_holes_scope(word.false_branch))
            case unstacked.SetGlobal():
                return SetLocal(word.name, word.globl, self.fill_holes_field_accesses(word.fields), self.fill(word.field_type))
            case unstacked.SetLocal():
                return SetLocal(word.name, word.local, self.fill_holes_field_accesses(word.fields), self.fill(word.field_type))
            case unstacked.MemGrow():
                return word
            case unstacked.SetStackSize():
                return word
            case unstacked.Match():
                taip = self.fill(word.type)
                by_ref = isinstance(taip, PtrType)
                if isinstance(taip, PtrType):
                    taip = taip.child
                assert(isinstance(taip, CustomTypeType))
                variant = self.lookup_type_definition(taip.type_definition)
                assert(not isinstance(variant, Struct))
                cases: List[MatchCase] = []
                for cays in word.cases:
                    case_type = variant.cases[cays.tag].taip
                    if case_type is not None:
                        case_type = without_holes.with_generics(case_type, taip.generic_arguments)
                    cases.append(MatchCase(case_type, cays.tag, self.fill_holes_scope(cays.body)))
                return Match(
                        word.token,
                        taip,
                        by_ref,
                        tuple(cases),
                        self.fill_holes_scope(word.default.body) if word.default is not None else None,
                        tuple(self.fill(p) for p in word.parameters),
                        tuple(self.fill(r) for r in word.returns) if word.returns is not None else None)
            case unstacked.Loop():
                return Loop(
                        word.token,
                        tuple(self.fill(p) for p in word.parameters),
                        tuple(self.fill(r) for r in word.returns) if word.returns is not None else None,
                        self.fill_holes_scope(word.body))
            case unstacked.Break():
                return word
            case unstacked.Load():
                return Load(word.token, self.fill(word.taip))
            case unstacked.StoreLocal():
                return StoreLocal(
                        word.name,
                        word.var,
                        self.fill(word.field_type),
                        self.fill_holes_field_accesses(word.fields))
            case unstacked.Flip():
                return Flip(word.token, self.fill(word.lower), self.fill(word.upper))
            case unstacked.Store():
                return Store(word.token, self.fill(word.taip))
            case unstacked.And():
                return And(word.token, assert_is_primitive(self.fill(word.taip)))
            case unstacked.Or():
                return Or(word.token, assert_is_primitive(self.fill(word.taip)))
            case unstacked.Not():
                return Not(word.token, assert_is_primitive(self.fill(word.taip)))
            case unstacked.Shl():
                return Shl(word.token, self.fill(word.taip))
            case unstacked.Shr():
                return Shr(word.token, self.fill(word.taip))
            case unstacked.Rotl():
                return Rotl(word.token, self.fill(word.taip))
            case unstacked.Rotr():
                return Rotr(word.token, self.fill(word.taip))
            case unstacked.Block():
                return Block(
                        word.token,
                         tuple(self.fill(t) for t in word.parameters),
                         None if word.returns is None else tuple(self.fill(t) for t in word.returns),
                         self.fill_holes_scope(word.body))
            case unstacked.MakeVariant():
                taip = self.fill(word.taip)
                assert(isinstance(taip, CustomTypeType))
                return MakeVariant(
                        word.token,
                        word.tag,
                        taip)
            case unstacked.GetField():
                on_ptr = isinstance(self.fill(word.base_type), PtrType)
                fields = self.fill_holes_field_accesses(word.fields)
                taip = fields[-1].target_type
                if on_ptr:
                    taip = PtrType(taip)
                return GetField(word.token, fields, on_ptr, taip)
            case unstacked.FieldInit():
                struct_type = self.fill(word.taip)
                assert isinstance(struct_type, CustomTypeType)
                struct = self.lookup_type_definition(struct_type.type_definition)
                assert isinstance(struct, Struct)
                field_type = without_holes.with_generics(struct.fields[word.field_index].taip, struct_type.generic_arguments)
                return FieldInit(word.name, field_type, word.field_index)
            case unstacked.MemCopy():
                return word
            case unstacked.MemFill():
                return word
            case unstacked.Sizeof():
                return word
            case unstacked.MakeStructNamed():
                t = self.fill(word.taip)
                assert(isinstance(t, CustomTypeType))
                return MakeStructNamed(
                        word.token,
                        t,
                        self.fill_holes_scope(word.body))
            case unstacked.IndirectCall():
                return IndirectCall(word.token, FunctionType(word.token,
                                                             tuple(self.fill(p) for p in word.parameters),
                                                             tuple(self.fill(r) for r in word.return_types)))
            case other:
                assert_never(other)

    def fill_holes_locals(self, locals: Dict[LocalId, unstacked.Local]) -> IndexedDict[LocalId, Local]:
        return IndexedDict.from_items(
                (local_id, Local(local.name, self.fill(local.taip), local.parameter is not None))
                for local_id, local in locals.items())

    def call_argument_mismatch_error(self, token: Token, signature: Signature, generic_arguments: Tuple[InferenceHole, ...], argument_types: Tuple[Type | None, ...]) -> Never:
        msg =  "incorrect arguments in call to:\n"
        msg += f"  fn {token.lexeme}"
        if len(signature.generic_parameters) != 0:
            msg += "<"
            for i, parameter in enumerate(signature.generic_parameters):
                if i != 0:
                    msg += ", "
                if isinstance(parameter, str):
                    msg += parameter
                if isinstance(parameter, Token):
                    msg += parameter.lexeme
            msg += ">"
        msg += "("
        for i, param in enumerate(signature.parameters):
            if i != 0:
                msg += ", "
            if isinstance(param, without_holes.NamedType):
                msg += f"{param.name.lexeme}: {self.type_lookup.type_pretty(param.taip)}"
            else:
                msg += f"{self.type_lookup.type_pretty(param)}"
        msg += ")"
        printed_inferred_header = False
        for generic_parameter, generic_argument in zip(signature.generic_parameters, generic_arguments):
            inferred = self.lookup_hole(generic_argument)
            if inferred is not None:
                if not printed_inferred_header:
                    msg += "\n\n  inferred:"
                    printed_inferred_header = True
                msg += f"\n    {generic_parameter.lexeme if isinstance(generic_parameter, Token) else generic_parameter} = {self.type_lookup.type_pretty(inferred)}"
        if len(signature.constraints) != 0:
            for constraint in signature.constraints:
                match constraint:
                    case MustBeOneOf():
                        generic_parameter = signature.generic_parameters[constraint.generic]
                        if isinstance(generic_parameter, str):
                            msg += f"\n  {generic_parameter} must be one of: "
                        else:
                            msg += f"\n  {generic_parameter.lexeme} must be one of: "
                        for i, taip in enumerate(constraint.allowed):
                            if i != 0:
                                msg += ", "
                            if taip == "AnyPtr":
                                msg += ".a"
                            else:
                                assert(taip != "AnyPtr")
                                msg += f"{self.type_lookup.type_pretty(cast(without_holes.Type, taip))}"
                    case MustSatisfyPredicate():
                        msg += f"\n  {constraint.description}"

        msg += "\ngot: ["
        for i, argument in enumerate(argument_types):
            if i != 0:
                msg += ", "
            if argument is None:
                msg += "_"
            else:
                msg += f"{self.type_lookup.type_pretty(argument)}"
        msg += "]"
        self.abort(token, msg)

