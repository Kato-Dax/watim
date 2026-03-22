from typing import Sequence, Tuple, Literal, assert_never
from dataclasses import dataclass

from indexed_dict import IndexedDict
import format

from monomorphization import (
        Local,
        LocalId, GlobalId,
        Word,
        CustomTypeType, PtrType,
        Variant, Struct,
        field_offset,
        TypeId,
        can_live_in_reg,
        Bool, I8, I32, I64,
        local_lives_in_memory,
        global_lives_in_memory,
        I32_ID,
)
import monomorphization as mono

from codegen.ctx import Ctx
from codegen.common import (
        type_size,
        generate_type_pretty,
        generate_flip_i32_i32,
        generate_flip_i64_i32,
        generate_flip_i32_i64,
        generate_flip_i64_i64,
        generate_store,
        generate_var_ident,
        generate_type,
        generate_dup_i64,
        generate_dup_i32,
        generate_returns,
        generate_parameters_unnamed,
)

def generate_words(ctx: Ctx, module: int, locals: IndexedDict[LocalId, Local], words: Sequence[Word]):
    for word in words:
        generate_word(ctx, module, locals, word)

def generate_word(ctx: Ctx, module: int, locals: IndexedDict[LocalId, Local], word: Word):
    ctx.fmt.write_indent()
    match word:
        case mono.Uninit():
            size = type_size(ctx.program.sizes, word.type)
            if size <= 4:
                ctx.fmt.write("i32.const 0")
            elif size <= 8:
                ctx.fmt.write("i64.const 0")
            else:
                ctx.fmt.write("local.get $locl-copy-spac:e i32.const ")
                ctx.fmt.write(word.copy_space_offset)
                ctx.fmt.write(" i32.add")
        case mono.Number():
            ctx.fmt.write(f"i32.const {word.token.lexeme}")
        case mono.MakeStruct():
            generate_make_struct(ctx, word)
        case mono.Drop():
            ctx.fmt.write("drop")
        case mono.Call():
            generate_call(ctx, word)
        case mono.String():
            ctx.fmt.write(f"i32.const {ctx.module_data_offsets[module] + word.offset} i32.const {word.len}")
        case mono.InitLocal():
            var_lives_in_memory = local_lives_in_memory(ctx.program.sizes, locals[word.local])
            generate_set(ctx, locals, word.local, word.type, var_lives_in_memory, ())
        case mono.GetLocal():
            generate_get_local(ctx, locals, word)
        case mono.SetLocal():
            match word.var:
                case LocalId():
                    var_lives_in_memory = local_lives_in_memory(ctx.program.sizes, locals[word.var])
                case GlobalId():
                    var_lives_in_memory = global_lives_in_memory(ctx.program.sizes, ctx.program.lookup_global(word.var))
            target_lives_in_memory = var_lives_in_memory or fields_go_through_ptr(ctx, word.fields)
            loads = determine_loads(ctx, word.fields, target_lives_in_memory, var_lives_in_memory)
            generate_set(ctx, locals, word.var, word.type, target_lives_in_memory, loads)
        case mono.RefLocal():
            loads = determine_loads(ctx, word.fields, True, False)
            match word.var:
                case LocalId():
                    ctx.fmt.write("local.get ")
                case GlobalId():
                    ctx.fmt.write("global.get ")
                case other:
                    assert_never(other)
            generate_var_ident(ctx, locals, word.var)
            generate_loads(ctx, loads)
        case mono.Eq():
            if type_size(ctx.program.sizes, word.taip) > 4:
                ctx.fmt.write("i64.eq")
            else:
                ctx.fmt.write("i32.eq")
        case mono.NotEq():
            if type_size(ctx.program.sizes, word.taip) > 4:
                ctx.fmt.write("i64.ne")
            else:
                ctx.fmt.write("i32.ne")
        case mono.MatchVoid():
            ctx.fmt.write(";; match on variant {}\n").write_indent()
            ctx.fmt.write("unreachable")
        case mono.MakeStructNamed():
            custom_type_handle = ctx.lookup_type(word.type)
            assert isinstance(custom_type_handle, CustomTypeType)
            struct = ctx.lookup_type_definition(custom_type_handle.handle)
            assert not isinstance(struct, Variant)
            size = type_size(ctx.program.sizes, word.type)
            if size == 0:
                for _ in struct.fields:
                    ctx.fmt.write("drop ")
                ctx.fmt.write("i32.const 0 ;; make ")
                generate_type_pretty(ctx, word.type)
            else:
                ctx.fmt.write(";; make ")
                generate_type_pretty(ctx, word.type)
                ctx.fmt.write("\n")
                ctx.fmt.indent()
                generate_words(ctx, module, locals, word.body.words)
                ctx.fmt.dedent()
                ctx.fmt.write_indent()
                ctx.fmt.write(f"local.get $locl-copy-spac:e i32.const {word.copy_space_offset} i32.add ")
                if size <= 4:
                    ctx.fmt.write("i32.load ")
                elif size <= 8:
                    ctx.fmt.write("i64.load ")
                ctx.fmt.write(";; make ")
                generate_type_pretty(ctx, word.type)
                ctx.fmt.write(" end")
        case mono.FieldInit():
            ctx.fmt.write(f"local.get $locl-copy-spac:e i32.const {word.copy_space_offset} i32.add ")
            size = type_size(ctx.program.sizes, word.type)
            if size <= 4 or size > 8:
                generate_flip_i32_i32(ctx)
            else:
                generate_flip_i64_i32(ctx)
            ctx.fmt.write(" ")
            generate_store(ctx, word.type)
        case mono.MakeVariant():
            custom_type_handle = ctx.lookup_type(word.type)
            assert isinstance(custom_type_handle, CustomTypeType)
            variant = ctx.lookup_type_definition(custom_type_handle.handle)
            assert not isinstance(variant, Struct)
            case = variant.cases[word.tag]
            variant_size = type_size(ctx.program.sizes, word.type)

            if variant_size <= 4:
                assert variant_size == 4
                if case.taip is not None:
                    ctx.fmt.write("drop ")
                ctx.fmt.write(f"i32.const {word.tag} ;; store tag {variant.name.lexeme}.{case.name.lexeme}")
            elif variant_size <= 8:
                if case.taip is None:
                    ctx.fmt.write(f"i64.const {word.tag} ;; make ")
                else:
                    ctx.fmt.write("i64.extend_i32_u i64.const 32 i64.shl ;; store value\n").write_indent()
                    ctx.fmt.write(f"i64.const {word.tag} ;; store tag\n").write_indent()
                    ctx.fmt.write("i64.or ;; make ")
                ctx.fmt.write(f"{variant.name.lexeme}.{case.name.lexeme}")
            else:
                ctx.fmt.write(f"local.get $locl-copy-spac:e i32.const {word.copy_space_offset} i32.add i32.const {word.tag} i32.store ;; store tag\n")
                if case.taip is not None:
                    case_type_size = type_size(ctx.program.sizes, case.taip)
                    ctx.fmt.write_indent()
                    ctx.fmt.write(f"local.get $locl-copy-spac:e i32.const {word.copy_space_offset + 4} i32.add ")
                    if case_type_size > 4 and case_type_size <= 8:
                        generate_flip_i64_i32(ctx)
                    else:
                        generate_flip_i32_i32(ctx)
                    ctx.fmt.write(" ")
                    generate_store(ctx, case.taip)
                    ctx.fmt.write(" ;; store value\n")
                ctx.fmt.write_indent()
                ctx.fmt.write(f"local.get $locl-copy-spac:e i32.const {word.copy_space_offset} i32.add ;; make {variant.name.lexeme}.{case.name.lexeme}")
            pass
        case mono.Match():
            custom_type_handle = ctx.lookup_type(word.type)
            assert isinstance(custom_type_handle, CustomTypeType)
            variant = ctx.lookup_type_definition(custom_type_handle.handle)
            assert not isinstance(variant, Struct)
            variant_size = type_size(ctx.program.sizes, word.type)
            ctx.fmt.write(f";; match on {variant.name.lexeme}\n").write_indent()
            for i, match_case in enumerate(word.cases):
                if variant_size > 8 or word.by_ref:
                    ctx.fmt.write("call $intrinsic:dupi32 i32.load ")
                elif variant_size > 4:
                    generate_dup_i64(ctx)
                    ctx.fmt.write(" i32.wrap_i64 ")
                else:
                    generate_dup_i32(ctx)
                    ctx.fmt.write(" ")
                ctx.fmt.write(f"i32.const {match_case.tag} i32.eq (if")
                generate_parameters_unnamed(ctx, word.parameters)
                variant_inhabits_i64 = variant_size <= 8 and variant_size > 4 and not word.by_ref
                if variant_inhabits_i64:
                    ctx.fmt.write(" (param i64)")
                else:
                    ctx.fmt.write(" (param i32)")
                if word.returns is not None:
                    generate_returns(ctx, word.returns)
                ctx.fmt.write("\n").write_indent()
                ctx.fmt.write("(then\n").indent()
                if match_case.type is None:
                    ctx.fmt.write_indent()
                    ctx.fmt.write("drop\n")
                else:
                    case_type_size = type_size(ctx.program.sizes, match_case.type)
                    if case_type_size != 0:
                        ctx.fmt.write_indent()
                        if word.by_ref or variant_size > 8:
                            ctx.fmt.write("i32.const 4 i32.add")
                            if not word.by_ref and case_type_size <= 8:
                                ctx.fmt.write(" ")
                                generate_type(ctx, match_case.type)
                                ctx.fmt.write(".load")
                        else:
                            ctx.fmt.write("i64.const 32 i64.shr_u i32.wrap_i64")
                        ctx.fmt.write("\n")
                    else:
                        if variant_inhabits_i64:
                            ctx.fmt.write_indent()
                            ctx.fmt.write("i32.wrap_i64\n")

                generate_words(ctx, module, locals, match_case.body.words)
                ctx.fmt.dedent()
                ctx.fmt.write_indent()
                ctx.fmt.write(")\n")
                ctx.fmt.write_indent()
                if i + 1 == len(word.cases) and word.default is not None:
                    ctx.fmt.write("(else\n").indent()
                else:
                    ctx.fmt.write("(else ")

            if word.default is not None:
                generate_words(ctx, module, locals, word.default.words)
                ctx.fmt.dedent()
                ctx.fmt.write_indent()
            else:
                if len(word.cases) != 0:
                    ctx.fmt.write("unreachable")
            for _ in word.cases:
                ctx.fmt.write("))")
            if word.returns is None:
                if len(word.cases) != 0 or word.default is not None:
                    ctx.fmt.write("\n").write_indent()
                ctx.fmt.write("unreachable")
        case mono.If():
            ctx.fmt.write("(if")
            generate_parameters_unnamed(ctx, word.parameters)
            if word.returns is not None:
                generate_returns(ctx, word.returns)
            ctx.fmt.write("\n").indent()
            ctx.fmt.write_indent()
            ctx.fmt.write("(then\n")
            ctx.fmt.indent()
            generate_words(ctx, module, locals, word.true_branch.words)
            ctx.fmt.dedent()
            ctx.fmt.write_indent()
            ctx.fmt.write(")\n")
            if len(word.false_branch.words) != 0:
                ctx.fmt.write_indent()
                ctx.fmt.write("(else\n").indent()
                generate_words(ctx, module, locals, word.false_branch.words)
                ctx.fmt.dedent()
                ctx.fmt.write_indent()
                ctx.fmt.write(")\n")
            ctx.fmt.dedent()
            ctx.fmt.write_indent()
            ctx.fmt.write(")")
            if word.returns is None:
                ctx.fmt.write("\n")
                ctx.fmt.write_indent()
                ctx.fmt.write("unreachable")
        case mono.Loop():
            ctx.fmt.write("(block $block ")
            generate_parameters_unnamed(ctx, word.parameters)
            if word.returns is not None:
                generate_returns(ctx, word.returns)
            ctx.fmt.write("\n")
            ctx.fmt.indent()
            ctx.fmt.write_indent()
            ctx.fmt.write("(loop $loop ")
            generate_parameters_unnamed(ctx, word.parameters)
            if word.returns is not None:
                generate_returns(ctx, word.returns)
            ctx.fmt.write("\n").indent()
            generate_words(ctx, module, locals, word.body.words)
            ctx.fmt.write_indent()
            ctx.fmt.write("br $loop\n")
            ctx.fmt.dedent()
            ctx.fmt.write_indent()
            ctx.fmt.write(")\n")
            ctx.fmt.dedent()
            ctx.fmt.write_indent()
            ctx.fmt.write(")")
            if word.returns is None:
                ctx.fmt.write("\n").write_indent()
                ctx.fmt.write("unreachable")
        case mono.Block():
            ctx.fmt.write("(block $block")
            generate_parameters_unnamed(ctx, word.parameters)
            if word.returns is not None:
                generate_returns(ctx, word.returns)
            ctx.fmt.write("\n")
            ctx.fmt.indent()
            generate_words(ctx, module, locals, word.body.words)
            ctx.fmt.dedent()
            ctx.fmt.write_indent()
            ctx.fmt.write(")")
        case mono.Break():
            ctx.fmt.write("br $block")
        case mono.Add():
            match ctx.lookup_type(word.type):
                case I64():
                    ctx.fmt.write("i64.add")
                case _:
                    ctx.fmt.write("i32.add")
        case mono.Sub():
            match ctx.lookup_type(word.taip):
                case I64():
                    ctx.fmt.write("i64.sub")
                case _:
                    ctx.fmt.write("i32.sub")
        case mono.Mul():
            match ctx.lookup_type(word.taip):
                case I8() | I32():
                    ctx.fmt.write("i32.mul")
                case I64():
                    ctx.fmt.write("i64.mul")
                case _:
                    assert False
        case mono.Cast():
            src_size = type_size(ctx.program.sizes, word.src)
            dst_size = type_size(ctx.program.sizes, word.dst)
            if src_size == dst_size:
                ctx.fmt.write(";; cast to ")
                generate_type_pretty(ctx, word.dst)
            elif src_size <= 4 and dst_size > 4 and dst_size <= 8:
                ctx.fmt.write("i64.extend_i32_u ;; cast to ")
                generate_type_pretty(ctx, word.dst)
            elif src_size > 4 and src_size <= 8 and dst_size <= 4:
                ctx.fmt.write("i32.wrap_i64 ;; cast to ")
                generate_type_pretty(ctx, word.dst)
            elif src_size <= 4 and dst_size == 1:
                ctx.fmt.write("i32.const 0xFF i32.and ;; cast to ")
                generate_type_pretty(ctx, word.dst)
            elif src_size <= 4 and dst_size <= 4 and dst_size >= src_size:
                ctx.fmt.write(";; cast to ")
                generate_type_pretty(ctx, word.dst)
            elif isinstance(ctx.lookup_type(word.dst), I64) and can_live_in_reg(ctx.program.sizes, word.src):
                ctx.fmt.write("i64.extend_i32_s")
            else:
                ctx.fmt.write("UNSUPPORTED Cast from ")
                generate_type_pretty(ctx, word.src)
                ctx.fmt.write(" to ")
                generate_type_pretty(ctx, word.dst)
        case mono.Load():
            match ctx.lookup_type(word.type):
                case I8():
                    ctx.fmt.write("i32.load8_u")
                case I32():
                    ctx.fmt.write("i32.load")
                case I64():
                    ctx.fmt.write("i64.load")
                case Bool():
                    ctx.fmt.write("i32.load")
                case _:
                    if can_live_in_reg(ctx.program.sizes, word.type):
                        generate_type(ctx, word.type)
                        ctx.fmt.write(".load")
                    else:
                        ctx.fmt.write(f"local.get $locl-copy-spac:e i32.const {word.copy_space_offset}")
                        ctx.fmt.write(f" i32.add call $intrinsic:dupi32 call $intrinsic:rotate-left i32.const {type_size(ctx.program.sizes, word.type)}")
                        ctx.fmt.write(" memory.copy")
        case mono.Ge():
            match ctx.lookup_type(word.taip):
                case I8():
                    ctx.fmt.write("i32.ge_u")
                case I32():
                    ctx.fmt.write("i32.ge_u")
                case I64():
                    ctx.fmt.write("i64.ge_u")
                case _:
                    assert False
        case mono.Le():
            match ctx.lookup_type(word.taip):
                case I8():
                    ctx.fmt.write("i32.le_u")
                case I32():
                    ctx.fmt.write("i32.le_u")
                case I64():
                    ctx.fmt.write("i64.le_u")
                case _:
                    assert False
        case mono.Gt():
            match ctx.lookup_type(word.taip):
                case I8():
                    ctx.fmt.write("i32.gt_u")
                case I32():
                    ctx.fmt.write("i32.gt_u")
                case I64():
                    ctx.fmt.write("i64.gt_u")
                case _:
                    assert False
        case mono.Lt():
            match ctx.lookup_type(word.taip):
                case I8():
                    ctx.fmt.write("i32.lt_u")
                case I32():
                    ctx.fmt.write("i32.lt_u")
                case I64():
                    ctx.fmt.write("i64.lt_u")
                case _:
                    assert False
        case mono.And():
            match ctx.lookup_type(word.taip):
                case I8():
                    ctx.fmt.write("i32.and")
                case I32():
                    ctx.fmt.write("i32.and")
                case I64():
                    ctx.fmt.write("i64.and")
                case Bool():
                    ctx.fmt.write("i32.and")
                case _:
                    assert False
        case mono.Or():
            match ctx.lookup_type(word.taip):
                case I8():
                    ctx.fmt.write("i32.or")
                case I32():
                    ctx.fmt.write("i32.or")
                case I64():
                    ctx.fmt.write("i64.or")
                case Bool():
                    ctx.fmt.write("i32.or")
                case _:
                    assert False
        case mono.Div():
            match ctx.lookup_type(word.taip):
                case I8():
                    ctx.fmt.write("i32.div_u")
                case I32():
                    ctx.fmt.write("i32.div_u")
                case I64():
                    ctx.fmt.write("i64.div_u")
                case _:
                    assert False
        case mono.Mod():
            match ctx.lookup_type(word.taip):
                case I8():
                    ctx.fmt.write("i32.rem_u")
                case I32():
                    ctx.fmt.write("i32.rem_u")
                case I64():
                    ctx.fmt.write("i64.rem_u")
                case _:
                    assert False
        case mono.Store():
            generate_store(ctx, word.taip)
        case mono.StoreLocal():
            match word.var:
                case LocalId():
                    ctx.fmt.write("local.get ")
                case GlobalId():
                    ctx.fmt.write("global.get ")
            generate_var_ident(ctx, locals, word.var)
            loads = determine_loads(ctx, word.fields, False, False)
            generate_loads(ctx, loads)
            ctx.fmt.write(" call $intrinsic:flip ")
            generate_store(ctx, word.type)
        case mono.MemGrow():
            ctx.fmt.write("memory.grow")
        case mono.MemFill():
            ctx.fmt.write("memory.fill")
        case mono.MemCopy():
            ctx.fmt.write("memory.copy")
        case mono.Sizeof():
            ctx.fmt.write(f"i32.const {type_size(ctx.program.sizes, word.type)}")
        case mono.Flip():
            lower_size = type_size(ctx.program.sizes, word.lower)
            upper_size = type_size(ctx.program.sizes, word.upper)
            lower_is_i32 = lower_size <= 4 or lower_size > 8
            upper_is_i32 = upper_size <= 4 or upper_size > 8
            if lower_is_i32 and upper_is_i32:
                generate_flip_i32_i32(ctx)
            elif lower_is_i32 and not upper_is_i32:
                generate_flip_i32_i64(ctx)
            elif not lower_is_i32 and upper_is_i32:
                generate_flip_i64_i32(ctx)
            else:
                assert not lower_is_i32 and not upper_is_i32
                generate_flip_i64_i64(ctx)
        case mono.Shl():
            if isinstance(ctx.lookup_type(word.taip), I64):
                ctx.fmt.write("i64.shl")
            else:
                ctx.fmt.write("i32.shl")
        case mono.Shr():
            if isinstance(ctx.lookup_type(word.taip), I64):
                ctx.fmt.write("i64.shr_u")
            else:
                ctx.fmt.write("i32.shr_u")
        case mono.Rotl():
            if isinstance(ctx.lookup_type(word.taip), I64):
                ctx.fmt.write("i64.rotl")
            else:
                ctx.fmt.write("i32.rotl")
        case mono.Rotr():
            if isinstance(ctx.lookup_type(word.taip), I64):
                ctx.fmt.write("i64.rotr")
            else:
                ctx.fmt.write("i32.rotr")
        case mono.IndirectCall():
            fun_type = ctx.lookup_type(word.type)
            assert isinstance(fun_type, mono.FunType)
            ctx.fmt.write("(call_indirect")
            generate_parameters_unnamed(ctx, fun_type.parameters)
            generate_returns(ctx, fun_type.returns)
            ctx.fmt.write(")")
            generate_return_receivers(ctx, word.copy_space_offset, fun_type.returns)
        case mono.Not():
            match ctx.lookup_type(word.taip):
                case I64():
                    ctx.fmt.write("i64.const -1 i64.xor")
                case I32():
                    ctx.fmt.write("i32.const -1 i32.xor")
                case I8():
                    ctx.fmt.write("i32.const -1 i32.xor i32.const 0xFF i32.and")
                case Bool():
                    ctx.fmt.write("i32.const 1 i32.xor i32.const 1 i32.and")
        case mono.FunRef():
            ctx.fmt.write(f"i32.const {word.table_index + 1}")
        case mono.GetField():
            loads = determine_loads(ctx, word.fields, word.on_ptr, False)
            if len(loads) == 0:
                ctx.fmt.write(";; GetField was no-op")
            else:
                target_type_can_live_in_reg = can_live_in_reg(ctx.program.sizes, word.type)
                if not word.on_ptr and not target_type_can_live_in_reg:
                    ctx.fmt.write(f"local.get $locl-copy-spac:e i32.const {word.copy_space_offset} i32.add call $intrinsic:dupi32 call $intrinsic:rotate-left")
                generate_loads(ctx, loads)
        case mono.SetStackSize():
            if ctx.guard_stack:
                ctx.fmt.write("global.set $stack-siz:e")
            else:
                ctx.fmt.write("drop")
        case other:
            assert_never(other)
    ctx.fmt.write("\n")

