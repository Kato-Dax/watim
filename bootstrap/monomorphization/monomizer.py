from typing import Tuple, List, Iterable, Sequence, assert_never
from dataclasses import dataclass, field
import sys

from util import Ref, align_to
from format import Formattable, Formatter
import format
from indexed_dict import IndexedDict

from lexer import Token
from parsing.types import Bool, I8, I32, I64, GenericType
from resolving import LocalName, LocalId, ScopeId, GlobalId
import resolving as resolved
from monomorphization.type import TypeId, NamedTypeId, Type, CustomTypeHandle, PtrType, FunType as FunType, Struct, Variant, VariantCase, TypeDefinition, CustomTypeType
from inference import Number, String, Break
import inference as inferred

@dataclass
class Global(Formattable):
    name: Token
    type: TypeId
    reffed: bool
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Global", [self.name, self.type, self.reffed])

@dataclass
class Local(Formattable):
    name: LocalName
    type: TypeId
    reffed: bool
    is_parameter: bool
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Local", [self.name, self.type, self.reffed, self.is_parameter])

@dataclass(frozen=True, eq=True)
class Signature(Formattable):
    parameters: Tuple[NamedTypeId, ...]
    returns: Tuple[TypeId, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Signature", [format.Seq(self.parameters, multi_line=True), format.Seq(self.returns, multi_line=True)])

@dataclass(frozen=True)
class Extern(Formattable):
    name: Token
    extern_module: str
    extern_name: str
    signature: Signature
    def format(self, fmt: Formatter):
        fmt.named_record("Extern", [
            ("name", self.name),
            ("extern-module", self.extern_module),
            ("extern-name", self.extern_name),
            ("signature", self.signature)])

@dataclass
class Uninit(Formattable):
    type: TypeId
    copy_space_offset: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Uninit", [self.type, self.copy_space_offset])

@dataclass
class InitLocal(Formattable):
    name: Token
    type: TypeId
    local: LocalId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("InitLocal", [self.name, self.type, self.local])

@dataclass(frozen=True)
class FieldAccess(Formattable):
    name: Token
    source_type: TypeId
    target_type: TypeId
    field_index: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FieldAccess", [self.name, self.source_type, self.target_type, self.field_index])

@dataclass
class GetLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    fields: Tuple[FieldAccess, ...]
    result_type: TypeId
    copy_space_offset: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GetLocal", [self.name, self.var, self.result_type, format.Seq(self.fields, multi_line=True), self.copy_space_offset])

@dataclass
class RefLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    fields: Tuple[FieldAccess, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("RefLocal", [self.name, self.var, format.Seq(self.fields, multi_line=True)])

@dataclass(frozen=True)
class Add(Formattable):
    token: Token
    type: TypeId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord("Add", [self.type])])

@dataclass(frozen=True)
class Drop(Formattable):
    token: Token
    type: TypeId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord("Drop", [self.type])])

@dataclass
class MakeStruct(Formattable):
    type: TypeId
    copy_space_offset: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MakeStruct", [self.type, self.copy_space_offset])

@dataclass
class MakeStructNamed(Formattable):
    type: TypeId
    body: 'Scope'
    copy_space_offset: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MakeStructNamed", [self.type, self.copy_space_offset, self.body])

@dataclass
class Load(Formattable):
    type: TypeId
    copy_space_offset: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Load", [self.type, self.copy_space_offset])

@dataclass
class GetField(Formattable):
    token: Token
    fields: Tuple[FieldAccess, ...]
    type: TypeId
    on_ptr: bool
    copy_space_offset: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("GetField", [self.token, self.fields, self.type, self.on_ptr, self.copy_space_offset])

@dataclass(frozen=True)
class CommonIntrinsic(Formattable):
    token: Token
    taip: TypeId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Intrinsic", [self.token, format.UnnamedRecord(type(self).__name__, [self.taip])])

