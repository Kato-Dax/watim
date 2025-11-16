from typing import List, Dict, Set, Tuple, Sequence, TypeGuard, assert_never
from dataclasses import dataclass, field
import unittest
import copy

from util import Ref, Lazy, intercalate, align_to
from format import Formattable, Formatter
from indexed_dict import IndexedDict
from lexer import Token
from parsing.types import I8, I32, I64, Bool, PrimitiveType
from parsing.parser import NumberWord, BreakWord
import resolving.resolver as resolver
import resolving.type_without_holes as without_holes
from resolving import LocalName, ScopeId, GlobalId, LocalId
from checking.intrinsics import IntrinsicDrop, IntrinsicMemCopy, IntrinsicMemFill, IntrinsicMemGrow, IntrinsicSetStackSize
from checking.words import MatchVoidWord as MatchVoidWord
import checking as checked

@dataclass
class PtrType(Formattable):
    child: 'Type'
    def __str__(self) -> str:
        return f"PtrType(child={str(self.child)})"

    def size(self) -> int:
        return 4

    def can_live_in_reg(self) -> bool:
        return True

@dataclass
class NamedType(Formattable):
    name: Token
    taip: 'Type'
    def format(self, fmt: Formatter):
        fmt.unnamed_record("NamedType", [self.name, self.taip])

@dataclass
class FunctionType(Formattable):
    token: Token
    parameters: List['Type']
    returns: List['Type']

    def size(self) -> int:
        return 4

    def can_live_in_reg(self) -> bool:
        return True

@dataclass
class Struct:
    name: Token
    fields: Lazy[List[NamedType]]
    generic_parameters: List['Type']

    def __str__(self) -> str:
        return f"Struct(name={str(self.name)})"

    def size(self) -> int:
        field_sizes = [field.taip.size() for field in self.fields.get()]
        size = 0
        largest_field = 0
        for i, field_size in enumerate(field_sizes):
            largest_field = max(largest_field, field_size)
            size += field_size
            if i + 1 < len(field_sizes):
                next_field_size = field_sizes[i + 1]
                size = align_to(size, min(next_field_size, 4))
        return align_to(size, largest_field)

    def field_offset(self, field_index: int) -> int:
        fields = self.fields.get()
        offset = 0
        for i in range(0, field_index):
            field_size = fields[i].taip.size()
            offset += field_size
            if i + 1 < len(fields):
                next_field_size = fields[i + 1].taip.size()
                offset = align_to(offset, min(next_field_size, 4))
        return offset

@dataclass
class VariantCase:
    name: Token
    taip: 'Type | None'

@dataclass
class Variant:
    name: Token
    cases: Lazy[List[VariantCase]]
    generic_arguments: List['Type']

    def size(self) -> int:
        return 4 + max((t.taip.size() for t in self.cases.get() if t.taip is not None), default=0)

TypeDefinition = Struct | Variant

@dataclass
class CustomTypeHandle(Formattable):
    module: int
    index: int
    instance: int

@dataclass
class CustomTypeType(Formattable):
    name: Token
    struct: CustomTypeHandle
    _size: Lazy[int]
    def format(self, fmt: Formatter):
        fmt.named_record("StructType", [
            ("name", self.name),
            ("struct", self.struct)])

    def can_live_in_reg(self) -> bool:
        return self.size() <= 8

    def size(self):
        return self._size.get()

    @staticmethod
    def dummy(name: str, size: int) -> 'CustomTypeType':
        return CustomTypeType(Token.dummy(name), CustomTypeHandle(0, 0, 0), Lazy(lambda: size))

@dataclass
class TupleType(Formattable):
    token: Token
    items: List['Type']

    def can_live_in_reg(self) -> bool:
        return self.size() <= 8

    def size(self):
        return sum(t.size() for t in self.items)

Type = PrimitiveType | PtrType | CustomTypeType | FunctionType | TupleType

def type_eq(a: Type, b: Type) -> bool:
    if isinstance(a, Bool) and isinstance(b, Bool):
        return True
    if isinstance(a, I8) and isinstance(b, I8):
        return True
    if isinstance(a, I32) and isinstance(b, I32):
        return True
    if isinstance(a, I64) and isinstance(b, I64):
        return True
    if isinstance(a, PtrType) and isinstance(b, PtrType):
        return type_eq(a.child, b.child)
    if isinstance(a, CustomTypeType) and isinstance(b, CustomTypeType):
        return a.struct.module == b.struct.module and a.struct.index == b.struct.index and a.struct.instance == b.struct.instance
    if isinstance(a, FunctionType) and isinstance(b, FunctionType):
        return types_eq(a.parameters, b.parameters) and types_eq(a.returns, b.returns)
    if isinstance(a, TupleType) and isinstance(b, TupleType):
        return types_eq(a.items, b.items)
    return False

def types_eq(a: List[Type], b: List[Type]) -> bool:
    if len(a) != len(b):
        return False
    for i in range(0, len(a)):
        if not type_eq(a[i], b[i]):
            return False
    return True

def format_type(a: Type) -> str:
    match a:
        case PtrType(child):
            return f".{format_type(child)}"
        case CustomTypeType(name):
            return name.lexeme 
        case FunctionType(_, parameters, returns):
            s = "("
            for param in parameters:
                s += format_type(param) + ", "
            s = s[:-2] + " -> "
            if len(a.returns) == 0:
                return s[:-1] + ")"
            for ret in returns:
                s += format_type(ret) + ", "
            return s[:-2] + ")"
        case TupleType(_, items):
            return "[" + intercalate(", ", map(format_type, items)) + "]"
        case Bool():
            return "bool"
        case I8():
            return "i8"
        case I32():
            return "i32"
        case I64():
            return "i64"

@dataclass
class ParameterLocal:
    name: LocalName
    taip: Type
    _lives_in_memory: bool

    def size(self) -> int:
        return self.taip.size()

    def lives_in_memory(self) -> bool:
        return self._lives_in_memory

    def needs_moved_into_memory(self) -> bool:
        return self.lives_in_memory() and self.taip.can_live_in_reg()

    def can_be_abused_as_ref(self) -> bool:
        return not self.taip.can_live_in_reg() or self.taip.size() <= 4

@dataclass
class InitLocal:
    name: LocalName
    taip: Type
    _lives_in_memory: bool

    def size(self) -> int:
        return self.taip.size()

    def lives_in_memory(self) -> bool:
        return self._lives_in_memory

type Local = ParameterLocal | InitLocal

@dataclass
class FunctionSignature:
    generic_arguments: List[Type]
    parameters: List[NamedType]
    returns: List[Type]

    def returns_any_struct(self) -> bool:
        return any(isinstance(ret, CustomTypeType) for ret in self.returns)

@dataclass
class Global:
    name: Token
    taip: Type
    was_reffed: bool

@dataclass
class Extern:
    name: Token
    extern_module: str
    extern_name: str
    signature: FunctionSignature

@dataclass
class Scope:
    id: ScopeId
    words: List['Word']

@dataclass
class ConcreteFunction:
    name: Token
    export_name: Token | None
    signature: FunctionSignature
    body: Scope
    locals_copy_space: int
    max_struct_ret_count: int
    locals: Dict[LocalId, Local]

@dataclass
class GenericFunction:
    instances: Dict[int, ConcreteFunction]

Function = ConcreteFunction | GenericFunction

@dataclass(frozen=True, eq=True)
class FunctionHandle:
    module: int
    index: int
    instance: int | None