def fields_go_through_ptr(ctx: Ctx, fields: Sequence[mono.FieldAccess]) -> bool:
    for field in fields:
        if isinstance(ctx.lookup_type(field.source_type), PtrType):
            return True
    return False

@dataclass(frozen=True)
class Offset(format.Formattable):
    offset: int
    def format(self, fmt: format.Formatter):
        fmt.unnamed_record("Offset", [self.offset])

@dataclass(frozen=True)
class OffsetLoad(format.Formattable):
    type: TypeId
    offset: int
    def format(self, fmt: format.Formatter):
        fmt.unnamed_record("OffsetLoad", [self.type, self.offset])

@dataclass(frozen=True)
class BitShift(format.Formattable):
    type: Literal["I32InI64"] | Literal["I8InI32"] | Literal["I16InI32"] | Literal["I8InI64"]
    extra_offset: int
    def format(self, fmt: format.Formatter):
        fmt.unnamed_record(self.type, [self.extra_offset])

type Load = Offset | OffsetLoad | BitShift

def merge_loads(loads: Tuple[Load, ...]) -> Tuple[Load, ...]:
    if len(loads) <= 1:
        return loads
    first = loads[0]
    second = loads[1]
    rest = loads[2:]
    match first:
        case OffsetLoad():
            match second:
                case BitShift():
                    return (OffsetLoad(I32_ID, first.offset + second.extra_offset),) + rest
                case _:
                    return loads
        case Offset():
            match second:
                case Offset():
                    return (Offset(first.offset + second.offset),) + rest
                case OffsetLoad():
                    return (OffsetLoad(second.type, first.offset + second.offset),) + rest
                case _:
                    return loads
        case BitShift():
            if not isinstance(second, BitShift):
                return loads

            match first.type:
                case "I16InI32":
                    match second.type:
                        case "I8InI32":
                            return (BitShift("I8InI32", first.extra_offset + second.extra_offset),) + rest
                        case _:
                            return loads
                case _:
                    # TODO: merging of other configurations, for example:
                    #         [BitShift.I32InI64 4, BitShift.I8InI32 1] -> BitShift.I8InI64 5
                    return loads

