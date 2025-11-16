from typing import List, Dict, Sequence, assert_never
from dataclasses import dataclass, field

from util import uhex, listtostr, align_to
from lexer import Token
from checking.words import StringWord, NumberWord
from resolving.words import ScopeId, GlobalId, LocalId, BreakWord, ROOT_SCOPE
from checking.intrinsics import IntrinsicMemCopy, IntrinsicMemGrow, IntrinsicDrop, IntrinsicMemFill, IntrinsicSetStackSize
from parsing.types import I8, I32, I64, Bool
import monomizer
from monomizer import Type, Load, is_bitshift, I32InI64, I8InI32, I8InI64, Local, format_type, FunctionHandle, NamedType, GenericFunction, Extern, TupleMakeWord, UnnamedStructWord, Variant, IfWord, StructWord, MatchWord, LoadWord, BlockWord, LoopWord, SizeofWord, FunRefWord, MatchCase, PtrType, CastWord, IntrinsicUninit, IntrinsicFlip, IntrinsicShl, IntrinsicRotl, IntrinsicRotr, IntrinsicAnd, FunctionType, StoreWord, CustomTypeType, VariantWord, StructFieldInitWord, TupleUnpackWord, FunctionSignature, IntrinsicStore, IntrinsicAdd, IntrinsicMul, IntrinsicOr, IntrinsicEqual, IntrinsicNotEqual, IntrinsicGreaterEq, IntrinsicLess, IntrinsicShr, IntrinsicNot, IntrinsicGreater, IntrinsicLessEq, IntrinsicDiv, ParameterLocal, IndirectCallWord, ExternHandle, IntrinsicSub, Global, CustomTypeHandle, TypeDefinition, ConcreteFunction, Word, GetWord, GetFieldWord, SetWord, RefWord, InitWord, CallWord, IntrinsicMod, Function, MatchVoidWord