@dataclass(frozen=True, eq=True)
class ExternHandle:
    module: int
    index: int

@dataclass
class CallWord:
    name: Token
    function: 'FunctionHandle | ExternHandle'
    return_space_offset: int

@dataclass
class CastWord:
    token: Token
    source: Type
    taip: Type

@dataclass
class LoadWord:
    token: Token
    taip: Type
    copy_space_offset: int | None

@dataclass
class IfWord:
    token: Token
    parameters: List[Type]
    returns: List[Type] | None
    true_branch: Scope
    false_branch: Scope
    diverges: bool

@dataclass
class IndirectCallWord:
    token: Token
    taip: FunctionType
    return_space_offset: int

@dataclass
class FunRefWord:
    call: CallWord
    table_index: int

@dataclass
class LoopWord:
    token: Token
    body: Scope
    parameters: List[Type]
    returns: List[Type]
    diverges: bool

@dataclass
class BlockWord:
    token: Token
    body: Scope
    parameters: List[Type]
    returns: List[Type]

@dataclass
class SizeofWord:
    token: Token
    taip: Type

@dataclass
class FieldAccess:
    name: Token
    source_taip: CustomTypeType | PtrType
    target_taip: Type
    offset: int

@dataclass
class Offset:
    offset: int

    def __str__(self) -> str:
        return f"i32.const {self.offset} i32.add"

@dataclass
class OffsetLoad:
    offset: int
    taip: Type

    def __str__(self) -> str:
        size = self.taip.size()
        if size == 1:
            return f"i32.load8_u offset={self.offset}" if self.offset != 0 else "i32.load8_u"
        if size <= 4:
            return f"i32.load offset={self.offset}" if self.offset != 0 else "i32.load"
        if size <= 8:
            return f"i64.load offset={self.offset}" if self.offset != 0 else "i64.load"
        if self.offset == 0:
            return f"i32.const {size} memory.copy"
        else:
            return f"i32.const {self.offset} i32.add i32.const {size} memory.copy"

@dataclass
class I32InI64:
    offset: int

    def __str__(self) -> str:
        if self.offset == 0:
            return "i32.wrap_i64"
        return f"i64.const {self.offset * 8} i64.shr_u i32.wrap_i64"

@dataclass
class I16InI32:
    offset: int

    def __str__(self) -> str:
        if self.offset == 0:
            return "i32.const 0xFFFF i32.and"
        return f"i32.const {self.offset * 8} i32.shr_u i32.const 0xFFFF i32.and"

@dataclass
class I8InI32:
    offset: int

    def __str__(self) -> str:
        if self.offset == 0:
            return "i32.const 0xFF i32.and"
        return f"i32.const {self.offset * 8} i32.shr_u i32.const 0xFF i32.and"

@dataclass
class I8InI64:
    offset: int

    def __str__(self) -> str:
        if self.offset == 0:
            return "i32.wrap_i64 i32.const 0xFF i32.and"
        return f"i64.const {self.offset * 8} i64.shr_u i32.wrap_i64 i32.const 0xFF i32.and"

type Load = Offset | OffsetLoad | I32InI64 | I8InI32 | I16InI32 | I8InI64

def is_bitshift(load) -> TypeGuard[I8InI64 | I32InI64 | I8InI32 | I16InI32]:
    return isinstance(load, I8InI64) or isinstance(load, I32InI64) or isinstance(load, I8InI32) or isinstance(load, I16InI32)

@dataclass
class GetFieldWord:
    token: Token
    target_taip: Type
    loads: List[Load]
    on_ptr: bool
    copy_space_offset: int | None

@dataclass
class SetWord:
    token: Token
    local_id: LocalId | GlobalId
    target_taip: Type
    loads: List[Load]
    var_lives_in_memory: bool

@dataclass
class InitWord:
    token: Token
    local_id: LocalId
    taip: Type
    var_lives_in_memory: bool

@dataclass
class GetWord:
    ident: Token
    local_id: LocalId | GlobalId
    target_taip: Type
    loads: List[Load]
    copy_space_offset: int | None
    var_lives_in_memory: bool

@dataclass
class RefWord:
    ident: Token
    local_id: LocalId | GlobalId
    loads: List[Load]

@dataclass
class IntrinsicAdd:
    token: Token
    taip: PtrType | I8 | I32 | I64

@dataclass
class IntrinsicSub:
    token: Token
    taip: PtrType | I8 | I32 | I64

@dataclass
class IntrinsicMul:
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicDiv:
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicMod:
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicEqual:
    token: Token
    taip: Type

@dataclass
class IntrinsicNotEqual:
    token: Token
    taip: Type

@dataclass
class IntrinsicFlip:
    token: Token
    lower: Type
    upper: Type

@dataclass
class IntrinsicAnd:
    token: Token
    taip: PrimitiveType

@dataclass
class IntrinsicNot:
    token: Token
    taip: PrimitiveType

@dataclass
class IntrinsicGreaterEq:
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicLessEq:
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicGreater:
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicLess:
    token: Token
    taip: I8 | I32 | I64

@dataclass
class IntrinsicShl:
    token: Token
    taip: Type

@dataclass
class IntrinsicShr:
    token: Token
    taip: Type

@dataclass
class IntrinsicRotl:
    token: Token
    taip: Type

@dataclass
class IntrinsicRotr:
    token: Token
    taip: Type

@dataclass
class IntrinsicOr:
    token: Token
    taip: Type

@dataclass
class IntrinsicStore:
    token: Token
    taip: Type

@dataclass
class IntrinsicUninit:
    token: Token
    taip: Type
    copy_space_offset: int

@dataclass
class StoreWord:
    token: Token
    local: LocalId | GlobalId
    taip: Type
    loads: List[Load]

@dataclass
class StructWord:
    token: Token
    taip: CustomTypeType
    copy_space_offset: int
    body: Scope

@dataclass
class UnnamedStructWord:
    token: Token
    taip: CustomTypeType
    copy_space_offset: int

@dataclass
class StructFieldInitWord:
    token: Token
    taip: Type
    copy_space_offset: int

@dataclass
class VariantWord:
    token: Token
    tag: int
    variant: CustomTypeHandle
    copy_space_offset: int

@dataclass
class MatchCase:
    tag: int
    body: Scope

@dataclass
class MatchWord:
    token: Token
    variant: CustomTypeHandle
    by_ref: bool
    cases: List[MatchCase]
    default: Scope | None
    parameters: List[Type]
    returns: List[Type] | None

@dataclass
class TupleMakeWord:
    token: Token
    taip: TupleType
    copy_space_offset: int

@dataclass
class TupleUnpackWord:
    token: Token
    item: List[Type]
    copy_space_offset: int

type IntrinsicWord = (
      IntrinsicAdd
    | IntrinsicSub
    | IntrinsicEqual
    | IntrinsicNotEqual
    | IntrinsicAnd
    | IntrinsicDrop
    | IntrinsicGreaterEq
    | IntrinsicLessEq
    | IntrinsicMul
    | IntrinsicMod
    | IntrinsicDiv
    | IntrinsicGreater
    | IntrinsicLess
    | IntrinsicFlip
    | IntrinsicShl
    | IntrinsicShr
    | IntrinsicRotl
    | IntrinsicRotr
    | IntrinsicOr
    | IntrinsicStore
    | IntrinsicMemCopy
    | IntrinsicMemFill
    | IntrinsicMemGrow
    | IntrinsicNot
    | IntrinsicUninit
    | IntrinsicSetStackSize
)