def determine_loads(ctx: Ctx, fields: Tuple[mono.FieldAccess, ...], just_ref: bool, base_in_mem: bool) -> Tuple[Load, ...]:
    if len(fields) == 0:
        return ()
    field = fields[0]
    tail = fields[1:]

    source_type_size = type_size(ctx.program.sizes, field.source_type)
    type = ctx.lookup_type(field.source_type)
    match type:
        case CustomTypeType():
            struct = ctx.lookup_type_definition(type.handle)
            assert not isinstance(struct, Variant)
            offset = field_offset(ctx.program.sizes, struct, field.field_index)
            if base_in_mem or source_type_size > 8:
                if len(fields) > 1 or just_ref:
                    if offset == 0:
                        return determine_loads(ctx, tail, just_ref, True)
                    load: Load = Offset(offset)
                else:
                    load = OffsetLoad(field.target_type, offset)
                rest = determine_loads(ctx, tail, just_ref, True)
                return merge_loads((load,) + rest)
            target_type_size = type_size(ctx.program.sizes, field.target_type)
            if source_type_size > 4:
                if target_type_size == 1:
                    load = BitShift("I8InI64", offset)
                elif target_type_size == 4:
                    load = BitShift("I32InI64", offset)
                else:
                    assert False
                rest = determine_loads(ctx, tail, just_ref, base_in_mem)
                return merge_loads((load,) + rest)
            if source_type_size != target_type_size:
                rest = determine_loads(ctx, tail, just_ref, base_in_mem)
                if target_type_size == 1:
                    return merge_loads((BitShift("I8InI32", offset),) + rest)
                if target_type_size == 2:
                    return merge_loads((BitShift("I16InI32", offset),) + rest)
                assert False # TODO

            assert source_type_size == 4
            return determine_loads(ctx, tail, just_ref, base_in_mem)
        case PtrType():
            child = ctx.lookup_type(type.child)
            assert isinstance(child, CustomTypeType)
            struct = ctx.lookup_type_definition(child.handle)
            assert not isinstance(struct, Variant)
            offset = field_offset(ctx.program.sizes, struct, field.field_index)
            target_type_size = type_size(ctx.program.sizes, field.target_type)

            if (just_ref and len(fields) == 1) or (target_type_size > 8 and len(fields) != 1):
                if offset == 0:
                    return determine_loads(ctx, tail, just_ref, base_in_mem)
                else:
                    return merge_loads((Offset(offset),) + determine_loads(ctx, tail, just_ref, base_in_mem))
            else:
                return merge_loads((OffsetLoad(field.target_type, offset),) + determine_loads(ctx, tail, just_ref, base_in_mem))
        case _:
            assert False