@dataclass(frozen=True)
class Gt(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Lt(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Ge(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Le(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Eq(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class NotEq(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Mul(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Div(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Mod(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Sub(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Shl(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Shr(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Rotl(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Rotr(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class And(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Or(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Not(CommonIntrinsic):
    pass

@dataclass(frozen=True)
class Store(CommonIntrinsic):
    pass

@dataclass
class StoreLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    type: TypeId
    fields: Tuple[FieldAccess, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("StoreLocal", [self.name, self.var, self.type, format.Seq(self.fields, multi_line=True)])

@dataclass
class SetLocal(Formattable):
    name: Token
    var: LocalId | GlobalId
    fields: Tuple[FieldAccess, ...]
    type: TypeId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("SetLocal", [self.name, self.var, format.Seq(self.fields, multi_line=True), self.type])

@dataclass
class MakeVariant(Formattable):
    tag: int
    type: TypeId
    copy_space_offset: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MakeVariant", [self.tag, self.type, self.copy_space_offset])

@dataclass
class Call(Formattable):
    name: Token
    function: 'FunctionHandle'
    copy_space_offset: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Call", [self.name, self.function, self.copy_space_offset])

@dataclass
class IndirectCall(Formattable):
    type: TypeId
    copy_space_offset: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("IndirectCall", [self.type, self.copy_space_offset])

@dataclass(frozen=True)
class FunRef(Formattable):
    call: Call
    table_index: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FunRef", [self.call, self.table_index])

@dataclass
class Block(Formattable):
    token: Token
    parameters: Tuple[TypeId, ...]
    returns: Tuple[TypeId, ...] | None
    body: 'Scope'
    def format(self, fmt: Formatter):
        fmt.named_record("Block", [
            ("token", self.token),
            ("parameters", self.parameters),
            ("returns", format.Optional(self.returns)),
            ("body", self.body)])

@dataclass
class Loop(Formattable):
    token: Token
    parameters: Tuple[TypeId, ...]
    returns: Tuple[TypeId, ...] | None
    body: 'Scope'
    def format(self, fmt: Formatter):
        fmt.named_record("Loop", [
            ("token", self.token),
            ("parameters", self.parameters),
            ("returns", format.Optional(self.returns)),
            ("body", self.body)])

@dataclass(frozen=True)
class Flip(Formattable):
    token: Token
    lower: TypeId
    upper: TypeId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Flip", [self.token, self.lower, self.upper])

@dataclass(frozen=True)
class Sizeof(Formattable):
    type: TypeId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Sizeof", [self.type])

@dataclass(frozen=True)
class Cast(Formattable):
    token: Token
    src: TypeId
    dst: TypeId
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Cast", [self.token, self.src, self.dst])

@dataclass(frozen=True)
class If(Formattable):
    token: Token
    parameters: Tuple[TypeId, ...]
    returns: Tuple[TypeId, ...] | None
    true_branch: 'Scope'
    false_branch: 'Scope'
    def format(self, fmt: Formatter):
        fmt.named_record("If", [
            ("token", self.token),
            ("parameters", self.parameters),
            ("returns", format.Optional(self.returns)),
            ("true-branch", self.true_branch),
            ("false-branch", self.false_branch)])

@dataclass(frozen=True)
class MatchCase(Formattable):
    type: TypeId | None
    tag: int
    body: 'Scope'
    def format(self, fmt: Formatter):
        fmt.unnamed_record("MatchCase", [format.Optional(self.type), self.tag, self.body])

@dataclass(frozen=True)
class Match(Formattable):
    type: TypeId
    by_ref: bool
    cases: Tuple[MatchCase, ...]
    default: 'Scope | None'
    parameters: Tuple[TypeId, ...]
    returns: Tuple[TypeId, ...] | None
    def format(self, fmt: Formatter):
        fmt.named_record("Match", [
            ("type", self.type),
            ("by-ref", self.by_ref),
            ("cases", format.Seq(self.cases, multi_line=True)),
            ("default", format.Optional(self.default)),
            ("parameters", format.Seq(self.parameters)),
            ("returns", format.Optional(self.returns))])

@dataclass
class FieldInit(Formattable):
    struct: CustomTypeHandle
    type: TypeId
    field_index: int
    copy_space_offset: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FieldInit", [self.type, self.field_index, self.copy_space_offset])

type Word = ( Number
            | String
            | Uninit
            | InitLocal
            | GetLocal
            | RefLocal
            | Add | Sub
            | Drop
            | MakeStruct | MakeStructNamed | MakeVariant
            | FieldInit
            | Load
            | GetField
            | Gt | Lt | Ge | Le
            | Eq | NotEq
            | Mul | Div | Mod
            | Shl | Shr | Rotl | Rotr
            | And | Or | Not
            | Store
            | inferred.MemGrow | inferred.MemCopy | inferred.MemFill | inferred.SetStackSize
            | StoreLocal
            | SetLocal
            | Call | FunRef
            | IndirectCall
            | Block | Loop | Break
            | Flip
            | Sizeof
            | Cast
            | If | Match | inferred.MatchVoid
            )

@dataclass(frozen=True)
class Scope(Formattable):
    id: ScopeId
    words: Tuple[Word, ...]
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Scope", [self.id, format.Seq(self.words, multi_line=True)])

@dataclass
class Function(Formattable):
    name: Token
    export: Token | None
    signature: Signature
    locals: IndexedDict[LocalId, Local]
    local_copy_space: int
    max_stack_returns: int
    body: Scope
    generic_arguments: Tuple[TypeId, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Function", [
            ("name", self.name),
            ("export", format.Optional(self.export)),
            ("signature", self.signature),
            ("generic-arguments", self.generic_arguments),
            ("locals", self.locals.formattable(lambda local: local, lambda local: local)),
            ("local-copy-space", self.local_copy_space),
            ("max-stack-returns", self.max_stack_returns),
            ("body", self.body)])

@dataclass(frozen=True, eq=True)
class FunctionHandle(Formattable):
    module: int
    index: int
    instance: int
    def format(self, fmt: Formatter):
        fmt.unnamed_record("FunctionHandle", [self.module, self.index, self.instance])

type ExternOrInstances = Extern | Tuple[Function, ...]

@dataclass
class Module(Formattable):
    type_definitions: Tuple[TypeDefinition, ...]
    globals: Tuple[Global, ...]
    static_data: bytes
    functions: Tuple[ExternOrInstances, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Module", [
            ("custom-types", format.Seq(self.type_definitions, multi_line=True)),
            ("globals", format.Seq(self.globals, multi_line=True)),
            ("functions", format.Seq(
                (format.Seq(f, multi_line=True) if not isinstance(f, Extern) else f for f in self.functions),
                multi_line=True))])

@dataclass(eq=True)
class CustomTypeKey(Formattable):
    handle: CustomTypeHandle
    generic_arguments: Tuple[TypeId, ...]
    type: Type | None = field(compare=False)
    def format(self, fmt: Formatter):
        if self.type is None:
            fmt.unnamed_record("CustomTypeKey", [self.handle, self.generic_arguments])
        else:
            fmt.unnamed_record("CustomTypeKey", [self.type])

type Key = CustomTypeKey | Type

@dataclass(frozen=True)
class Monomized(Formattable):
    types: Tuple[Type | None, ...]
    modules: IndexedDict[str, Module]
    sizes: Tuple[int, ...]
    function_table: Tuple[FunctionHandle, ...]
    def format(self, fmt: Formatter):
        fmt.named_record("Monomized", [
            ("types", format.Seq(tuple(format.Optional(t) for t in self.types), multi_line=True)),
            ("sizes", format.Seq(self.sizes)),
            ("modules", self.modules.formattable(format.Str, lambda m: m)),
            ("function-table", self.function_table)])

    def lookup_function(self, function: FunctionHandle) -> Function | Extern:
        f = self.modules.index(function.module).functions[function.index]
        match f:
            case Extern():
                return f
            case tuple():
                return f[function.instance]

    def lookup_global(self, id: GlobalId) -> Global:
        return self.modules.index(id.module).globals[id.index]

def primitive_types() -> List[Key | None]:
    return [Bool(), I8(), I32(), I64()]

BOOL_ID = TypeId(0)
I8_ID = TypeId(1)
I32_ID = TypeId(2)
I64_ID = TypeId(3)

type ExternOrInstancesMap = Extern | IndexedDict[Tuple[TypeId, ...], Ref[Function | None]]

@dataclass
class Ctx:
    module_id: int
    modules: Tuple[inferred.Module, ...]
    types: List[Key | None]
    function_table: List[FunctionHandle]
    type_definitions: List[TypeDefinition]
    functions: List[List[ExternOrInstancesMap]]

    def lookup_type(self, type: TypeId) -> Type:
        key = self.types[type.index]
        assert key is not None
        if isinstance(key, CustomTypeKey):
            assert key.type is not None
            return key.type
        return key

    def monomize_functions(self, functions: Iterable[inferred.Function | inferred.Extern]):
        for i, function in enumerate(functions):
            handle = resolved.FunctionHandle(self.module_id, i)
            match function:
                case inferred.Extern():
                    self.insert_extern(handle, self.monomize_extern(function))
                case inferred.Function():
                    if function.export is not None:
                        generic_arguments = ()
                        slot, _ = self.pre_insert_function(handle, generic_arguments)
                        slot.value = self.monomize_function(function, generic_arguments)

    def pre_insert_function(self, handle: resolved.FunctionHandle, generic_arguments: Tuple[TypeId, ...]) -> Tuple[Ref[Function | None], int]:
        slot: Ref[Function | None] = Ref(None)
        while len(self.functions) <= handle.module:
            self.functions.append([])
        module_functions = self.functions[handle.module]
        while len(module_functions) <= handle.index:
            module_functions.append(IndexedDict())
        instances = module_functions[handle.index]
        assert not isinstance(instances, Extern)
        assert generic_arguments not in instances
        index = len(instances)
        instances[generic_arguments] = slot
        return slot, index

    def monomize_function(self, function: inferred.Function, generic_arguments: Tuple[TypeId, ...]) -> Function:
        locals = self.monomize_locals(function.locals, generic_arguments)
        ctx = WordCtx(self, locals, None)
        return Function(
                function.name,
                function.export,
                self.monomize_signature(function.signature, generic_arguments),
                locals,
                (1 << 32) - 1,
                (1 << 32) - 1,
                ctx.monomize_scope(function.body, generic_arguments),
                generic_arguments)

    def monomize_locals(self, locals: IndexedDict[LocalId, inferred.Local], generic_arguments: Tuple[TypeId, ...]) -> IndexedDict[LocalId, Local]:
        return IndexedDict.from_items((id, self.monomize_local(local, generic_arguments)) for id, local in locals.items())

    def monomize_local(self, local: inferred.Local, generic_arguments: Tuple[TypeId, ...]) -> Local:
        return Local(local.name, self.monomize_type(local.type, generic_arguments), False, local.is_parameter)

    def monomize_extern(self, extern: resolved.Extern) -> Extern:
        return Extern(extern.name, extern.extern_module, extern.extern_name, self.monomize_signature(extern.signature, ()))

    def insert_extern(self, handle: resolved.FunctionHandle, extern: Extern):
        while len(self.functions) <= handle.module:
            self.functions.append([])
        module_functions = self.functions[handle.module]
        while len(module_functions) <= handle.index:
            module_functions.append(IndexedDict())
        module_functions[handle.index] = extern

    def monomize_signature(self, signature: resolved.FunctionSignature, generic_arguments: Tuple[TypeId, ...]) -> Signature:
        return Signature(self.monomize_named_types(signature.parameters, generic_arguments),
                         self.monomize_types(signature.returns, generic_arguments))

    def monomize_types(self, types: Iterable[inferred.Type], generic_arguments: Tuple[TypeId, ...]) -> Tuple[TypeId, ...]:
        return tuple(self.monomize_type(t, generic_arguments) for t in types)

    def monomize_type(self, type: inferred.Type, generic_arguments: Tuple[TypeId, ...]) -> TypeId:
        match type:
            case Bool():
                return BOOL_ID
            case I8():
                return I8_ID
            case I32():
                return I32_ID
            case I64():
                return I64_ID
            case GenericType():
                return generic_arguments[type.generic_index]
        type_id = TypeId(len(self.types))
        self.types.append(None)

        match type:
            case inferred.PtrType():
                key: Key | None = PtrType(self.monomize_type(type.child, generic_arguments))
            case inferred.FunctionType():
                key = FunType(self.monomize_types(type.parameters, generic_arguments), self.monomize_types(type.returns, generic_arguments))
            case inferred.CustomTypeType():
                key = CustomTypeKey(type.type_definition, self.monomize_types(type.generic_arguments, generic_arguments), None)
            case other:
                assert_never(other)

        try:
            index = self.types.index(key)
            if type_id.index + 1 == len(self.types):
                assert self.types.pop() is None
            return TypeId(index)
        except ValueError:
            self.types[type_id.index] = key
            if isinstance(key, CustomTypeKey):
                if isinstance(type, inferred.CustomTypeType):
                    monomized_type = self.monomize_custom_type(type, key.generic_arguments)
                    key.type = CustomTypeType(monomized_type)
            return type_id

    def monomize_named_type(self, type: inferred.NamedType, generic_arguments: Tuple[TypeId, ...]) -> NamedTypeId:
        return NamedTypeId(type.name, self.monomize_type(type.taip, generic_arguments))

    def monomize_custom_type(self, custom_type: inferred.CustomTypeType, generic_arguments: Tuple[TypeId, ...]) -> CustomTypeHandle:
        type_definitions = self.modules[custom_type.type_definition.module].type_definitions
        type_definition = type_definitions[custom_type.type_definition.index]
        match type_definition:
            case resolved.Struct():
                fields = self.monomize_named_types(type_definition.fields, generic_arguments)
                return self.add_monomized_type_definition(Struct(type_definition.name, fields))
            case resolved.Variant():
                def monomize_case(case: resolved.VariantCase):
                    return VariantCase(
                            case.name,
                            None if case.taip is None else self.monomize_type(case.taip, generic_arguments))
                cases = tuple(map(monomize_case, type_definition.cases))
                return self.add_monomized_type_definition(Variant(type_definition.name, cases))

    def type_definitions_equiv(self, a: TypeDefinition, b: TypeDefinition) -> bool:
        if isinstance(a, Struct) and isinstance(b, Struct):
            return tuple(nt.taip for nt in a.fields) == tuple(nt.taip for nt in b.fields)
        if isinstance(a, Variant) and isinstance(b, Variant):
            return tuple(case.taip for case in a.cases) == tuple(case.taip for case in b.cases)
        return False

    def add_monomized_type_definition(self, type: TypeDefinition) -> CustomTypeHandle:
        try:
            return CustomTypeHandle(self.module_id,
                                    next(i for i, td in enumerate(self.type_definitions) if self.type_definitions_equiv(type, td)))
        except StopIteration:
            index = len(self.type_definitions)
            self.type_definitions.append(type)
            return CustomTypeHandle(self.module_id, index)

    def monomize_named_types(self, types: Tuple[inferred.NamedType, ...], generic_arguments: Tuple[TypeId, ...]) -> Tuple[NamedTypeId, ...]:
        return tuple(self.monomize_named_type(t, generic_arguments) for t in types)

    def monomize_globals(self, globals: Iterable[inferred.Global]) -> Tuple[Global, ...]:
        return tuple(map(self.monomize_global, globals))

    def monomize_global(self, globl: inferred.Global) -> Global:
        return Global(
                globl.name,
                self.monomize_type(globl.taip, ()),
                globl.reffed)

    def fields_go_through_ptr(self, fields: Sequence[FieldAccess]) -> bool:
        return any(isinstance(self.lookup_type(field.source_type), PtrType) for field in fields)

    def lookup_checked_function(self, handle: inferred.FunctionHandle) -> inferred.Extern | inferred.Function:
        return self.modules[handle.module].functions[handle.index]

    def lookup_function(self, handle: inferred.FunctionHandle, generic_arguments: Tuple[TypeId, ...]) -> int | None:
        if len(self.functions) <= handle.module:
            return None
        module_functions = self.functions[handle.module]
        if len(module_functions) <= handle.index:
            return None
        instances = module_functions[handle.index]
        assert not isinstance(instances, Extern)
        try:
            return instances.index_of(generic_arguments)
        except KeyError:
            return None

    def insert_into_function_table(self, handle: FunctionHandle) -> int:
        try:
            return self.function_table.index(handle)
        except ValueError:
            index = len(self.function_table)
            self.function_table.append(handle)
            return index

@dataclass
class WordCtx:
    ctx: Ctx
    locals: IndexedDict[LocalId, Local]
    struct_env: CustomTypeHandle | None

    def mark_var_reffed(self, var: LocalId | GlobalId):
        match var:
            case LocalId():
                self.locals[var].reffed = True
            case GlobalId():
                self.ctx.modules[var.module].globals[var.index].reffed = True

    def monomize_scope(self, scope: inferred.Scope, generic_arguments: Tuple[TypeId, ...]) -> Scope:
        return Scope(scope.id, self.monomize_words(scope.words, generic_arguments))

    def monomize_words(self, words: Iterable[inferred.Word], generic_arguments: Tuple[TypeId, ...]) -> Tuple[Word, ...]:
        return tuple(self.monomize_word(word, generic_arguments) for word in words)

    def monomize_word(self, word: inferred.Word, generic_arguments: Tuple[TypeId, ...]) -> Word:
        match word:
            case inferred.Number() | inferred.String():
                return word
            case inferred.InitLocal():
                return InitLocal(word.name, self.ctx.monomize_type(word.taip, generic_arguments), word.local)
            case inferred.GetLocal():
                return GetLocal(word.name,
                                word.var,
                                self.monomize_field_accesses(word.fields, generic_arguments),
                                self.ctx.monomize_type(word.result_taip, generic_arguments),
                                (1 << 32) - 1)
            case inferred.Uninit():
                return Uninit(self.ctx.monomize_type(word.taip, generic_arguments), (1 << 32) - 1)
            case inferred.Add():
                return Add(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Drop():
                return Drop(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.RefLocal():
                fields = self.monomize_field_accesses(word.fields, generic_arguments)
                if not self.ctx.fields_go_through_ptr(fields):
                    self.mark_var_reffed(word.var)
                return RefLocal(word.name, word.var, fields)
            case inferred.MakeStruct():
                return MakeStruct(self.ctx.monomize_type(word.taip, generic_arguments), (1 << 32) - 1)
            case inferred.MakeStructNamed():
                outer_struct_env = self.struct_env
                type_id = self.ctx.monomize_type(word.taip, generic_arguments)
                type = self.ctx.lookup_type(type_id)
                assert isinstance(type, CustomTypeType)
                self.struct_env = type.handle
                body = self.monomize_scope(word.scope, generic_arguments)
                self.struct_env = outer_struct_env
                return MakeStructNamed(type_id, body, 0)
            case inferred.Load():
                return Load(self.ctx.monomize_type(word.taip, generic_arguments), (1 << 32) - 1)
            case inferred.GetField():
                return GetField(word.token, self.monomize_field_accesses(word.fields, generic_arguments), self.ctx.monomize_type(word.type, generic_arguments), word.on_ptr, (1 << 32) - 1)
            case inferred.StoreLocal():
                return StoreLocal(word.name, word.var, self.ctx.monomize_type(word.type, generic_arguments), self.monomize_field_accesses(word.fields, generic_arguments))
            case inferred.Gt():
                return Gt(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Lt():
                return Lt(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Ge():
                return Ge(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Le():
                return Le(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Eq():
                return Eq(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.NotEq():
                return NotEq(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Mul():
                return Mul(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Div():
                return Div(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Mod():
                return Mod(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Sub():
                return Sub(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Shl():
                return Shl(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Shr():
                return Shr(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Rotl():
                return Rotl(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Rotr():
                return Rotr(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.And():
                return And(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Or():
                return Or(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Not():
                return Not(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Store():
                return Store(word.token, self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.MemCopy():
                return word
            case inferred.MemGrow():
                return word
            case inferred.MemFill():
                return word
            case inferred.MakeVariant():
                return MakeVariant(word.tag, self.ctx.monomize_type(word.taip, generic_arguments), (1 << 32) - 1)
            case inferred.Call():
                return self.monomize_call(word, generic_arguments)
            case inferred.IndirectCall():
                return IndirectCall(self.ctx.monomize_type(word.taip, generic_arguments), (1 << 32) - 1)
            case inferred.Block():
                return Block(
                        word.token,
                        self.ctx.monomize_types(word.parameters, generic_arguments),
                        self.ctx.monomize_types(word.returns, generic_arguments) if word.returns is not None else None,
                        self.monomize_scope(word.body, generic_arguments))
            case inferred.Loop():
                return Loop(
                        word.token,
                        self.ctx.monomize_types(word.parameters, generic_arguments),
                        self.ctx.monomize_types(word.returns, generic_arguments) if word.returns is not None else None,
                        self.monomize_scope(word.body, generic_arguments))
            case inferred.Break():
                return word
            case inferred.Flip():
                return Flip(word.token, self.ctx.monomize_type(word.lower, generic_arguments), self.ctx.monomize_type(word.upper, generic_arguments))
            case inferred.Sizeof():
                return Sizeof(self.ctx.monomize_type(word.taip, generic_arguments))
            case inferred.Cast():
                return Cast(word.token, self.ctx.monomize_type(word.src, generic_arguments), self.ctx.monomize_type(word.dst, generic_arguments))
            case inferred.If():
                return If(
                        word.token,
                        self.ctx.monomize_types(word.parameters, generic_arguments),
                        self.ctx.monomize_types(word.returns, generic_arguments) if word.returns is not None else None,
                        self.monomize_scope(word.true_branch, generic_arguments),
                        self.monomize_scope(word.false_branch, generic_arguments))
            case inferred.Match():
                def monomize_case(case: inferred.MatchCase):
                    return MatchCase(
                            self.ctx.monomize_type(case.taip, generic_arguments) if case.taip is not None else None,
                            case.tag,
                            self.monomize_scope(case.body, generic_arguments))
                return Match(
                        self.ctx.monomize_type(word.variant, generic_arguments),
                        word.by_ref,
                        tuple(map(monomize_case, word.cases)),
                        None if word.default is None else self.monomize_scope(word.default, generic_arguments),
                        self.ctx.monomize_types(word.parameters, generic_arguments),
                        self.ctx.monomize_types(word.returns, generic_arguments) if word.returns is not None else None)
            case inferred.MatchVoid():
                return word
            case inferred.FunRef():
                call = self.monomize_call(word.call, generic_arguments)
                return FunRef(call, self.ctx.insert_into_function_table(call.function))
            case inferred.SetLocal():
                return SetLocal(word.name,
                                word.var,
                                self.monomize_field_accesses(word.fields, generic_arguments),
                                self.ctx.monomize_type(word.type, generic_arguments))
            case inferred.SetStackSize():
                return word
            case inferred.FieldInit():
                assert self.struct_env is not None
                return FieldInit(self.struct_env, self.ctx.monomize_type(word.type, generic_arguments), word.field_index, (1 << 32) - 1)

    def monomize_call(self, word: inferred.Call, generic_arguments: Tuple[TypeId, ...]) -> Call:
        generic_arguments_of_this_call = self.ctx.monomize_types(word.generic_arguments, generic_arguments)
        function = self.ctx.lookup_checked_function(word.function)
        match function:
            case inferred.Extern():
                return Call(word.name, FunctionHandle(word.function.module, word.function.index, 0), (1 << 32) - 1)
            case inferred.Function():
                instance = self.ctx.lookup_function(word.function, generic_arguments_of_this_call)
                if instance is None:
                    slot, instance = self.ctx.pre_insert_function(word.function, generic_arguments_of_this_call)
                    slot.value = self.ctx.monomize_function(function, generic_arguments_of_this_call)
                return Call(word.name, FunctionHandle(word.function.module, word.function.index, instance), (1 << 32) - 1)

    def monomize_field_accesses(self, fields: Iterable[inferred.FieldAccess], generic_arguments: Tuple[TypeId, ...]) -> Tuple[FieldAccess, ...]:
        return tuple(self.monomize_field_access(field, generic_arguments) for field in fields)

    def monomize_field_access(self, field: inferred.FieldAccess, generic_arguments: Tuple[TypeId, ...]) -> FieldAccess:
        return FieldAccess(
                name=field.name,
                source_type=self.ctx.monomize_type(field.source_type, generic_arguments),
                target_type=self.ctx.monomize_type(field.target_type, generic_arguments),
                field_index=field.field_index)

def monomize(modules: IndexedDict[str, inferred.Module]) -> Monomized:
    monomized_modules: IndexedDict[str, Module] = IndexedDict()
    functions: List[List[ExternOrInstancesMap]] = []
    types = primitive_types()
    function_table: List[FunctionHandle] = []
    for i, (path, module) in enumerate(modules.items()):
        ctx = Ctx(
                module_id=i,
                modules=tuple(modules.values()),
                types=types,
                function_table=function_table,
                type_definitions=[],
                functions=functions)
        ctx.monomize_functions(module.functions)
        monomized_modules[path] = Module(
                globals=ctx.monomize_globals(module.globals),
                type_definitions=tuple(ctx.type_definitions),
                static_data=module.static_data,
                functions=())

    for i, monomized_module in enumerate(monomized_modules.values()):
        if i < len(functions):
            module_functions = list(monomized_module.functions)
            for j, function in enumerate(functions[i]):
                while len(module_functions) <= j:
                    module_functions.append(())
                match function:
                    case IndexedDict():
                        def assert_value_not_none(slot: Ref[Function | None]) -> Function:
                            assert slot.value is not None
                            return slot.value
                        module_functions[j] = tuple(map(assert_value_not_none, function.values()))
                    case Extern():
                        module_functions[j] = function
            monomized_module.functions = tuple(module_functions)

    sizes = compute_sizes(monomized_modules, tuple(types))
    measure_copy_space(monomized_modules, types, sizes)
    def key_type(key: Key | None) -> Type | None:
        if key is None:
            return None
        if isinstance(key, CustomTypeKey):
            assert key.type is not None
            return key.type
        return key
    return Monomized(tuple(key_type(t) for t in types), monomized_modules, sizes, tuple(function_table))

def compute_sizes(modules: IndexedDict[str, Module], types: Tuple[Key | None, ...]) -> Tuple[int, ...]:
    sizes = list((1 << 32) - 1 for _ in types)
    for i in range(len(types)):
        compute_size(modules, sizes, types, i)
    return tuple(sizes)

def compute_size(modules: IndexedDict[str, Module], sizes: List[int], types: Tuple[Key | None, ...], index: int):
    if sizes[index] != (1 << 32) - 1:
        return
    type = types[index]
    if isinstance(type, CustomTypeKey):
        type = type.type
        assert type is not None
        assert isinstance(type, CustomTypeType)
    match type:
        case None:
            size = (1 << 32) - 2
        case Bool():
            size = 4
        case I8():
            size = 1
        case I32():
            size = 4
        case I64():
            size = 8
        case PtrType():
            size = 4
        case CustomTypeType():
            size = compute_custom_type_size(modules, sizes, types, modules.index(type.handle.module).type_definitions[type.handle.index])
        case FunType():
            size = 4
        case other:
            assert_never(other)

    sizes[index] = size

def compute_custom_type_size(modules: IndexedDict[str, Module], sizes: List[int], types: Tuple[Key | None, ...], type: TypeDefinition) -> int:
    match type:
        case Struct():
            size = 0
            largest_field = 0
            for i, field in enumerate(type.fields):
                field_size = compute_typeid_size(modules, sizes, types, field.taip)
                largest_field = max(field_size, largest_field)
                size += field_size
                if i + 1 < len(type.fields):
                    next_field_size = compute_typeid_size(modules, sizes, types, type.fields[i + 1].taip)
                    size = align_to(size, min(4, next_field_size))
            return align_to(size, largest_field)
        case Variant():
            size = 0
            for i, case in enumerate(type.cases):
                if case.taip is not None:
                    size = max(size, compute_typeid_size(modules, sizes, types, case.taip))
            return size + 4

def compute_typeid_size(modules: IndexedDict[str, Module], sizes: List[int], types: Tuple[Key | None, ...], type: TypeId) -> int:
    size = sizes[type.index]
    if size == (1 << 32) - 1:
        compute_size(modules, sizes, types, type.index)
        return compute_typeid_size(modules, sizes, types, type)
    else:
        return size

def measure_copy_space(modules: IndexedDict[str, Module], types: Sequence[Key | None], sizes: Tuple[int, ...]):
    for module in modules.values():
        module_measure_copy_space(tuple(modules.values()), module, types, sizes)

def module_measure_copy_space(modules: Tuple[Module, ...], module: Module, types: Sequence[Key | None], sizes: Tuple[int, ...]):
    for function in module.functions:
        match function:
            case Extern():
                pass
            case instances:
                for instance in instances:
                    function_measure_copy_space(modules, instance, types, sizes)

def type_size(sizes: Sequence[int], type: TypeId) -> int:
    return sizes[type.index]

def can_live_in_reg(sizes: Sequence[int], type: TypeId) -> bool:
    return type_size(sizes, type) <= 8

def local_lives_in_memory(sizes: Sequence[int], local: Local) -> bool:
    return (not can_live_in_reg(sizes, local.type)) or local.reffed

def global_lives_in_memory(sizes: Sequence[int], globl: Global) -> bool:
    return (not can_live_in_reg(sizes, globl.type)) or globl.reffed

def field_offset(sizes: Sequence[int], struct: Struct, field_index: int) -> int:
    offset = 0
    for i, struct_field in enumerate(struct.fields):
        if i == field_index:
            return offset
        field_size = type_size(sizes, struct_field.taip)
        offset += field_size
        if i + 1 < len(struct.fields):
            next_field_size = type_size(sizes, struct.fields[i + 1].taip)
            offset = align_to(offset, min(next_field_size, 4))
    assert False

@dataclass
class CopySpaceCtx:
    modules: Tuple[Module, ...]
    types: Sequence[Key | None]
    sizes: Tuple[int, ...]
    struct_offset: None | int
    max_stack_returns: int

    def words_measure_copy_space(self, words: Tuple[Word, ...], offset: Ref[int]):
        for word in words:
            self.word_measure_copy_space(word, offset)

    def call_measure_copy_space(self, returns: Sequence[TypeId], offset: Ref[int]) -> int:
        copy_space_offset = returns_measure_copy_space(returns, self.sizes, offset)
        if copy_space_offset != offset.value:
            self.max_stack_returns = max(self.max_stack_returns, len(returns))
        return copy_space_offset

    def word_measure_copy_space(self, word: Word, offset: Ref[int]):
        match word:
            case GetLocal():
                type = word.result_type
            case GetField():
                type = word.type
            case Uninit():
                type = word.type
            case MakeStruct():
                type = word.type
            case MakeStructNamed():
                word.copy_space_offset = offset.value
                offset.value += type_size(self.sizes, word.type)
                prev_struct_offset = self.struct_offset
                self.struct_offset = word.copy_space_offset
                self.words_measure_copy_space(word.body.words, offset)
                self.struct_offset = prev_struct_offset
                return
            case FieldInit():
                struct = self.modules[word.struct.module].type_definitions[word.struct.index]
                assert not isinstance(struct, Variant)
                field_off = field_offset(self.sizes, struct, word.field_index)
                assert self.struct_offset is not None
                word.copy_space_offset = self.struct_offset + field_off
                return
            case MakeVariant():
                type = word.type
            case Load():
                type = word.type
            case Call():
                function = self.modules[word.function.module].functions[word.function.index]
                match function:
                    case Extern():
                        signature = function.signature
                    case other:
                        signature = other[word.function.instance].signature
                word.copy_space_offset = self.call_measure_copy_space(signature.returns, offset)
                return
            case IndirectCall():
                fun_type = self.types[word.type.index]
                assert isinstance(fun_type, FunType)
                word.copy_space_offset = self.call_measure_copy_space(fun_type.returns, offset)
                return
            case If():
                self.words_measure_copy_space(word.true_branch.words, offset)
                self.words_measure_copy_space(word.false_branch.words, offset)
                return
            case Block() | Loop():
                self.words_measure_copy_space(word.body.words, offset)
                return
            case Match():
                for case in word.cases:
                    self.words_measure_copy_space(case.body.words, offset)
                if word.default is not None:
                    self.words_measure_copy_space(word.default.words, offset)
                return
            case _:
                return
        if not can_live_in_reg(self.sizes, type):
            word.copy_space_offset = offset.value
            offset.value += type_size(self.sizes, type)

def returns_measure_copy_space(returns: Sequence[TypeId], sizes: Sequence[int], offset: Ref[int]) -> int:
    value = offset.value
    for type in returns:
        if not can_live_in_reg(sizes, type):
            offset.value += type_size(sizes, type)
    return value

def function_measure_copy_space(modules: Tuple[Module, ...], function: Function, types: Sequence[Key | None], sizes: Tuple[int, ...]):
    ctx = CopySpaceCtx(modules, types, sizes, None, 0)
    function.local_copy_space = 0
    local_copy_space = Ref(0)
    ctx.words_measure_copy_space(function.body.words, local_copy_space)
    function.local_copy_space = local_copy_space.value
    function.max_stack_returns = ctx.max_stack_returns