type Word = (
      NumberWord 
    | checked.words.StringWord
    | CallWord
    | GetWord
    | InitWord
    | CastWord
    | SetWord
    | LoadWord
    | IntrinsicWord
    | IfWord
    | RefWord
    | IndirectCallWord
    | StoreWord
    | FunRefWord
    | LoopWord
    | BreakWord
    | SizeofWord
    | BlockWord
    | GetFieldWord
    | StructWord
    | StructFieldInitWord
    | UnnamedStructWord
    | VariantWord
    | MatchWord
    | MatchVoidWord
    | InitWord
    | TupleMakeWord
    | TupleUnpackWord
)

@dataclass
class Module:
    id: int
    type_definitions: Dict[int, List[TypeDefinition]]
    externs: Dict[int, Extern]
    globals: List[Global]
    functions: Dict[int, Function]
    data: bytes

@dataclass
class Monomizer:
    modules: IndexedDict[str, checked.Module]
    type_definitions: Dict[checked.CustomTypeHandle, List[Tuple[List[Type], TypeDefinition]]] = field(default_factory=dict)
    externs: Dict[checked.FunctionHandle, Extern] = field(default_factory=dict)
    globals: Dict[GlobalId, Global] = field(default_factory=dict)
    functions: Dict[checked.FunctionHandle, Function] = field(default_factory=dict)
    signatures: Dict[checked.FunctionHandle, FunctionSignature | List[FunctionSignature]] = field(default_factory=dict)
    function_table: Dict[FunctionHandle | ExternHandle, int] = field(default_factory=dict)
    struct_literal_ctx: Struct | None = None

    def with_struct_literal_ctx(self, struct: Struct | None) -> 'Monomizer':
        self = copy.copy(self)
        self.struct_literal_ctx = struct
        return self

    def lookup_type_definition(self, struct: CustomTypeHandle) -> TypeDefinition:
        return self.type_definitions[checked.CustomTypeHandle(struct.module, struct.index)][struct.instance][1]

    def monomize(self) -> Tuple[Dict[FunctionHandle | ExternHandle, int], Dict[int, Module]]:
        self.externs = {
            checked.FunctionHandle(m, i): self.monomize_extern(f)
            for m,module in self.modules.indexed_values()
            for i,f in enumerate(module.functions.values())
            if isinstance(f, resolver.Extern)
        }
        self.globals = {
            GlobalId(globl.name, m, i): self.monomize_global(globl)
            for m,module in self.modules.indexed_values()
            for i,globl in enumerate(module.globals.values())
        }
        for id in range(len(self.modules)):
            module = self.modules.index(id)
            for index, function in enumerate(module.functions.values()):
                if isinstance(function, resolver.Extern):
                    continue
                if function.export_name is not None:
                    assert(len(function.signature.generic_parameters) == 0)
                    handle = checked.FunctionHandle(id, index)
                    self.monomize_function(handle, [])

        mono_modules = {}
        for module_id,module in enumerate(self.modules.values()):
            externs: Dict[int, Extern] = { handle.index: extern for (handle,extern) in self.externs.items() if handle.module == module_id }
            globals: List[Global] = [globl for id, globl in self.globals.items() if id.module == module_id]
            type_definitions: Dict[int, List[TypeDefinition]] = { handle.index: [taip for _,taip in monomorphizations] for handle,monomorphizations in self.type_definitions.items() if handle.module == module_id }
            functions = { handle.index: function for handle,function in self.functions.items() if handle.module == module_id }
            mono_modules[module_id] = Module(module_id, type_definitions, externs, globals, functions, self.modules.index(module_id).data)
        return self.function_table, mono_modules

    def monomize_locals(self, locals: Dict[LocalId, checked.Local], generics: List[Type]) -> Dict[LocalId, Local]:
        res: Dict[LocalId, Local] = {}
        for id, local in locals.items():
            taip = self.monomize_type(local.taip, generics)
            lives_in_memory = local.was_reffed or not taip.can_live_in_reg()
            if local.is_parameter:
                res[id] = ParameterLocal(local.name, taip, lives_in_memory)
            else:
                res[id] = InitLocal(local.name, taip, lives_in_memory)
            continue
        return res

    def monomize_concrete_signature(self, signature: resolver.FunctionSignature) -> FunctionSignature:
        assert(len(signature.generic_parameters) == 0)
        return self.monomize_signature(signature, [])

    def monomize_function(self, function: checked.FunctionHandle, generics: List[Type]) -> ConcreteFunction:
        f = self.modules.index(function.module).functions.index(function.index)
        assert(isinstance(f, checked.Function))
        if len(generics) == 0:
            assert(len(f.signature.generic_parameters) == 0)
        signature = self.monomize_signature(f.signature, generics)
        if len(f.signature.generic_parameters) == 0:
            self.signatures[function] = signature
            generic_index = None
        else:
            if function not in self.signatures:
                self.signatures[function] = []
            instances = self.signatures[function]
            assert(isinstance(instances, list))
            generic_index = len(instances)
            instances.append(signature)
        copy_space_offset = Ref(0)
        max_struct_ret_count = Ref(0)
        monomized_locals = self.monomize_locals(f.locals, generics)
        body = Scope(
            f.body.id,
            self.monomize_words(
                f.body.words,
                generics,
                copy_space_offset,
                max_struct_ret_count,
                monomized_locals,
                None))
        concrete_function = ConcreteFunction(
            f.name,
            f.export_name,
            signature,
            body,
            copy_space_offset.value,
            max_struct_ret_count.value,
            monomized_locals)
        if len(f.signature.generic_parameters) == 0:
            assert(len(generics) == 0)
            assert(function not in self.functions)
            self.functions[function] = concrete_function
            return concrete_function
        assert(generic_index is not None)
        if function not in self.functions:
            self.functions[function] = GenericFunction({})
        generic_function = self.functions[function]
        assert(isinstance(generic_function, GenericFunction))
        assert(generic_index not in generic_function.instances)
        generic_function.instances[generic_index] = concrete_function
        return concrete_function

    def monomize_signature(self, signature: checked.FunctionSignature, generics: List[Type]) -> FunctionSignature:
        parameters = list(map(lambda t: self.monomize_named_type(without_holes.named_type_with_holes(t), generics), signature.parameters))
        returns = list(map(lambda t: self.monomize_type(without_holes.with_holes(t), generics), signature.returns))
        return FunctionSignature(generics, parameters, returns)

    def monomize_global(self, globl: checked.Global) -> Global:
        return Global(globl.name, self.monomize_type(without_holes.with_holes(globl.taip), []), globl.was_reffed)

    def monomize_scope(self, scope: checked.Scope, generics: List[Type], copy_space_offset: Ref[int], max_struct_ret_count: Ref[int], locals: Dict[LocalId, Local], struct_space: int | None) -> Scope:
        return Scope(scope.id, self.monomize_words(scope.words, generics, copy_space_offset, max_struct_ret_count, locals, struct_space))

    def monomize_words(self, words: List[checked.Word], generics: List[Type], copy_space_offset: Ref[int], max_struct_ret_count: Ref[int], locals: Dict[LocalId, Local], struct_space: int | None) -> List[Word]:
        return list(map(lambda w: self.monomize_word(w, generics, copy_space_offset, max_struct_ret_count, locals, struct_space), words))

    def monomize_word(self, word: checked.Word, generics: List[Type], copy_space_offset: Ref[int], max_struct_ret_count: Ref[int], locals: Dict[LocalId, Local], struct_space: int | None) -> Word:
        match word:
            case checked.words.NumberWord():
                return word
            case checked.words.StringWord():
                return word
            case checked.words.CallWord():
                return self.monomize_call_word(word, copy_space_offset, max_struct_ret_count, generics)
            case checked.words.IndirectCallWord(token, taip):
                monomized_function_taip = self.monomize_function_type(taip, generics)
                local_copy_space_offset = copy_space_offset.value
                copy_space = sum(taip.size() for taip in monomized_function_taip.returns if not taip.can_live_in_reg())
                copy_space_offset.value += copy_space
                if copy_space != 0:
                    max_struct_ret_count.value = max(max_struct_ret_count.value, len(monomized_function_taip.returns))
                return IndirectCallWord(token, monomized_function_taip, local_copy_space_offset)
            case checked.words.GetLocal(token, local_id, var_taip, resolved_fields, taip):
                fields = self.monomize_field_accesses(resolved_fields, generics)
                monomized_taip = self.monomize_type(taip, generics)
                if not monomized_taip.can_live_in_reg():
                    offset = copy_space_offset.value
                    copy_space_offset.value += monomized_taip.size()
                else:
                    offset = None
                lives_in_memory = self.does_var_live_in_memory(local_id, locals)
                monomized_var_taip = self.monomize_type(var_taip, generics)
                loads = determine_loads(fields, just_ref=False, base_in_mem=lives_in_memory)
                target_taip = fields[-1].target_taip if len(fields) != 0 else monomized_var_taip
                return GetWord(token, local_id, target_taip, loads, offset, lives_in_memory)
            case checked.words.InitWord(token, local_id, taip):
                return InitWord(token, local_id, self.monomize_type(taip, generics), self.does_var_live_in_memory(local_id, locals))
            case checked.words.SetWord(token, local_id, resolved_fields):
                fields = self.monomize_field_accesses(resolved_fields, generics)
                lives_in_memory = self.does_var_live_in_memory(local_id, locals)
                target_lives_in_memory = lives_in_memory or any(isinstance(field.source_taip, checked.words.PtrType) for field in resolved_fields)
                monomized_var_taip = self.lookup_var_taip(local_id, locals)
                loads = determine_loads(fields, just_ref=target_lives_in_memory, base_in_mem=lives_in_memory)
                monomized_taip = fields[-1].target_taip if len(fields) != 0 else monomized_var_taip
                return SetWord(token, local_id, monomized_taip, loads, target_lives_in_memory)
            case checked.words.RefWord(token, local_id, resolved_fields):
                fields = self.monomize_field_accesses(resolved_fields, generics)
                loads = determine_loads(fields, just_ref=True)
                return RefWord(token, local_id, loads)
            case checked.words.StoreWord(token, local_id, resolved_fields):
                fields = self.monomize_field_accesses(resolved_fields, generics)
                loads = determine_loads(fields)
                monomized_taip = fields[-1].target_taip if len(fields) != 0 else self.lookup_var_taip(local_id, locals)
                if len(fields) == 0 and isinstance(local_id, LocalId):
                    assert(isinstance(monomized_taip, PtrType))
                    monomized_taip = monomized_taip.child
                return StoreWord(token, local_id, monomized_taip, loads)
            case checked.words.intrinsics.IntrinsicAdd(token, taip):
                return IntrinsicAdd(token, self.monomize_addable_type(taip, generics))
            case checked.words.intrinsics.IntrinsicSub(token, taip):
                return IntrinsicSub(token, self.monomize_addable_type(taip, generics))
            case checked.words.intrinsics.IntrinsicMul(token, taip):
                return IntrinsicMul(token, taip)
            case checked.words.intrinsics.IntrinsicMod(token, taip):
                return IntrinsicMod(token, taip)
            case checked.words.intrinsics.IntrinsicDiv(token, taip):
                return IntrinsicDiv(token, taip)
            case checked.words.intrinsics.IntrinsicEqual(token, taip):
                return IntrinsicEqual(token, self.monomize_type(taip, generics))
            case checked.words.intrinsics.IntrinsicNotEqual(token, taip):
                return IntrinsicNotEqual(token, self.monomize_type(taip, generics))
            case checked.words.intrinsics.IntrinsicGreaterEq(token, taip):
                return IntrinsicGreaterEq(token, taip)
            case checked.words.intrinsics.IntrinsicGreater(token, taip):
                return IntrinsicGreater(token, taip)
            case checked.words.intrinsics.IntrinsicLess(token, taip):
                return IntrinsicLess(token, taip)
            case checked.words.intrinsics.IntrinsicLessEq(token, taip):
                return IntrinsicLessEq(token, taip)
            case checked.words.intrinsics.IntrinsicAnd(token, taip):
                return IntrinsicAnd(token, taip)
            case checked.words.intrinsics.IntrinsicNot(token, taip):
                return IntrinsicNot(token, taip)
            case IntrinsicDrop():
                return word
            case BreakWord():
                return word
            case checked.words.intrinsics.IntrinsicFlip(token, lower, upper):
                return IntrinsicFlip(token, self.monomize_type(lower, generics), self.monomize_type(upper, generics))
            case checked.words.intrinsics.IntrinsicShl(token, taip):
                return IntrinsicShl(token, self.monomize_type(taip, generics))
            case checked.words.intrinsics.IntrinsicShr(token, taip):
                return IntrinsicShr(token, self.monomize_type(taip, generics))
            case checked.words.intrinsics.IntrinsicRotl(token, taip):
                return IntrinsicRotl(token, self.monomize_type(taip, generics))
            case checked.words.intrinsics.IntrinsicRotr(token, taip):
                return IntrinsicRotr(token, self.monomize_type(taip, generics))
            case checked.words.intrinsics.IntrinsicOr(token, taip):
                return IntrinsicOr(token, self.monomize_type(taip, generics))
            case checked.words.intrinsics.IntrinsicStore(token, taip):
                return IntrinsicStore(token, self.monomize_type(taip, generics))
            case IntrinsicMemCopy():
                return word
            case IntrinsicMemFill():
                return word
            case IntrinsicMemGrow():
                return word
            case IntrinsicSetStackSize():
                return word
            case checked.words.intrinsics.IntrinsicUninit(token, taip):
                monomized_taip = self.monomize_type(taip, generics)
                offset = copy_space_offset.value
                if not monomized_taip.can_live_in_reg():
                    copy_space_offset.value += monomized_taip.size()
                return IntrinsicUninit(token, monomized_taip, offset)
            case checked.words.LoadWord(token, taip):
                monomized_taip = self.monomize_type(taip, generics)
                if not monomized_taip.can_live_in_reg():
                    offset = copy_space_offset.value
                    copy_space_offset.value += monomized_taip.size()
                else:
                    offset = None
                return LoadWord(token, monomized_taip, offset)
            case checked.words.CastWord(token, source, taip):
                return CastWord(token, self.monomize_type(source, generics), self.monomize_type(taip, generics))
            case checked.words.IfWord(token, resolved_parameters, resolved_returns, resolved_if_words, resolved_else_words, diverges):
                true_branch = self.monomize_scope(resolved_if_words, generics, copy_space_offset, max_struct_ret_count, locals, struct_space)
                false_branch = self.monomize_scope(resolved_else_words, generics, copy_space_offset, max_struct_ret_count, locals, struct_space)
                parameters = list(map(lambda t: self.monomize_type(t, generics), resolved_parameters))
                returns = None if resolved_returns is None else list(map(lambda t: self.monomize_type(t, generics), resolved_returns))
                return IfWord(token, parameters, returns, true_branch, false_branch, diverges)
            case checked.words.FunRefWord(call):
                # monomize_call_word increments the copy_space, but if we're just taking the pointer
                # of the function, then we're not actually calling it and no space should be allocated.
                cso = copy_space_offset.value
                msrc = max_struct_ret_count.value
                call_word = self.monomize_call_word(call, copy_space_offset, max_struct_ret_count, generics)
                # So restore the previous values of copy_space_offset and max_struct_ret_count afterwards.
                # TODO: extract those parts of monomize_call_word which are common to both actual calls and just FunRefs.
                copy_space_offset.value = cso
                max_struct_ret_count.value = msrc
                table_index = self.insert_function_into_table(call_word.function)
                return FunRefWord(call_word, table_index)
            case checked.words.LoopWord(token, resolved_body, resolved_parameters, resolved_returns, diverges):
                body = self.monomize_scope(resolved_body, generics, copy_space_offset, max_struct_ret_count, locals, struct_space)
                parameters = list(map(lambda t: self.monomize_type(t, generics), resolved_parameters))
                returns = list(map(lambda t: self.monomize_type(t, generics), resolved_returns))
                return LoopWord(token, body, parameters, returns, diverges)
            case checked.words.SizeofWord(token, taip):
                return SizeofWord(token, self.monomize_type(taip, generics))
            case checked.words.BlockWord(token, resolved_body, resolved_parameters, resolved_returns):
                body = self.monomize_scope(resolved_body, generics, copy_space_offset, max_struct_ret_count, locals, struct_space)
                parameters = list(map(lambda t: self.monomize_type(t, generics), resolved_parameters))
                returns = list(map(lambda t: self.monomize_type(t, generics), resolved_returns))
                return BlockWord(token, body, parameters, returns)
            case checked.words.GetFieldWord(token, resolved_fields, on_ptr):
                fields = self.monomize_field_accesses(resolved_fields, generics)
                target_taip = fields[-1].target_taip
                offset = None
                if not on_ptr and not target_taip.can_live_in_reg():
                    offset = copy_space_offset.value
                    copy_space_offset.value += target_taip.size()
                loads = determine_loads(fields, just_ref=on_ptr)
                return GetFieldWord(token, target_taip, loads, on_ptr, offset)
            case checked.words.StructWord(token, taip, resolved_body):
                monomized_taip = self.monomize_struct_type(taip, generics)
                offset = copy_space_offset.value
                copy_space_offset.value += monomized_taip.size()
                struct = self.lookup_type_definition(monomized_taip.struct)
                assert(not isinstance(struct, Variant))
                body = self.with_struct_literal_ctx(struct).monomize_scope(resolved_body, generics, copy_space_offset, max_struct_ret_count, locals, offset)
                return StructWord(token, monomized_taip, offset, body)
            case checked.words.UnnamedStructWord(token, taip):
                monomized_taip = self.monomize_struct_type(taip, generics)
                offset = copy_space_offset.value
                if not monomized_taip.can_live_in_reg():
                    copy_space_offset.value += monomized_taip.size()
                return UnnamedStructWord(token, monomized_taip, offset)
            case checked.words.StructFieldInitWord(token, field_index):
                assert(self.struct_literal_ctx is not None)
                field_taip = self.struct_literal_ctx.fields.get()[field_index].taip
                assert(struct_space is not None)
                field_copy_space_offset: int = struct_space
                for i,_ in enumerate(self.struct_literal_ctx.fields.get()):
                    if i == field_index:
                        # TODO: why is this `+=` instead of `=`?
                        #       This seems very wrong, but it still seems to work, why is that?
                        #       Why even loop at all in here?
                        field_copy_space_offset += self.struct_literal_ctx.field_offset(i)
                        break
                return StructFieldInitWord(token, field_taip, field_copy_space_offset)
            case checked.words.VariantWord(token, case, resolved_variant_type):
                this_generics = list(map(lambda t: self.monomize_type(t, generics), resolved_variant_type.generic_arguments))
                (variant_handle, variant) = self.monomize_struct(resolved_variant_type.type_definition, this_generics)
                offset = copy_space_offset.value
                if variant.size() > 8:
                    copy_space_offset.value += variant.size()
                return VariantWord(token, case, variant_handle, offset)
            case checked.words.MatchVoidWord():
                return word
            case checked.words.MatchWord(token, resolved_variant_type, by_ref, cases, default_case, resolved_parameters, resolved_returns):
                monomized_cases: List[MatchCase] = []
                for resolved_case in cases:
                    body = self.monomize_scope(resolved_case.body, generics, copy_space_offset, max_struct_ret_count, locals, struct_space)
                    monomized_cases.append(MatchCase(resolved_case.tag, body))
                monomized_default_case = None if default_case is None else self.monomize_scope(default_case, generics, copy_space_offset, max_struct_ret_count, locals, struct_space)
                this_generics = list(map(lambda t: self.monomize_type(t, generics), resolved_variant_type.generic_arguments))
                monomized_variant = self.monomize_struct(resolved_variant_type.type_definition, this_generics)[0]
                parameters = list(map(lambda t: self.monomize_type(t, generics), resolved_parameters))
                returns = None if resolved_returns is None else list(map(lambda t: self.monomize_type(t, generics), resolved_returns))
                return MatchWord(token, monomized_variant, by_ref, monomized_cases, monomized_default_case, parameters, returns)

    def lookup_var_taip(self, local_id: LocalId | GlobalId, locals: Dict[LocalId, Local]) -> Type:
        if isinstance(local_id, LocalId):
            return locals[local_id].taip
        return self.globals[local_id].taip

    def does_var_live_in_memory(self, local_id: LocalId | GlobalId, locals: Dict[LocalId, Local]) -> bool:
        if isinstance(local_id, LocalId):
            return locals[local_id].lives_in_memory()
        globl = self.globals[local_id]
        return globl.was_reffed or not globl.taip.can_live_in_reg()

    def insert_function_into_table(self, function: FunctionHandle | ExternHandle) -> int:
        if function not in self.function_table:
            self.function_table[function] = len(self.function_table)
        return self.function_table[function]

    def monomize_field_accesses(self, fields: Sequence[checked.words.FieldAccess], generics: List[Type]) -> List[FieldAccess]:
        if len(fields) == 0:
            return []

        field = fields[0]

        if isinstance(field.source_taip, checked.CustomTypeType):
            source_taip: PtrType | CustomTypeType = self.monomize_struct_type(field.source_taip, generics)
            resolved_struct = field.source_taip.type_definition
            generic_arguments = field.source_taip.generic_arguments
        else:
            assert(isinstance(field.source_taip.child, checked.CustomTypeType))
            source_taip = PtrType(self.monomize_type(field.source_taip.child, generics))
            resolved_struct = field.source_taip.child.type_definition
            generic_arguments = field.source_taip.child.generic_arguments
        [_, struct] = self.monomize_struct(resolved_struct, list(map(lambda t: self.monomize_type(t, generics), generic_arguments)))
        assert(not isinstance(struct, Variant))
        target_taip = self.monomize_type(field.target_taip, struct.generic_parameters)
        offset = struct.field_offset(field.field_index)
        return [FieldAccess(field.name, source_taip, target_taip, offset)] + self.monomize_field_accesses(fields[1:], struct.generic_parameters)

    def monomize_call_word(self, word: checked.words.CallWord, copy_space_offset: Ref[int], max_struct_ret_count: Ref[int], generics: List[Type]) -> CallWord:
        if word.function in self.externs:
            signature = self.externs[word.function].signature
            offset = copy_space_offset.value
            copy_space = sum(taip.size() for taip in signature.returns if isinstance(taip, CustomTypeType))
            max_struct_ret_count.value = max(max_struct_ret_count.value, len(signature.returns) if copy_space > 0 else 0)
            copy_space_offset.value += copy_space
            return CallWord(word.name, ExternHandle(word.function.module, word.function.index), offset)
        generics_here = list(map(lambda t: self.monomize_type(t, generics), word.generic_arguments))
        if word.function in self.signatures:
            signatures = self.signatures[word.function]
            if isinstance(signatures, FunctionSignature):
                signature = signatures
                assert(len(word.generic_arguments) == 0)
                offset = copy_space_offset.value
                copy_space = sum(taip.size() for taip in signature.returns if not taip.can_live_in_reg())
                max_struct_ret_count.value = max(max_struct_ret_count.value, len(signature.returns) if copy_space > 0 else 0)
                copy_space_offset.value += copy_space
                return CallWord(word.name, FunctionHandle(word.function.module, word.function.index, None), offset)
            for instance_index, signature in enumerate(signatures):
                if types_eq(signature.generic_arguments, generics_here):
                    offset = copy_space_offset.value
                    copy_space = sum(taip.size() for taip in signature.returns if not taip.can_live_in_reg())
                    max_struct_ret_count.value = max(max_struct_ret_count.value, len(signature.returns) if copy_space > 0 else 0)
                    copy_space_offset.value += copy_space
                    return CallWord(word.name, FunctionHandle(word.function.module, word.function.index, instance_index), offset)
        self.monomize_function(word.function, generics_here)
        return self.monomize_call_word(word, copy_space_offset, max_struct_ret_count, generics) # the function instance should now exist, try monomorphizing this CallWord again

    def lookup_struct(self, struct: checked.CustomTypeHandle, generics: List[Type]) -> Tuple[CustomTypeHandle, TypeDefinition] | None:
        if struct not in self.type_definitions:
            return None
        for instance_index, (genics, instance) in enumerate(self.type_definitions[struct]):
            if types_eq(genics, generics):
                return CustomTypeHandle(struct.module, struct.index, instance_index), instance
        return None

    def add_struct(self, handle: checked.CustomTypeHandle, taip: TypeDefinition, generics: List[Type]) -> CustomTypeHandle:
        if handle not in self.type_definitions:
            self.type_definitions[handle] = []
        instance_index = len(self.type_definitions[handle])
        self.type_definitions[handle].append((generics, taip))
        return CustomTypeHandle(handle.module, handle.index, instance_index)

    def monomize_struct(self, struct: checked.CustomTypeHandle, generics: List[Type]) -> Tuple[CustomTypeHandle, TypeDefinition]:
        handle_and_instance = self.lookup_struct(struct, generics)
        if handle_and_instance is not None:
            return handle_and_instance
        s = self.modules.index(struct.module).type_definitions.index(struct.index)
        if isinstance(s, checked.Variant):
            def cases() -> List[VariantCase]:
                return [VariantCase(c.name, self.monomize_type(c.taip, generics) if c.taip is not None else None) for c in s.cases]

            variant_instance = Variant(s.name, Lazy(cases), generics)
            handle = self.add_struct(struct, variant_instance, generics)
            return handle, variant_instance

        def fields() -> List[NamedType]:
            return list(map(lambda t: self.monomize_named_type(t, generics), s.fields))

        struct_instance = Struct(s.name, Lazy(fields), generics)
        handle = self.add_struct(struct, struct_instance, generics)
        return handle, struct_instance

    def monomize_named_type(self, taip: checked.NamedType, generics: List[Type]) -> NamedType:
        return NamedType(taip.name, self.monomize_type(taip.taip, generics))

    def monomize_type(self, taip: checked.Type, generics: List[Type]) -> Type:
        match taip:
            case checked.PtrType():
                return PtrType(self.monomize_type(taip.child, generics))
            case checked.GenericType(_, generic_index):
                return generics[generic_index]
            case checked.CustomTypeType():
                return self.monomize_struct_type(taip, generics)
            case checked.FunctionType():
                return self.monomize_function_type(taip, generics)
            case checked.HoleType():
                assert(False)
            case other:
                return other

    def monomize_addable_type(self, taip: checked.PtrType | I8 | I32 | I64, generics: List[Type]) -> PtrType | I8 | I32 | I64:
        match taip:
            case I8() | I32() | I64():
                return taip
            case checked.PtrType():
                return PtrType(self.monomize_type(taip.child, generics))

    def monomize_struct_type(self, taip: checked.CustomTypeType, generics: List[Type]) -> CustomTypeType:
        this_generics = list(map(lambda t: self.monomize_type(t, generics), taip.generic_arguments))
        handle,struct = self.monomize_struct(taip.type_definition, this_generics)
        return CustomTypeType(taip.name, handle, Lazy(lambda: struct.size()))

    def monomize_function_type(self, taip: checked.FunctionType, generics: List[Type]) -> FunctionType:
        parameters = list(map(lambda t: self.monomize_type(t, generics), taip.parameters))
        returns = list(map(lambda t: self.monomize_type(t, generics), taip.returns))
        return FunctionType(taip.token, parameters, returns)

    def monomize_extern(self, extern: checked.Extern) -> Extern:
        signature = self.monomize_concrete_signature(extern.signature)
        return Extern(extern.name, extern.extern_module, extern.extern_name, signature)