def generate_get_local(
        ctx: Ctx,
        locals: IndexedDict[LocalId, Local],
        word: mono.GetLocal):
    result_can_live_in_reg = can_live_in_reg(ctx.program.sizes, word.result_type)
    if not result_can_live_in_reg:
        ctx.fmt.write("local.get $locl-copy-spac:e i32.const ")
        ctx.fmt.write(word.copy_space_offset)
        ctx.fmt.write(" i32.add call $intrinsic:dupi32 ")

    match word.var:
        case GlobalId():
            ctx.fmt.write("global.get $")
            globl = ctx.program.lookup_global(word.var)
            ctx.fmt.write(f"{globl.name.lexeme}:{word.var.module}")
            var_lives_in_memory = global_lives_in_memory(ctx.program.sizes, globl)
        case LocalId():
            ctx.fmt.write("local.get ")
            local = locals[word.var]
            generate_var_ident(ctx, locals, word.var)
            var_lives_in_memory = local_lives_in_memory(ctx.program.sizes, local)

    loads = determine_loads(ctx, word.fields, False, var_lives_in_memory)
    result_size = type_size(ctx.program.sizes, word.result_type)
    generate_loads(ctx, loads)
    if len(loads) == 0:
        if result_can_live_in_reg:
            if var_lives_in_memory:
                ctx.fmt.write(" ")
                generate_type(ctx, word.result_type)
                ctx.fmt.write(".load")
        else:
            ctx.fmt.write(f" i32.const {result_size} memory.copy")