@dataclass
class WatGenerator:
    modules: Dict[int, monomizer.Module]
    function_table: Dict[FunctionHandle | ExternHandle, int]
    guard_stack: bool
    chunks: List[str] = field(default_factory=list)
    indentation: int = 0
    globals: Dict[GlobalId, Global]= field(default_factory=dict)
    module_data_offsets: Dict[int, int] = field(default_factory=dict)

    pack_i32s_used: bool = False
    unpack_i32s_used: bool = False
    flip_i64_i32_used: bool = False
    flip_i32_i64_used: bool = False
    flip_i64_i64_used: bool = False
    dup_i64_used: bool = False

    def write(self, s: str) -> None:
        self.chunks.append(s)

    def write_indent(self) -> None:
        self.chunks.append("\t" * self.indentation)

    def write_line(self, line: str) -> None:
        self.write_indent()
        self.write(line)
        self.write("\n")

    def indent(self) -> None:
        self.indentation += 1

    def dedent(self) -> None:
        self.indentation -= 1

    def lookup_type_definition(self, handle: CustomTypeHandle) -> TypeDefinition:
        return self.modules[handle.module].type_definitions[handle.index][handle.instance]

    def lookup_extern(self, handle: ExternHandle) -> Extern:
        return self.modules[handle.module].externs[handle.index]

    def lookup_function(self, handle: FunctionHandle) -> ConcreteFunction:
        function = self.modules[handle.module].functions[handle.index]
        if isinstance(function, GenericFunction):
            assert(handle.instance is not None)
            return function.instances[handle.instance]
        return function

    def write_wat_module(self) -> str:
        assert(len(self.chunks) == 0)
        self.write_line("(module")
        self.indent()
        for module in self.modules.values():
            for extern in module.externs.values():
                self.write_extern(module.id, extern)
                self.write("\n")
            for i, globl in enumerate(module.globals):
                self.globals[GlobalId(globl.name, module.id, i)] = globl

        self.write_line("(memory 1 65536)")
        self.write_line("(export \"memory\" (memory 0))")

        all_data: bytes = b""
        for id in sorted(self.modules):
            self.module_data_offsets[id] = len(all_data)
            all_data += self.modules[id].data

        self.write_function_table()

        data_end = align_to(len(all_data), 4)
        global_mem = self.write_globals(data_end)
        stack_start = align_to(global_mem, 4)
        self.write_line(f"(global $stac:k (mut i32) (i32.const {stack_start}))")
        if self.guard_stack:
            self.write_line("(global $stack-siz:e (mut i32) (i32.const 65536))")

        self.write_data(all_data)

        for module_id in sorted(self.modules):
            module = self.modules[module_id]
            for function in sorted(module.functions.keys()):
                self.write_function(module_id, module.functions[function])

        self.write_intrinsics()

        self.dedent()
        self.write(")")
        return ''.join(self.chunks)

    def write_function(self, module: int, function: Function, instance_id: int | None = None) -> None:
        if isinstance(function, GenericFunction):
            for (id, instance) in function.instances.items():
                self.write_function(module, instance, id)
            return
        self.write_indent()
        self.write("(")
        self.write_signature(module, function.name, function.export_name, function.signature, instance_id, function.locals)
        if len(function.signature.generic_arguments) > 0:
            self.write(" ;;")
            for taip in function.signature.generic_arguments:
                self.write(" ")
                self.write_type_human(taip)
        self.write("\n")
        self.indent()
        self.write_locals(function.locals)
        for i in range(0, function.max_struct_ret_count):
            self.write_indent()
            self.write(f"(local $s{i}:4 i32) (local $s{i}:8 i64)\n")
        if function.locals_copy_space != 0:
            self.write_indent()
            self.write("(local $locl-copy-spac:e i32)\n")

        uses_stack = function.locals_copy_space != 0 or any(local.lives_in_memory() for local in function.locals.values())
        if uses_stack:
            self.write_indent()
            self.write("(local $stac:k i32)\n")
            self.write_indent()
            self.write("global.get $stac:k local.set $stac:k\n")

        if function.locals_copy_space != 0:
            self.write_mem("locl-copy-spac:e", function.locals_copy_space, ROOT_SCOPE, 0)
        self.write_structs(function.locals)
        if uses_stack and self.guard_stack:
            self.write_line("call $stack-overflow-guar:d")
        self.write_words(module, { id: local.name.get() for id, local in function.locals.items() }, function.body.words)
        if uses_stack:
            self.write_line("local.get $stac:k global.set $stac:k")
        self.dedent()
        self.write_line(")")

    def write_mem(self, name: str, size: int, scope: ScopeId, shadow: int) -> None:
        self.write_indent()
        self.write(f"global.get $stac:k global.get $stac:k i32.const {align_to(size, 4)} i32.add global.set $stac:k local.set ${name}")
        if scope != ROOT_SCOPE or shadow != 0:
            self.write(f":{scope}:{shadow}")
        self.write("\n")

    def write_structs(self, locals: Dict[LocalId, Local]) -> None:
        for local_id, local in locals.items():
            if not isinstance(local, ParameterLocal) and local.lives_in_memory():
                self.write_mem(local.name.get(), local.taip.size(), local_id.scope, local_id.shadow)
            if isinstance(local, ParameterLocal) and local.needs_moved_into_memory():
                self.write_indent()
                self.write("global.get $stac:k global.get $stac:k local.get $")
                if not local.can_be_abused_as_ref():
                    self.write("v:")
                self.write(f"{local.name.get()} ")
                self.write_type(local.taip)
                self.write(f".store local.tee ${local.name.get()} i32.const {align_to(local.taip.size(), 4)} i32.add global.set $stac:k\n")

    def write_locals(self, locals: Dict[LocalId, Local]) -> None:
        for local_id, local in locals.items():
            if isinstance(local, ParameterLocal):
                if local.needs_moved_into_memory() and not local.can_be_abused_as_ref():
                    self.write_line(f"(local ${local.name.get()} i32)")
                continue
            local = locals[local_id]
            self.write_indent()
            self.write(f"(local ${local.name.get()}")
            if local_id.scope != ROOT_SCOPE or local_id.shadow != 0:
                self.write(f":{local_id.scope}:{local_id.shadow}")
            self.write(" ")
            if local.lives_in_memory():
                self.write("i32")
            else:
                self.write_type(local.taip)
            self.write(")\n")

    def write_words(self, module: int, locals: Dict[LocalId, str], words: List[Word]) -> None:
        for word in words:
            self.write_word(module, locals, word)

    def write_local_ident(self, locals: Dict[LocalId, str], local: LocalId) -> None:
        if local.scope != ROOT_SCOPE or local.shadow != 0:
            self.write(f"${locals[local]}:{local.scope}:{local.shadow}")
        else:
            self.write(f"${locals[local]}")

    def write_word(self, module: int, locals: Dict[LocalId, str], word: Word) -> None:
        match word:
            case NumberWord(token):
                self.write_line(f"i32.const {token.lexeme}")
            case GetWord(token, local_id, target_taip, loads, copy_space_offset, var_lives_in_memory):
                self.write_indent()
                if not target_taip.can_live_in_reg():
                    # set up the address to store the result in
                    self.write(f"local.get $locl-copy-spac:e i32.const {copy_space_offset} i32.add call $intrinsic:dupi32 ")
                if isinstance(local_id, GlobalId):
                    self.write(f"global.get ${token.lexeme}:{local_id.module}")
                else:
                    self.write("local.get ")
                    self.write_local_ident(locals, local_id)
                # at this point, either the value itself or a pointer to it is on the stack
                for i, load in enumerate(loads):
                    self.write(" ")
                    self.write(str(load))
                if len(loads) == 0:
                    if target_taip.can_live_in_reg():
                        if var_lives_in_memory:
                            self.write(" ")
                            self.write_type(target_taip)
                            self.write(".load\n")
                            return
                    else:
                        self.write(f" i32.const {target_taip.size()} memory.copy")
                self.write("\n")
            case GetFieldWord(token, target_taip, loads, on_ptr, copy_space_offset):
                if len(loads) == 0:
                    self.write_line(";; GetField was no-op")
                    return
                self.write_indent()
                if not on_ptr and not target_taip.can_live_in_reg():
                    self.write(f"local.get $locl-copy-spac:e i32.const {copy_space_offset} i32.add call $intrinsic:dupi32 call $intrinsic:rotate-left ")
                for load in loads:
                    self.write(str(load))
                self.write("\n")
            case RefWord(token, local_id, loads):
                self.write_indent()
                if isinstance(local_id, GlobalId):
                    self.write(f"global.get ${token.lexeme}:{local_id.module}")
                if isinstance(local_id, LocalId):
                    self.write("local.get ")
                    self.write_local_ident(locals, local_id)
                for i, load in enumerate(loads):
                    self.write(f" {load}")
                self.write("\n")
            case SetWord(token, local_id, target_taip, loads, target_lives_in_memory):
                self.write_set(local_id, locals, target_lives_in_memory, target_taip, loads)
            case InitWord(name, local_id, taip, var_lives_in_memory):
                self.write_set(local_id, locals, var_lives_in_memory, taip, [])
            case CallWord(name, function_handle, return_space_offset):
                self.write_indent()
                match function_handle:
                    case ExternHandle():
                        extern = self.lookup_extern(function_handle)
                        signature = extern.signature
                        self.write(f"call ${function_handle.module}:{name.lexeme}")
                    case FunctionHandle():
                        function = self.lookup_function(function_handle)
                        signature = function.signature
                        self.write(f"call ${function_handle.module}:{function.name.lexeme}")
                        if function_handle.instance is not None and function_handle.instance != 0:
                            self.write(f":{function_handle.instance}")
                    case other:
                        assert_never(other)
                self.write_return_struct_receiving(return_space_offset, signature.returns)
            case IndirectCallWord(token, taip, return_space_offset):
                self.write_indent()
                self.write("(call_indirect")
                self.write_parameters(taip.parameters)
                self.write_returns(taip.returns)
                self.write(")")
                self.write_return_struct_receiving(return_space_offset, taip.returns)
            case IntrinsicStore(token, taip):
                self.write_indent()
                self.write_store(taip)
                self.write("\n")
            case IntrinsicAdd(token, taip):
                if isinstance(taip, PtrType) or isinstance(taip, I32) or isinstance(taip, I8):
                    self.write_line("i32.add")
                    return
                if isinstance(taip, I64):
                    self.write_line("i64.add")
                    return
                assert_never(taip)
            case IntrinsicSub(token, taip):
                if isinstance(taip, PtrType) or isinstance(taip, I32) or isinstance(taip, I8):
                    self.write_line("i32.sub")
                    return
                if isinstance(taip, I64):
                    self.write_line("i64.sub")
                    return
                assert_never(taip)
            case IntrinsicMul(_, taip):
                self.write_line(f"{'i64' if isinstance(taip, I64) else 'i32'}.mul")
            case IntrinsicDrop():
                self.write_line("drop")
            case IntrinsicOr(_, taip):
                self.write_indent()
                self.write_type(taip)
                self.write(".or\n")
            case IntrinsicEqual(_, taip):
                if taip.size() > 4:
                    self.write_line("i64.eq")
                    return
                assert(taip.can_live_in_reg())
                self.write_line("i32.eq")
            case IntrinsicNotEqual(_, taip):
                if taip.size() > 4:
                    assert(taip.can_live_in_reg())
                    self.write_line("i64.ne")
                    return
                assert(taip.can_live_in_reg())
                self.write_line("i32.ne")
            case IntrinsicGreaterEq(_, taip):
                if isinstance(taip, I32) or isinstance(taip, I8):
                    self.write_line("i32.ge_u")
                    return
                if isinstance(taip, I64):
                    self.write_line("i64.ge_u")
                    return
                assert_never(taip)
            case IntrinsicGreater(_, taip):
                if isinstance(taip, I32) or isinstance(taip, I8):
                    self.write_line("i32.gt_u")
                    return
                if isinstance(taip, I64):
                    self.write_line("i64.gt_u")
                    return
                assert_never(taip)
            case IntrinsicLessEq(_, taip):
                if isinstance(taip, I32) or isinstance(taip, I8):
                    self.write_line("i32.le_u")
                    return
                if isinstance(taip, I64):
                    self.write_line("i64.le_u")
                    return
                assert_never(taip)
            case IntrinsicLess(_, taip):
                if isinstance(taip, I32) or isinstance(taip, I8):
                    self.write_line("i32.lt_u")
                    return
                if isinstance(taip, I64):
                    self.write_line("i64.lt_u")
                    return
                assert_never(taip)
            case IntrinsicFlip(_, lower, upper):
                lower_type = "i32" if lower.size() <= 4 or lower.size() > 8 else "i64"
                upper_type = "i32" if upper.size() <= 4 or upper.size() > 8 else "i64"
                if lower_type == "i32" and upper_type == "i64":
                    self.flip_i32_i64_used = True
                    self.write_line("call $intrinsic:flip-i32-i64")
                    return
                if lower_type == "i64" and upper_type == "i32":
                    self.flip_i64_i32_used = True
                    self.write_line("call $intrinsic:flip-i64-i32")
                    return
                if lower_type == "i32":
                    self.write_line("call $intrinsic:flip")
                    return
                self.flip_i64_i64_used = True
                self.write_line("call $intrinsic:flip-i64-i64")
            case IntrinsicShl(token, taip):
                if isinstance(taip, I64):
                    self.write_line("i64.shl")
                else:
                    self.write_line("i32.shl")
            case IntrinsicShr(token, taip):
                if isinstance(taip, I64):
                    self.write_line("i64.shr")
                else:
                    self.write_line("i32.shr_u")
            case IntrinsicRotl(token, taip):
                if isinstance(taip, I64):
                    self.write_line("i64.rotl")
                else:
                    self.write_line("i32.rotl")
            case IntrinsicRotr(token, taip):
                if isinstance(taip, I64):
                    self.write_line("i64.rotr")
                else:
                    self.write_line("i32.rotr")
            case IntrinsicAnd(_, taip):
                if isinstance(taip, I32) or isinstance(taip, Bool) or isinstance(taip, I8):
                    self.write_line("i32.and")
                    return
                if isinstance(taip, I64):
                    self.write_line("i64.and")
                    return
                assert_never(taip)
            case IntrinsicNot(_, taip):
                if isinstance(taip, Bool):
                    self.write_line("i32.const 1 i32.and i32.const 1 i32.xor i32.const 1 i32.and")
                    return
                if isinstance(taip, I8):
                    self.write_line("i32.const 255 i32.and i32.const 255 i32.xor i32.const 255 i32.and")
                    return
                if isinstance(taip, I32):
                    self.write_line("i32.const -1 i32.xor")
                    return
                if isinstance(taip, I64):
                    self.write_line("i64.const -1 i64.xor")
                    return
                assert_never(taip)
            case IntrinsicMod(_, taip):
                match taip:
                    case I8() | I32():
                        self.write_line("i32.rem_u")
                    case I64():
                        self.write_line("i64.rem_u")
                    case _:
                        assert_never(taip)
            case IntrinsicDiv(_, taip):
                match taip:
                    case I32() | I8():
                        self.write_line("i32.div_u")
                    case I64():
                        self.write_line("i64.div_u")
                    case _:
                        assert_never(taip)
            case IntrinsicMemCopy():
                self.write_line("memory.copy")
            case IntrinsicMemFill():
                self.write_line("memory.fill")
            case IntrinsicMemGrow():
                self.write_line("memory.grow")
            case IntrinsicSetStackSize():
                if self.guard_stack:
                    self.write_line("global.set $stack-siz:e")
                else:
                    self.write_line("drop")
            case IntrinsicUninit(_, taip, copy_space_offset):
                if taip.size() <= 4:
                    self.write_line("i32.const 0")
                elif taip.size() <= 8:
                    self.write_line("i64.const 0")
                else:
                    self.write_line(f"local.get $locl-copy-spac:e i32.const {copy_space_offset} i32.add")
            case CastWord(_, source, taip):
                if (isinstance(source, I32) or isinstance(source, PtrType)) and isinstance(taip, PtrType):
                    self.write_line(f";; cast to {format_type(taip)}")
                    return
                if isinstance(source, I32) and isinstance(taip, FunctionType):
                    self.write_line(f";; cast to {format_type(taip)}")
                    return
                if isinstance(source, I32) and isinstance(taip, CustomTypeType) and taip.size() == 4:
                    self.write_line(f";; cast to {format_type(taip)}")
                    return
                if (isinstance(source, Bool) or isinstance(source, I32)) and isinstance(taip, I64):
                    self.write_line("i64.extend_i32_u ;; cast to i64")
                    return
                if (isinstance(source, Bool) or isinstance(source, I32)) and isinstance(taip, I8):
                    self.write_line(f"i32.const 0xFF i32.and ;; cast to {format_type(taip)}")
                    return
                if isinstance(source, I64) and isinstance(taip, I8): 
                    self.write_line(f"i64.const 0xFF i64.and i32.wrap_i64 ;; cast to {format_type(taip)}")
                    return
                if isinstance(source, I64) and not isinstance(taip, I64):
                    self.write_line(f"i32.wrap_i64 ;; cast to {format_type(taip)}")
                    return
                if source.can_live_in_reg() and source.size() <= 4 and isinstance(taip, I32):
                    self.write_line(f";; cast to {format_type(taip)}")
                    return
                if source.can_live_in_reg() and source.size() <= 8 and isinstance(taip, I64):
                    self.write_line(f";; cast to {format_type(taip)}")
                    return
                self.write_line(f"UNSUPPORTED Cast from {format_type(source)} to {format_type(taip)}")
            case StringWord(_, offset, string_len):
                self.write_line(f"i32.const {self.module_data_offsets[module] + offset} i32.const {string_len}")
            case SizeofWord(_, taip):
                self.write_line(f"i32.const {taip.size()}")
            case FunRefWord(_, table_index):
                self.write_line(f"i32.const {table_index + 1}")
            case StoreWord(token, local_id, target_taip, loads):
                self.write_indent()
                if isinstance(local_id, GlobalId):
                    self.write(f"global.get ${token.lexeme}:{local_id.module}")
                else:
                    self.write("local.get ")
                    self.write_local_ident(locals, local_id)
                for load in loads:
                    # self.write(f" i32.load offset={offset}")
                    self.write(f" {load}")
                self.write(" call $intrinsic:flip ")
                self.write_store(target_taip)
                self.write("\n")
            case LoadWord(_, taip, copy_space_offset):
                self.write_indent()
                if not taip.can_live_in_reg():
                    self.write(f"local.get $locl-copy-spac:e i32.const {copy_space_offset}")
                    self.write(f" i32.add call $intrinsic:dupi32 call $intrinsic:rotate-left i32.const {word.taip.size()} memory.copy\n")
                elif taip.size() == 1:
                    self.write("i32.load8_u\n")
                else:
                    self.write_type(taip)
                    self.write(".load\n")
            case BreakWord():
                self.write_line("br $block")
            case BlockWord(token, body, parameters, returns):
                self.write_indent()
                self.write("(block $block")
                self.write_parameters(parameters)
                self.write_returns(returns)
                self.write("\n")
                self.indent()
                self.write_words(module, locals, body.words)
                self.dedent()
                self.write_line(")")
            case LoopWord(_, body, parameters, returns, diverges):
                self.write_indent()
                self.write("(block $block ")
                self.write_parameters(parameters)
                self.write_returns(returns)
                self.write("\n")
                self.indent()
                self.write_indent()
                self.write("(loop $loop ")
                self.write_parameters(parameters)
                self.write_returns(returns)
                self.write("\n")
                self.indent()
                self.write_words(module, locals, body.words)
                self.write_line("br $loop")
                self.dedent()
                self.write_line(")")
                self.dedent()
                self.write_line(")")
                if diverges:
                    self.write_line("unreachable")
            case IfWord(_, parameters, returns, true_branch, false_branch, diverges):
                self.write_indent()
                self.write("(if")
                self.write_parameters(parameters)
                self.write_returns(returns or [])
                self.write("\n")
                self.indent()
                self.write_line("(then")
                self.indent()
                self.write_words(module, locals, true_branch.words)
                self.dedent()
                self.write_line(")")
                if len(false_branch.words) > 0:
                    self.write_line("(else")
                    self.indent()
                    self.write_words(module, locals, false_branch.words)
                    self.dedent()
                    self.write_line(")")
                self.dedent()
                self.write_line(")")
                if diverges:
                    self.write_line("unreachable")
            case StructWord(_, taip, copy_space_offset, body):
                self.write_indent()
                struct = self.lookup_type_definition(taip.struct)
                assert(not isinstance(struct, Variant))
                if taip.size() == 0:
                    for field in struct.fields.get():
                        self.write("drop ")
                    self.write(f"i32.const 0 ;; make {format_type(taip)}\n")
                    return
                self.write(f";; make {format_type(taip)}\n")
                self.indent()
                self.write_words(module, locals, body.words)
                self.dedent()
                self.write_indent()
                self.write(f"local.get $locl-copy-spac:e i32.const {copy_space_offset} i32.add ")
                if taip.size() <= 4:
                    self.write("i32.load ")
                elif taip.size() <= 8:
                    self.write("i64.load ")
                self.write(f";; make {format_type(taip)} end\n")
            case UnnamedStructWord(_, taip, copy_space_offset):
                self.write_indent()
                struct = self.lookup_type_definition(taip.struct)
                assert(not isinstance(struct, Variant))
                if taip.can_live_in_reg():
                    fields = struct.fields.get()
                    if len(fields) == 1:
                        self.write(f";; make {format_type(taip)}\n")
                        return
                    if taip.size() == 0:
                        for field in fields:
                            self.write("drop ")
                        self.write(f"i32.const 0 ;; make {format_type(taip)}\n")
                        return
                    if taip.size() <= 8:
                        for i in range(len(fields), 0, -1):
                            offset = struct.field_offset(i - 1)
                            if i != len(fields) and (offset != 0 or taip.size() > 4):
                                if taip.size() <= 4:
                                    self.write("call $intrinsic:flip ")
                                else:
                                    self.write("call $intrinsic:flip-i32-i64 ")
                                    self.flip_i32_i64_used = True
                            if taip.size() > 4:
                                self.write("i64.extend_i32_u ")
                            if offset != 0:
                                if taip.size() <= 4:
                                    self.write(f"i32.const {offset * 8} i32.shl ")
                                else:
                                    self.write(f"i64.const {offset * 8} i64.shl ")
                            if i != len(fields):
                                if taip.size() <= 4:
                                    self.write("i32.or ")
                                else:
                                    self.write("i64.or ")
                        self.write(f";; make {format_type(taip)}\n")
                        return
                self.write(f";; make {format_type(taip)}\n")
                self.indent()
                for i in reversed(range(0, len(struct.fields.get()))):
                    field = struct.fields.get()[i]
                    field_offset = struct.field_offset(i)
                    self.write_indent()
                    self.write(f"local.get $locl-copy-spac:e i32.const {copy_space_offset + field_offset} i32.add ")
                    if field.taip.size() > 4 and field.taip.size() <= 8:
                        self.write("call $intrinsic:flip-i64-i32 ")
                        self.flip_i64_i32_used = True
                    else:
                        self.write("call $intrinsic:flip ")
                    self.write_store(field.taip)
                    self.write("\n")
                self.dedent()
                self.write_line(f"local.get $locl-copy-spac:e i32.const {copy_space_offset} i32.add ;; make {format_type(taip)} end")
            case StructFieldInitWord(_, taip, copy_space_offset):
                self.write_indent()
                self.write(f"local.get $locl-copy-spac:e i32.const {copy_space_offset} i32.add call ")
                if taip.size() <= 4 or taip.size() > 8:
                    self.write("$intrinsic:flip ")
                else:
                    self.write("$intrinsic:flip-i64-i32 ")
                    self.flip_i64_i32_used = True
                self.write_store(taip)
                self.write("\n")
            case MatchVoidWord(token):
                self.write_line(";; match on variant {}")
                self.write_line("unreachable")
            case MatchWord(_, variant_handle, by_ref, cases, default, parameters, returns):
                variant = self.lookup_type_definition(variant_handle)
                def go(remaining_cases: List[MatchCase]):
                    if len(remaining_cases) == 0:
                        if default is None:
                            if len(cases) != 0:
                                self.write("unreachable")
                            return
                        self.write_words(module, locals, default.words)
                        return
                    case = remaining_cases[0]
                    assert(isinstance(variant, Variant))
                    case_taip = variant.cases.get()[case.tag].taip
                    if variant.size() > 8 or by_ref:
                        self.write(f"call $intrinsic:dupi32 i32.load i32.const {case.tag} i32.eq (if")
                    elif variant.size() > 4 and variant.size() <= 8:
                        self.write(f"call $intrinsic:dupi64 i32.wrap_i64 i32.const {case.tag} i32.eq (if")
                        self.dup_i64_used = True
                    else:
                        self.write(f"call $intrinsic:dupi32 i32.const {case.tag} i32.eq (if")
                    self.write_parameters(parameters)
                    variant_inhabits_i64 = variant.size() <= 8 and variant.size() > 4 and not by_ref
                    if variant_inhabits_i64:
                        self.write(" (param i64)")
                    else:
                        self.write(" (param i32)")

                    if returns is not None:
                        self.write_returns(returns)
                    self.write("\n")
                    self.write_line("(then")
                    self.indent()
                    if case_taip is None:
                        self.write_line("drop")
                    elif case_taip.size() != 0:
                        self.write_indent()
                        if by_ref or variant.size() > 8:
                            self.write("i32.const 4 i32.add")
                            if not by_ref and case_taip.can_live_in_reg():
                                if case_taip.size() <= 8 and case_taip.size() > 4:
                                    self.write(" i64.load")
                                else:
                                    self.write(" i32.load")
                        else:
                            self.write("i64.const 32 i64.shr_u i32.wrap_i64")
                        self.write("\n")
                    elif variant_inhabits_i64:
                        self.write_line("i32.wrap_i64")
                    self.write_words(module, locals, case.body.words)
                    self.dedent()
                    self.write_line(")")
                    self.write_indent()
                    if len(remaining_cases) == 1 and default is not None:
                        self.write("(else\n")
                        self.indent()
                        go(remaining_cases[1:])
                        self.dedent()
                        self.write_indent()
                        self.write("))")
                    else:
                        self.write("(else ")
                        go(remaining_cases[1:])
                        self.write("))")
                self.write_line(f";; match on {variant.name.lexeme}")
                self.write_indent()
                go(cases)
                if returns is None:
                    if len(cases) != 0 or default is not None:
                        self.write("\n")
                        self.write_indent()
                    self.write("unreachable")
                self.write("\n")
            case VariantWord(_, tag, variant_handle, copy_space_offset):
                variant = self.lookup_type_definition(variant_handle)
                assert(isinstance(variant, Variant))
                case_taip = variant.cases.get()[tag].taip
                if variant.size() <= 4:
                    assert(variant.size() == 4)
                    self.write_indent()
                    if case_taip is not None:
                        self.write("drop ")
                    self.write(f"i32.const {tag} ;; store tag {variant.name.lexeme}.{variant.cases.get()[tag].name.lexeme}\n")
                    return
                if variant.size() <= 8:
                    if case_taip is None:
                        self.write_line(f"i64.const {tag} ;; make {variant.name.lexeme}.{variant.cases.get()[tag].name.lexeme}")
                    else:
                        self.write_line("i64.extend_i32_u i64.const 32 i64.shl ;; store value")
                        self.write_line(f"i64.const {tag} ;; store tag")
                        self.write_line(f"i64.or ;; make {variant.name.lexeme}.{variant.cases.get()[tag].name.lexeme}")
                    return
                self.write_line(f"local.get $locl-copy-spac:e i32.const {copy_space_offset} i32.add i32.const {tag} i32.store ;; store tag")
                if case_taip is not None:
                    self.write_indent()
                    self.write(f"local.get $locl-copy-spac:e i32.const {copy_space_offset + 4} i32.add ")
                    if case_taip.size() > 4 and case_taip.size() <= 8:
                        self.flip_i64_i32_used = True
                        self.write("call $intrinsic:flip-i64-i32 ")
                    else:
                        self.write("call $intrinsic:flip ")
                    self.write_store(case_taip)
                    self.write(" ;; store value\n")
                self.write_line(f"local.get $locl-copy-spac:e i32.const {copy_space_offset} i32.add ;; make {variant.name.lexeme}.{variant.cases.get()[tag].name.lexeme}")
            case TupleMakeWord(token, tupl, copy_space_offset):
                self.write_indent()
                if tupl.can_live_in_reg():
                    if tupl.size() == 0:
                        for item in tupl.items:
                            self.write("drop ")
                        self.write("i32.const 0 ")
                    if tupl.size() <= 4:
                        pass
                    else:
                        # alternative is TODO
                        assert(len(tupl.items) == 2 and tupl.items[0].size() == 4 and tupl.items[1].size() == 4)
                        self.write("call $intrinsic:pack-i32s")
                        self.pack_i32s_used = True
                    self.write(f";; make {format_type(tupl)}\n")
                    return
                self.write(f";; make {format_type(tupl)}\n")
                item_offset = tupl.size()
                self.indent()
                for item in reversed(tupl.items):
                    item_offset -= item.size()
                    self.write_indent()
                    self.write(f"local.get $locl-copy-spac:e i32.const {copy_space_offset + item_offset} i32.add ")
                    if item.size() > 4 and item.size() <= 8:
                        self.write("call $intrinsic:flip-i64-i32 ")
                        self.flip_i64_i32_used = True
                    else:
                        self.write("call $intrinsic:flip ")
                    self.write_store(item)
                    self.write("\n")
                self.dedent()
                self.write_indent()
                self.write(f"local.get $locl-copy-spac:e i32.const {copy_space_offset} i32.add ;; make {format_type(tupl)} end\n")
            case TupleUnpackWord(token, items, copy_space_offset):
                if len(items) == 2 and items[0].size() == 4 and items[1].size() == 4:
                    self.unpack_i32s_used = True
                    self.write_line(f"call $intrinsic:unpack-i32s ;; unpack {listtostr(items, format_type)}")
                    return
                if len(items) == 0:
                    self.write_line(f"drop ;; unpack {listtostr(items, format_type)}")
                    return
                self.write_line(f";; unpack {listtostr(items, format_type)}")
                self.indent()
                offset = 0
                for i, item in enumerate(items):
                    self.write_indent()
                    if item.size() == 0:
                        self.write("i32.const ")
                        continue
                    if i + 1 != len(items):
                        self.write("call $intrinsic:dupi32 ")
                    self.write(f"i32.const {offset} i32.add ")
                    if not item.can_live_in_reg():
                        self.write(f"local.get $locl-copy-spac:e i32.const {copy_space_offset} i32.add call $intrinsic:dupi32 ")
                        self.write("call $intrinsic:rotate-left ")
                        self.write(f"i32.const {item.size()} memory.copy")
                        copy_space_offset += item.size()
                    elif item.size() <= 4:
                        self.write("i32.load")
                    else:
                        self.write("i64.load")
                    if i + 1 != len(items):
                        if item.size() <= 4 or item.size() > 8:
                            self.write(" call $intrinsic:flip")
                        else:
                            self.write(" call $intrinsic:flip-i32-i64")
                    self.write("\n")
                    offset += item.size()
                self.dedent()
            case other:
                assert_never(other)

    def write_store(self, taip: Type):
        if not taip.can_live_in_reg():
            self.write(f"i32.const {taip.size()} memory.copy")
        elif taip.size() == 1:
            self.write("i32.store8")
        elif taip.size() > 4:
            self.write("i64.store")
        else:
            self.write("i32.store")

    def write_set(self, local_id: LocalId | GlobalId, locals: Dict[LocalId, str], target_lives_in_memory: bool, target_taip: Type, loads: List[Load]):
        self.write_indent()
        def write_ident():
            match local_id:
                case LocalId():
                    self.write_local_ident(locals, local_id)
                    return
                case GlobalId():
                    globl = self.globals[local_id]
                    self.write(f"${globl.name.lexeme}:{local_id.module}")
                    return
                case other:
                    assert_never(other)
        if not target_lives_in_memory and len(loads) == 0:
            if isinstance(local_id, LocalId):
                self.write("local.set ")
            else:
                self.write("global.set ")
            write_ident()
            self.write("\n")
            return
        if isinstance(local_id, LocalId):
            self.write("local.get ")
        else:
            self.write("global.get ")
        write_ident()
        if len(loads) == 0:
            if target_taip.size() > 4 and target_taip.size() <= 8:
                self.write(" call $intrinsic:flip-i64-i32 ")
                self.flip_i64_i32_used = True
            else:
                self.write(" call $intrinsic:flip ")
            self.write_store(target_taip)
            self.write("\n")
            return
        last_load = loads[-1]
        if not target_lives_in_memory and is_bitshift(last_load):
            for i, load in enumerate(loads):
                if all(is_bitshift(load) for load in loads[i:]):
                    break
                self.write(f" {load}")
            if isinstance(last_load, I32InI64) or isinstance(last_load, I8InI64):
                self.write(f" i64.const {uhex(0xFFFFFFFF_FFFFFFFF ^ (0xFFFFFFFF << (last_load.offset * 8)))} i64.and ")
            if isinstance(last_load, I8InI32):
                self.write(f" i32.const {uhex(0xFF << (last_load.offset * 8))} i32.and ")

            self.write("call $intrinsic:flip-i32-i64 i64.extend_i32_u ")
            self.flip_i32_i64_used = True
            if isinstance(last_load, I32InI64) and last_load.offset != 0:
                self.write(f"i64.const {last_load.offset * 8} i64.shl ")
            if isinstance(last_load, I8InI32) and last_load.offset != 0:
                self.write(f"i32.const {last_load.offset * 8} i32.shl ")
            self.write("i32.or " if isinstance(last_load, I8InI32) else "i64.or ")
            if isinstance(local_id, LocalId):
                self.write("local.set ")
            else:
                self.write("global.set ")
            write_ident()
            self.write("\n")
            return

        for i, load in enumerate(loads):
            self.write(f" {load}")
        if target_taip.size() > 4 and target_taip.size() <= 8:
            self.write(" call $intrinsic:flip-i64-i32 ")
        else:
            self.write(" call $intrinsic:flip ")
        self.write_store(target_taip)
        self.write("\n")
        return


    def write_return_struct_receiving(self, offset: int, returns: List[Type]) -> None:
        self.write("\n")
        if all(t.can_live_in_reg() for t in returns):
            return
        for i in range(len(returns), 0, -1):
            ret = returns[i - 1]
            size = 4 if ret.size() > 8 or ret.size() <= 4 else 8
            self.write_line(f"local.set $s{i - 1}:{size}")
        for i,ret in enumerate(returns):
            size = 4 if ret.size() > 8 or ret.size() <= 4 else 8
            if not ret.can_live_in_reg():
                self.write_line(f"local.get $locl-copy-spac:e i32.const {offset} i32.add call $intrinsic:dupi32 local.get $s{i}:{size} i32.const {ret.size()} memory.copy")
                offset += ret.size()
            else:
                self.write_line(f"local.get $s{i}:{size}")

    def write_signature(self, module: int, name: Token, export_name: Token | None, signature: FunctionSignature, instance_id: int | None, locals: Dict[LocalId, Local]) -> None:
        self.write(f"func ${module}:{name.lexeme}")
        if instance_id is not None and instance_id != 0:
            self.write(f":{instance_id}")
        if export_name is not None:
            self.write(f" (export {export_name.lexeme})")
        for parameter in signature.parameters:
            self.write(" (param $")
            for local in locals.values():
                if isinstance(local, ParameterLocal):
                    if local.name.get() == parameter.name.lexeme:
                        if local.lives_in_memory() and local.taip.can_live_in_reg() and local.taip.size() > 4:
                            self.write("v:")
                        break
            self.write(f"{parameter.name.lexeme} ")
            self.write_type(parameter.taip)
            self.write(")")
        self.write_returns(signature.returns)

    def write_type_human(self, taip: Type) -> None:
        self.write(format_type(taip))

    def write_parameters(self, parameters: Sequence[NamedType | Type]) -> None:
        for parameter in parameters:
            if isinstance(parameter, NamedType):
                self.write(f" (param ${parameter.name.lexeme} ")
                self.write_type(parameter.taip)
                self.write(")")
                continue
            self.write(" (param ")
            self.write_type(parameter)
            self.write(")")

    def write_returns(self, returns: List[Type]) -> None:
        for taip in returns:
            self.write(" (result ")
            self.write_type(taip)
            self.write(")")

    def write_intrinsics(self) -> None:
        self.write_line("(func $intrinsic:flip (param $a i32) (param $b i32) (result i32 i32) local.get $b local.get $a)")
        if self.flip_i32_i64_used:
            self.write_line("(func $intrinsic:flip-i32-i64 (param $a i32) (param $b i64) (result i64 i32) local.get $b local.get $a)")
        if self.flip_i64_i32_used:
            self.write_line("(func $intrinsic:flip-i64-i32 (param $a i64) (param $b i32) (result i32 i64) local.get $b local.get $a)")
        if self.flip_i64_i64_used:
            self.write_line("(func $intrinsic:flip-i64-i64 (param $a i64) (param $b i64) (result i64 i64) local.get $b local.get $a)")
        self.write_line("(func $intrinsic:dupi32 (param $a i32) (result i32 i32) local.get $a local.get $a)")
        if self.dup_i64_used:
            self.write_line("(func $intrinsic:dupi64 (param $a i64) (result i64 i64) local.get $a local.get $a)")
        self.write_line("(func $intrinsic:rotate-left (param $a i32) (param $b i32) (param $c i32) (result i32 i32 i32) local.get $b local.get $c local.get $a)")
        if self.pack_i32s_used:
            self.write_line("(func $intrinsic:pack-i32s (param $a i32) (param $b i32) (result i64) local.get $a i64.extend_i32_u local.get $b i64.extend_i32_u i64.const 32 i64.shl i64.or)")
        if self.unpack_i32s_used:
            self.write_line("(func $intrinsic:unpack-i32s (param $a i64) (result i32) (result i32) local.get $a i32.wrap_i64 local.get $a i64.const 32 i64.shr_u i32.wrap_i64)")
        if self.guard_stack:
            self.write_line("(func $stack-overflow-guar:d i32.const 1 global.get $stac:k global.get $stack-siz:e i32.lt_u i32.div_u drop)")

    def write_function_table(self) -> None:
        if len(self.function_table) == 0:
            self.write_line("(table funcref (elem))")
            return
        self.write_line("(table funcref (elem $intrinsic:flip")
        self.indent()
        self.write_indent()
        functions = list(self.function_table.items())
        functions.sort(key=lambda kv: kv[1])
        for i, (handle, _) in enumerate(functions):
            module = self.modules[handle.module]
            if isinstance(handle, FunctionHandle):
                function = module.functions[handle.index]
                if isinstance(function, GenericFunction):
                    assert(handle.instance is not None)
                    function = function.instances[handle.instance]
                    if handle.instance == 0:
                        name = f"${handle.module}:{function.name.lexeme}"
                    else:
                        name = f"${handle.module}:{function.name.lexeme}:{handle.instance}"
                else:
                    name = f"${handle.module}:{function.name.lexeme}"
            else:
                name = "TODO"
            self.write(f"{name}")
            if i + 1 != len(functions):
                self.write(" ")
        self.write("))\n")
        self.dedent()

    def write_globals(self, ptr: int) -> int:
        for global_id, globl in self.globals.items():
            self.write_indent()
            size = globl.taip.size()
            lives_in_memory = globl.was_reffed or not globl.taip.can_live_in_reg()
            initial_value = ptr if lives_in_memory else 0
            taip = "i64" if not lives_in_memory and size > 4 and size <= 8 else "i32"
            self.write(f"(global ${globl.name.lexeme}:{global_id.module} {taip if lives_in_memory else f"(mut {taip})"} ({taip}.const {initial_value}))\n")
            if not lives_in_memory:
                continue
            ptr += globl.taip.size()
        return ptr

    def write_data(self, data: bytes) -> None:
        self.write_indent()
        self.write("(data (i32.const 0) \"")
        def escape_char(char: int) -> str:
            if char == b"\\"[0]:
               return "\\\\"
            if char == b"\""[0]:
                return "\\\""
            if char == b"\t"[0]:
               return "\\t"
            if char == b"\r"[0]:
               return "\\r"
            if char == b"\n"[0]:
               return "\\n"
            if char >= 32 and char <= 126:
               return chr(char)
            hex_digits = "0123456789abcdef"
            return f"\\{hex_digits[char >> 4]}{hex_digits[char & 15]}"
        for char in data:
            self.write(escape_char(char))
        self.write("\")\n")

    def write_extern(self, module_id: int, extern: Extern) -> None:
        self.write_indent()
        self.write("(import ")
        self.write(extern.extern_module)
        self.write(" ")
        self.write(extern.extern_name)
        self.write(" (")
        self.write_signature(module_id, extern.name, None, extern.signature, None, {})
        self.write("))")

    def write_type(self, taip: Type) -> None:
        size = taip.size()
        if size > 4 and size <= 8:
            self.write("i64")
        else:
            self.write("i32")