def merge_locals_module(module: Module):
    for function in module.functions.values():
        if isinstance(function, ConcreteFunction):
            merge_locals_function(function)
            return
        for instance in function.instances.values():
            merge_locals_function(instance)

@dataclass
class Disjoint:
    scopes: Set[ScopeId]
    reused: Set[LocalId]
    substitutions: Dict[LocalId, LocalId]

    def fixup_var(self, var: LocalId | GlobalId) -> LocalId | GlobalId:
        if isinstance(var, GlobalId):
            return var
        if var not in self.substitutions:
            return var
        return self.substitutions[var]

def merge_locals_function(function: ConcreteFunction):
    disjoint = Disjoint(set(), set(), {})
    merge_locals_scope(function.body, function.locals, disjoint)

def merge_locals_scope(scope: Scope, locals: Dict[LocalId, Local], disjoint: Disjoint):
    for word in scope.words:
        merge_locals_word(word, locals, disjoint)

def merge_locals_word(word: Word, locals: Dict[LocalId, Local], disjoint: Disjoint):
    if isinstance(word, InitWord):
        reused_local = find_disjoint_local(locals, disjoint, locals[word.local_id])
        if reused_local is None:
            return
        del locals[word.local_id]
        disjoint.substitutions[word.local_id] = reused_local
        word.local_id = reused_local
        return
    if isinstance(word, GetWord):
        word.local_id = disjoint.fixup_var(word.local_id)
        return
    if isinstance(word, SetWord):
        word.local_id = disjoint.fixup_var(word.local_id)
        return
    if isinstance(word, RefWord):
        word.local_id = disjoint.fixup_var(word.local_id)
        return
    if isinstance(word, StoreWord):
        word.local = disjoint.fixup_var(word.local)
        return
    if isinstance(word, IfWord):
        outer_reused = disjoint.reused.copy()
        merge_locals_scope(word.true_branch, locals, disjoint)
        disjoint.reused = outer_reused

        disjoint.scopes.add(word.true_branch.id)
        outer_reused = disjoint.reused.copy()
        merge_locals_scope(word.false_branch, locals, disjoint)
        disjoint.reused = outer_reused
        disjoint.scopes.add(word.false_branch.id)
        return
    if isinstance(word, BlockWord):
        outer_reused = disjoint.reused.copy()
        merge_locals_scope(word.body, locals, disjoint)
        disjoint.reused = outer_reused
        disjoint.scopes.add(word.body.id)
        return
    if isinstance(word, LoopWord):
        outer_reused = disjoint.reused.copy()
        merge_locals_scope(word.body, locals, disjoint)
        disjoint.reused = outer_reused
        disjoint.scopes.add(word.body.id)
        return
    if isinstance(word, StructWord):
        outer_reused = disjoint.reused.copy()
        merge_locals_scope(word.body, locals, disjoint)
        disjoint.reused = outer_reused
        disjoint.scopes.add(word.body.id)
        return
    if isinstance(word, MatchWord):
        for cays in word.cases:
            outer_reused = disjoint.reused.copy()
            merge_locals_scope(cays.body, locals, disjoint)
            disjoint.reused = outer_reused
            disjoint.scopes.add(cays.body.id)
        if word.default is not None:
            outer_reused = disjoint.reused.copy()
            merge_locals_scope(word.default, locals, disjoint)
            disjoint.reused = outer_reused
            disjoint.scopes.add(word.default.id)