def generate_loads(ctx: Ctx, loads: Sequence[Load]):
    for load in loads:
        ctx.fmt.write(" ")
        generate_load(ctx, load)

def generate_load(ctx: Ctx, load: Load):
    match load:
        case BitShift():
            match load.type:
                case "I8InI32":
                    if load.extra_offset != 0:
                        ctx.fmt.write(f"i32.const {load.extra_offset * 8} i32.shr_u ")
                    ctx.fmt.write("i32.const 0xFF i32.and")
                case "I16InI32":
                    if load.extra_offset != 0:
                        ctx.fmt.write(f"i32.const {load.extra_offset * 8} i32.shr_u ")
                    ctx.fmt.write("i32.const 0xFFFF i32.and")
                case "I32InI64":
                    if load.extra_offset != 0:
                        ctx.fmt.write(f"i64.const {load.extra_offset * 8} i64.shr_u ")
                    ctx.fmt.write("i32.wrap_i64")
                case "I8InI64":
                    if load.extra_offset != 0:
                        ctx.fmt.write(f"i64.const {load.extra_offset * 8} i64.shr_u ")
                    ctx.fmt.write("i32.wrap_i64 i32.const 0xFF i32.and")
                case other:
                    assert_never(other)
        case Offset():
            ctx.fmt.write(f"i32.const {load.offset} i32.add")
        case OffsetLoad():
            size = type_size(ctx.program.sizes, load.type)
            if size <= 8:
                if size == 1:
                    ctx.fmt.write("i32.load8_u")
                elif size <= 4:
                    ctx.fmt.write("i32.load")
                else:
                    ctx.fmt.write("i64.load")
                if load.offset != 0:
                    ctx.fmt.write(f" offset={load.offset}")
                return
            if load.offset == 0:
                ctx.fmt.write(f"i32.const {size} memory.copy")
                return
            ctx.fmt.write(f"i32.const {load.offset} i32.add i32.const {size} memory.copy")
        case other:
            assert_never(other)

def generate_set(
        ctx: Ctx,
        locals: IndexedDict[LocalId, Local],
        var: LocalId | GlobalId,
        target_type: TypeId,
        target_lives_in_memory: bool,
        loads: Tuple[Load, ...]):
    if len(loads) == 0 and not target_lives_in_memory:
        match var:
            case LocalId():
                ctx.fmt.write("local.set ")
            case GlobalId():
                ctx.fmt.write("global.set ")
        generate_var_ident(ctx, locals, var)
        return

    match var:
        case LocalId():
            ctx.fmt.write("local.get ")
        case GlobalId():
            ctx.fmt.write("global.get ")
    generate_var_ident(ctx, locals, var)

    target_type_size = type_size(ctx.program.sizes, target_type)
    if len(loads) == 0:
        ctx.fmt.write(" ")
        if target_type_size > 4 and target_type_size <= 8:
            generate_flip_i64_i32(ctx)
        else:
            generate_flip_i32_i32(ctx)
        ctx.fmt.write(" ")
        generate_store(ctx, target_type)
        return

    last_load = loads[-1]
    if not target_lives_in_memory and isinstance(last_load, BitShift):
        for i, load in enumerate(loads):
            if all(isinstance(load, BitShift) for load in loads[i + 1:]):
                break
            generate_load(ctx, load)

        match last_load.type:
            case "I32InI64":
                mask = ((1 << 64) - 1) ^ (((1 << 32) - 1) << (last_load.extra_offset * 8))
                ctx.fmt.write(f" i64.const 0x{mask:X} i64.and ")
            case "I8InI32":
                mask = ((1 << 32) - 1) ^ (((1 << 8) - 1) << (last_load.extra_offset * 8))
                ctx.fmt.write(f" i32.const 0x{mask:X} i32.and ")
            case "I16InI32":
                mask = ((1 << 32) - 1) ^ (((1 << 16) - 1) << (last_load.extra_offset * 8))
                ctx.fmt.write(f" i32.const 0x{mask:X} i32.and ")
            case "I8InI64":
                mask = ((1 << 64) - 1) ^ (((1 << 8) - 1) << (last_load.extra_offset * 8))
                ctx.fmt.write(f" i64.const 0x{mask:X} i64.and ")
            case other:
                assert_never(other)
        generate_flip_i32_i64(ctx)
        ctx.fmt.write(" i64.extend_i32_u ")
        match last_load.type:
            case "I8InI32":
                ty_name = "i32"
            case "I16InI32":
                ty_name = "i32"
            case "I8InI64":
                ty_name = "i64"
            case "I32InI64":
                ty_name = "i64"
            case other:
                assert_never(other)
        if last_load.extra_offset != 0:
            ctx.fmt.write(f"{ty_name}.const {last_load.extra_offset * 8} {ty_name}.shl ")
        ctx.fmt.write(f"{ty_name}.or ")

        match var:
            case LocalId():
                ctx.fmt.write("local.set ")
            case GlobalId():
                ctx.fmt.write("global.set ")
            case o:
                assert_never(o)
        generate_var_ident(ctx, locals, var)
        return

    generate_loads(ctx, loads)
    ctx.fmt.write(" ")
    if target_type_size > 4 and target_type_size <= 8:
        generate_flip_i64_i32(ctx)
    else:
        generate_flip_i32_i32(ctx)
    ctx.fmt.write(" ")
    generate_store(ctx, target_type)