def find_disjoint_local(locals: Dict[LocalId, Local], disjoint: Disjoint, to_be_replaced: Local) -> LocalId | None:
    local_size = to_be_replaced.taip.size()
    if len(disjoint.scopes) == 0:
        return None
    for local_id, local in locals.items():
        if local.lives_in_memory() != to_be_replaced.lives_in_memory():
            continue
        if local.taip.size() != local_size:
            continue
        if local_id.scope not in disjoint.scopes:
            continue
        if local_id in disjoint.reused:
            continue
        disjoint.reused.add(local_id)
        return local_id
    return None

class DetermineLoadsToValueTests(unittest.TestCase):
    def test_no_fields_returns_empty(self) -> None:
        loads = determine_loads([])
        self.assertTrue(len(loads) == 0)

    def test_by_value_on_struct(self) -> None:
        loads = determine_loads([
            FieldAccess(Token.dummy("x"), CustomTypeType.dummy("Foo", 12), I32(), 4)
        ])
        self.assertTrue(len(loads) == 1)
        self.assertTrue(loads[0] == OffsetLoad(4, I32()))

    def test_by_value_on_struct_packed(self) -> None:
        loads = determine_loads([
            FieldAccess(Token.dummy("x"), CustomTypeType.dummy("Foo", 8), I32(), 0)
        ])
        self.assertTrue(len(loads) == 1)
        self.assertTrue(loads[0] == I32InI64(0))

    def test_packed_value_on_struct_in_mem(self) -> None:
        loads = determine_loads([
            FieldAccess(Token.dummy("x"), CustomTypeType.dummy("Foo", 8), I32(), 0)
        ], base_in_mem=True)
        self.assertEqual(loads, [OffsetLoad(0, I32())])

    def test_by_value_on_struct_packed_small_noop(self) -> None:
        loads = determine_loads([
            FieldAccess(Token.dummy("x"), CustomTypeType.dummy("Foo", 4), I32(), 0)
        ])
        self.assertEqual(loads, [])

    def test_by_value_on_nested_struct(self) -> None:
        foo = CustomTypeType.dummy("Foo", 12)
        v2 = CustomTypeType.dummy("V2", 8)
        loads = determine_loads([
            FieldAccess(Token.dummy("v"), foo, v2               , 4),
            FieldAccess(Token.dummy("x"), v2 , I32(), 0),
        ])
        self.assertEqual(loads, [OffsetLoad(4, I32())])

    def test_by_value_through_ptr(self) -> None:
        node = CustomTypeType.dummy("Node", 12)
        loads = determine_loads([
            FieldAccess(Token.dummy("next") , node         , PtrType(node)    , 4),
            FieldAccess(Token.dummy("value"), PtrType(node), I32(), 0),
        ])
        self.assertTrue(len(loads) == 1)
        self.assertTrue(loads[0] == OffsetLoad(4, I32()))

    def test_by_value_through_two_ptrs(self) -> None:
        node = CustomTypeType.dummy("Node", 12)
        loads = determine_loads([
            FieldAccess(Token.dummy("next") , node         , PtrType(node)    , 4),
            FieldAccess(Token.dummy("next") , PtrType(node), PtrType(node)    , 4),
            FieldAccess(Token.dummy("value"), PtrType(node), I32(), 0),
        ])
        self.assertEqual(loads, [
            OffsetLoad(8, PtrType(node)),
            OffsetLoad(0, I32())])

    def test_get_sub_struct_by_value(self) -> None:
        bar = CustomTypeType.dummy("Bar", 12)
        loads = determine_loads([
            FieldAccess(Token.dummy("v"), CustomTypeType.dummy("Foo", 16), bar, 4)
        ])
        self.assertEqual(loads, [OffsetLoad(4, bar)])

    def test_get_subsub_struct_by_value(self) -> None:
        bar = CustomTypeType.dummy("Bar", 12)
        inner = CustomTypeType.dummy("BarInner", 12)
        loads = determine_loads([
            FieldAccess(Token.dummy("v")    , CustomTypeType.dummy("Foo", 16), bar  , 4),
            FieldAccess(Token.dummy("inner"), bar                        , inner, 0),
        ])
        self.assertEqual(loads, [OffsetLoad(4, inner)])

    def test_by_ref_get_on_large_value(self) -> None:
        node = CustomTypeType.dummy("Node", 12)
        loads = determine_loads([
            FieldAccess(Token.dummy("next") , PtrType(node), PtrType(node)    , 4),
            FieldAccess(Token.dummy("value"), PtrType(node), I32(), 0),
        ])
        self.assertEqual(loads, [
            OffsetLoad(4, PtrType(node)),
            OffsetLoad(0, I32())])

    def test_by_ref_get_on_packed_value(self) -> None:
        node = CustomTypeType.dummy("Node", 8)
        loads = determine_loads([
            FieldAccess(Token.dummy("next") , PtrType(node), PtrType(node)    , 4),
            FieldAccess(Token.dummy("value"), PtrType(node), I32(), 0),
        ])
        self.assertTrue(len(loads) == 2)
        self.assertTrue(loads[0] == OffsetLoad(4, PtrType(node)))
        self.assertTrue(loads[1] == OffsetLoad(0, I32()))

    def test_get_through_bitshift(self) -> None:
        node = CustomTypeType.dummy("Node", 8)
        loads = determine_loads([
            FieldAccess(Token.dummy("next") , node         , PtrType(node)    , 4),
            FieldAccess(Token.dummy("value"), PtrType(node), I32(), 0),
        ])
        self.assertTrue(len(loads) == 2)
        self.assertTrue(loads[0] == I32InI64(4))
        self.assertTrue(loads[1] == OffsetLoad(0, I32()))

    def test_ref_field_in_big_struct(self) -> None:
        ctx = CustomTypeType.dummy("Ctx", 12)
        loads = determine_loads([
            FieldAccess(Token.dummy("counter"), ctx, I32(), 8),
        ], just_ref=True)
        self.assertTrue(len(loads) == 1)
        self.assertTrue(loads[0] == Offset(8))

    def test_ref_subfield_in_big_struct(self) -> None:
        ctx = CustomTypeType.dummy("Ctx", 20)
        word_ctx = CustomTypeType.dummy("WordCtx", 12)
        loads = determine_loads([
            FieldAccess(Token.dummy("word-ctx"), ctx              , word_ctx         , 4),
            FieldAccess(Token.dummy("counter") , PtrType(word_ctx), I32(), 8),
        ], just_ref=True)
        self.assertTrue(len(loads) == 1)
        self.assertTrue(loads[0] == Offset(12))

    def test_ref_field_in_big_struct_at_offset_0(self) -> None:
        ctx = CustomTypeType.dummy("Ctx", 12)
        loads = determine_loads([
            FieldAccess(Token.dummy("counter"), ctx, I32(), 0),
        ], just_ref=True)
        self.assertTrue(len(loads) == 0)

    def test_ignored_wrapper_struct(self) -> None:
        allocator = CustomTypeType.dummy("PageAllocator", 4)
        page = CustomTypeType.dummy("Page", 12)
        loads = determine_loads([
            FieldAccess(Token.dummy("free-list"), allocator    , PtrType(page)    , 0),
            FieldAccess(Token.dummy("foo")      , PtrType(page), I32(), 4),
        ], just_ref=True)
        self.assertEqual(loads, [Offset(4)])

    def test_no_unnecessary_bitshift_on_ptr(self) -> None:
        foo = CustomTypeType.dummy("Foo", 12)
        v2 = CustomTypeType.dummy("V2", 8)
        loads = determine_loads([
            FieldAccess(Token.dummy("v")  , foo, v2               , 8),
            FieldAccess(Token.dummy("foo"), v2 , I32(), 4),
        ])
        self.assertEqual(loads, [OffsetLoad(12, I32())])

    def test_set_field_on_ptr(self) -> None:
        small = CustomTypeType.dummy("Small", 4)
        loads = determine_loads([
            FieldAccess(Token.dummy("value"), PtrType(small), I32(), 0),
        ], just_ref=True)
        self.assertEqual(loads, [])

    def test_get_value_on_packed_but_reffed_struct(self) -> None:
        prestat = CustomTypeType.dummy("Prestat", 8)
        loads = determine_loads([
            FieldAccess(Token.dummy("path_len"), prestat, I32(), 4)
        ], base_in_mem=True)
        self.assertEqual(loads, [OffsetLoad(4, I32())])

    def test_get_struct_through_ptr(self) -> None:
        named_type = CustomTypeType.dummy("NamedType", 16)
        taip = CustomTypeType.dummy("Type", 12)
        loads = determine_loads([
            FieldAccess(Token.dummy("type"), PtrType(named_type), taip, 4),
        ])
        self.assertEqual(loads, [OffsetLoad(4, taip)])

    def test_packed_value_field_through_ptr(self) -> None:
        token = CustomTypeType.dummy("Token", 8)
        immediate_string = CustomTypeType.dummy("ImmediateString", 4)
        loads = determine_loads([
            FieldAccess(Token.dummy("lexeme"), PtrType(token), PtrType(immediate_string), 4),
            FieldAccess(Token.dummy("len"), PtrType(immediate_string), I32(), 0),
        ])
        self.assertEqual(loads, [
            OffsetLoad(4, PtrType(immediate_string)),
            OffsetLoad(0, I32())])

    def test_set_field_through_bitshift(self) -> None:
        token = CustomTypeType.dummy("Token", 8)
        immediate_string = CustomTypeType.dummy("ImmediateString", 4)
        loads = determine_loads([
            FieldAccess(Token.dummy("lexeme"), token, PtrType(immediate_string), 4),
            FieldAccess(Token.dummy("len"), PtrType(immediate_string), I32(), 0),
        ], just_ref=True)
        self.assertEqual(loads, [I32InI64(4)])