def generate_call(ctx: Ctx, word: mono.Call):
    function = ctx.program.lookup_function(word.function)
    ctx.fmt.write(f"call ${word.function.module}:{function.name.lexeme}")
    if word.function.instance != 0:
        ctx.fmt.write(f":{word.function.instance}")
    generate_return_receivers(ctx, word.copy_space_offset, function.signature.returns)

def generate_return_receivers(ctx: Ctx, offset: int, returns: Tuple[TypeId, ...]):
    if all(can_live_in_reg(ctx.program.sizes, r) for r in returns):
        return
    ctx.fmt.write("\n")
    for i in range(len(returns), 0, -1):
        size = type_size(ctx.program.sizes, returns[i - 1])
        ctx.fmt.write_indent()
        ctx.fmt.write(f"local.set $s{i - 1}")
        if size > 4 and size <= 8:
            ctx.fmt.write(":8\n")
        else:
            ctx.fmt.write(":4\n")

    for i, ret in enumerate(returns):
        size = type_size(ctx.program.sizes, ret)
        ctx.fmt.write_indent()
        if size <= 4:
            ctx.fmt.write(f"local.get $s{i}:4")
        elif size <= 8:
            ctx.fmt.write(f"local.get $s{i}:8")
        else:
            ctx.fmt.write(f"local.get $locl-copy-spac:e i32.const {offset} i32.add call $intrinsic:dupi32 local.get $s{i}:4 ")
            ctx.fmt.write(f"i32.const {size} memory.copy")
            offset += size
        if i + 1 >= len(returns):
            break
        ctx.fmt.write("\n")