def merge_loads(loads: List[Load]) -> List[Load]:
    if len(loads) <= 1:
        return loads
    a = loads[0]
    b = loads[1]
    if isinstance(a, OffsetLoad) and is_bitshift(b):
        return [OffsetLoad(a.offset + b.offset, I32())] + loads[2:]
    if isinstance(a, Offset) and isinstance(b, Offset):
        return [Offset(a.offset + b.offset)] + loads[2:]
    if isinstance(a, Offset) and isinstance(b, OffsetLoad):
        return [OffsetLoad(a.offset + b.offset, b.taip)] + loads[2:]
    if isinstance(a, I32InI64) and isinstance(b, I8InI32):
        return [I8InI64(a.offset + b.offset)] + loads[2:]
    if isinstance(a, I32InI64) and isinstance(b, I8InI32):
        return [I8InI32(a.offset + b.offset)] + loads[2:]
    if isinstance(a, I16InI32) and isinstance(b, I8InI32):
        return [I8InI32(a.offset + b.offset)] + loads[2:]
    return loads

# Returns the loads necessary to get the value of the final field on the stack.
def determine_loads(fields: List[FieldAccess], just_ref: bool = False, base_in_mem: bool = False) -> List[Load]:
    if len(fields) == 0:
        return []
    field = fields[0]
    if isinstance(field.source_taip, CustomTypeType):
        offset = field.offset
        if base_in_mem or field.source_taip.size() > 8:
            if len(fields) > 1 or just_ref:
                load: Load = Offset(offset)
            else:
                load = OffsetLoad(offset, field.target_taip)
            if load == Offset(0):
                return determine_loads(fields[1:], just_ref, base_in_mem=True)
            return merge_loads([load] + determine_loads(fields[1:], just_ref, base_in_mem=True))

        source_type_size = field.source_taip.size()
        target_type_size = field.target_taip.size()
        if source_type_size > 4: # source_taip is between >=4 and <=8 bytes
            if target_type_size == 1:
                load = I8InI64(offset)
            elif target_type_size == 4:
                load = I32InI64(offset)
            else:
                assert(False) # TODO
            return merge_loads([load] + determine_loads(fields[1:], just_ref, base_in_mem))

        if target_type_size != source_type_size:
            if target_type_size == 1:
                return merge_loads([I8InI32(offset)] + determine_loads(fields[1:], just_ref, base_in_mem))
            if target_type_size == 2:
                return merge_loads([I16InI32(offset)] + determine_loads(fields[1:], just_ref, base_in_mem))
            assert(False) # TODO

        assert(field.source_taip.size() == 4) # alternative is TODO
        return determine_loads(fields[1:], just_ref, base_in_mem)

    if isinstance(field.source_taip, PtrType):
        if (just_ref and len(fields) == 1) or (not field.target_taip.can_live_in_reg() and len(fields) != 1):
            # Instead of actually loading the value, we just ref it, since this is
            # the last field access in the chain and `just_ref` is set.
            if field.offset == 0:
                return determine_loads(fields[1:], just_ref, base_in_mem)
            return merge_loads([Offset(field.offset)] + determine_loads(fields[1:], just_ref, base_in_mem))

        return merge_loads([OffsetLoad(field.offset, field.target_taip)] + determine_loads(fields[1:], just_ref, base_in_mem))

    assert_never(field.source_taip)