def generate_make_struct(ctx: Ctx, word: mono.MakeStruct):
    custom_type_handle = ctx.lookup_type(word.type)
    assert isinstance(custom_type_handle, CustomTypeType)
    struct = ctx.lookup_type_definition(custom_type_handle.handle)
    assert not isinstance(struct, Variant)
    size = type_size(ctx.program.sizes, word.type)

    if size <= 8:
        if size == 0:
            for _ in struct.fields:
                ctx.fmt.write("drop ")
            ctx.fmt.write("i32.const 0 ;; make ")
            generate_type_pretty(ctx, word.type)
            return
        if len(struct.fields) == 1:
            ctx.fmt.write(";; make ")
            generate_type_pretty(ctx, word.type)
            return
        for i in range(len(struct.fields), 0, -1):
            field_size = type_size(ctx.program.sizes, struct.fields[i - 1].taip)
            offset = field_offset(ctx.program.sizes, struct, i - 1)
            if i != len(struct.fields) and (offset != 0 or size > 4):
                if size <= 4:
                    generate_flip_i32_i32(ctx)
                else:
                    generate_flip_i32_i64(ctx)
                ctx.fmt.write(" ")
            if size > 4:
                ctx.fmt.write("i64.extend_i32_u ")
            if offset != 0:
                if size <= 4:
                    ctx.fmt.write(f"i32.const {offset * 8} i32.shl ")
                else:
                    ctx.fmt.write(f"i64.const {offset * 8} i64.shl ")

            if i != len(struct.fields):
                if size <= 4:
                    ctx.fmt.write("i32.or ")
                else:
                    ctx.fmt.write("i64.or ")
        ctx.fmt.write(";; make ")
        generate_type_pretty(ctx, word.type)
        return

    ctx.fmt.write(";; make ")
    generate_type_pretty(ctx, word.type)
    ctx.fmt.write("\n").indent()

    for i in range(len(struct.fields), 0, -1):
        field_index = i - 1
        field = struct.fields[field_index]
        field_size = type_size(ctx.program.sizes, field.taip)
        offset = field_offset(ctx.program.sizes, struct, field_index)
        ctx.fmt.write_indent()
        ctx.fmt.write(f"local.get $locl-copy-spac:e i32.const {word.copy_space_offset + offset} i32.add ")
        if field_size > 4 and field_size <= 8:
            generate_flip_i64_i32(ctx)
        else:
            generate_flip_i32_i32(ctx)
        ctx.fmt.write(" ")
        generate_store(ctx, field.taip)
        ctx.fmt.write("\n")
    ctx.fmt.dedent()
    ctx.fmt.write_indent()
    ctx.fmt.write(f"local.get $locl-copy-spac:e i32.const {word.copy_space_offset} i32.add ;; make ")
    generate_type_pretty(ctx, word.type)
    ctx.fmt.write(" end")


