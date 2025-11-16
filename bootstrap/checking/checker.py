from typing import List, Dict, Tuple, NoReturn, Sequence, assert_never
from dataclasses import dataclass
import os
import copy
import sys

from util import seq_eq
import format
from format import Formattable, Formatter
from indexed_dict import IndexedDict
from lexer import Token
from parsing.types import I8, I32, I64, Bool
import resolving as resolved
from resolving.top_items import LocalName, FromSource, FunctionSignature, Import, Extern, TypeDefinition, Struct, Variant, Global
from resolving.types import GenericType, HoleType, NamedType, Type, PtrType, CustomTypeType, FunctionType, with_generics
from resolving.type_resolver import TypeLookup
from resolving.words import NumberWord, BreakWord, ROOT_SCOPE, IntrinsicType
from resolving.intrinsics import INTRINSIC_TO_LEXEME
import resolving.type_without_holes as without_holes
import parsing.parser as parser
from checking.intrinsics import IntrinsicShr, IntrinsicEqual, IntrinsicStore, IntrinsicNot, IntrinsicUninit, IntrinsicSetStackSize, IntrinsicRotr, IntrinsicGreater, IntrinsicGreaterEq, IntrinsicLess, IntrinsicLessEq, IntrinsicNotEqual, IntrinsicFlip, IntrinsicMemFill, IntrinsicAdd, IntrinsicSub, IntrinsicDiv, IntrinsicDrop, IntrinsicMemGrow, IntrinsicMod, IntrinsicMul, IntrinsicAnd, IntrinsicOr, IntrinsicShl, IntrinsicWord, IntrinsicRotl, IntrinsicMemCopy
from checking.words import Word, FunctionHandle, InitWord, RefWord, GetLocal, CallWord, SizeofWord, UnnamedStructWord, StructWord, FunRefWord, StoreWord, LoadWord, MatchCase, MatchWord, VariantWord, LoopWord, CastWord, GetFieldWord, IfWord, SetWord, BlockWord, IndirectCallWord, FieldAccess, Scope, ScopeId, GlobalId, LocalId, StructFieldInitWord
from checking.stack import Stack

@dataclass
class Local(Formattable):
    name: LocalName
    taip: Type
    is_parameter: bool
    was_reffed: bool = False
    def format(self, fmt: Formatter):
        fmt.unnamed_record("Local", [self.name, self.taip, self.is_parameter])

@dataclass
class Function(Formattable):
    name: Token
    export_name: Token | None
    signature: FunctionSignature
    body: Scope
    locals: Dict[LocalId, Local]
    def format(self, fmt: Formatter):
        fmt.named_record("Function", [
            ("name", self.name),
            ("export", format.Optional(self.export_name)),
            ("signature", self.signature),
            ("locals", format.Dict(dict((k,v) for k,v in self.locals.items()))),
            ("body", self.body)])


@dataclass
class CheckException(Exception):
    path: str
    token: Token
    message: str

    def display(self) -> str:
        line = self.token.line
        column = self.token.column
        return f"{self.path}:{line}:{column} {self.message}"

@dataclass
class Module(Formattable):
    path: str
    id: int
    imports: Dict[str, Tuple[Import, ...]]
    type_definitions: IndexedDict[str, TypeDefinition]
    globals: IndexedDict[str, Global]
    functions: IndexedDict[str, Function | Extern]
    data: bytes

    def format(self, fmt: Formatter):
        fmt.named_record("Module", [
            ("imports", format.Dict(dict((format.Str(k),v) for k,v in self.imports.items()))),
            ("type-definitions", format.Seq(list(self.type_definitions.values()), multi_line=True)),
            ("globals", format.Seq(list(self.globals.values()), multi_line=True)),
            ("functions", format.Seq(list(self.functions.values()), multi_line=True))])

def determine_compilation_order(modules: Dict[str, parser.Module]) -> IndexedDict[str, parser.Module]:
    unprocessed: IndexedDict[str, parser.Module] = IndexedDict.from_items(modules.items())
    ordered: IndexedDict[str, parser.Module] = IndexedDict()
    while len(unprocessed) > 0:
        i = 0
        while i < len(unprocessed):
            postpone = False
            module_path,module = list(unprocessed.items())[i]
            for imp in module.imports:
                if os.path.dirname(module_path) != "":
                    path = os.path.normpath(os.path.dirname(module_path) + "/" + imp.file_path.lexeme[1:-1])
                else:
                    path = os.path.normpath(imp.file_path.lexeme[1:-1])
                if "./"+path not in ordered.keys():
                    postpone = True
                    break
            if postpone:
                i += 1
                continue
            ordered[module_path] = module
            unprocessed.delete(i)
    return ordered

@dataclass
class BreakStack(Formattable):
    token: Token
    types: Tuple[Type, ...]
    reachable: bool
    def format(self, fmt: Formatter):
        fmt.named_record("BreakStack", [
            ("token", self.token),
            ("types", format.Seq(self.types, True)),
            ("reachable", self.reachable)])

@dataclass
class BlockAnnotation:
    parameters: Tuple[Type, ...]
    returns: Tuple[Type, ...]

@dataclass
class CheckCtx:
    resolved_modules: IndexedDict[str, resolved.Module]
    checked_modules: IndexedDict[str, Module]
    signatures: List[FunctionSignature]
    globals: IndexedDict[str, resolved.Global]
    type_lookup: TypeLookup
    module_id: int

    def abort(self, token: Token, message: str) -> NoReturn:
        raise CheckException(self.resolved_modules.index_key(self.module_id), token, message)

    @property
    def module(self) -> resolved.Module:
        return self.resolved_modules.index(self.module_id)
    def generic_arguments_mismatch_error(self, token: Token, expected: int, actual: int):
        msg = f"expected {expected} generic arguments, not {actual}"
        self.abort(token, msg)

    def check_functions(
        self,
    ) -> IndexedDict[str, Function | Extern]:
        functions: IndexedDict[str, Function | Extern] = IndexedDict()
        for function in self.module.functions.values():
            if isinstance(function, resolved.Function):
                signature = function.signature
                stack = Stack.empty()
                locals = {
                    local_id: Local(local.name, without_holes.with_holes(local.parameter), True, False)
                    for local_id,local in function.locals.items()
                    if local.parameter is not None
                }
                ctx = WordCtx(
                    self,
                    locals,
                    self.type_lookup,
                    self.signatures,
                    self.globals,
                )
                words, diverges = ctx.check_words(stack, function.body.id, list(function.body.words))
                if not diverges and not seq_eq(stack.stack, without_holes.types_with_holes(signature.returns)):
                    msg  = "unexpected return values:\n\texpected: "
                    msg += self.type_lookup.types_pretty_bracketed(without_holes.types_with_holes(signature.returns))
                    msg += "\n\tactual:   "
                    msg += self.type_lookup.types_pretty_bracketed(stack.stack)
                    self.abort(function.name, msg)
                functions[function.name.lexeme] = Function(
                    function.name,
                    function.export_name,
                    signature,
                    Scope(function.body.id, words),
                    locals
                )
                continue
            if isinstance(function, resolved.Extern):
                functions[function.name.lexeme] = function
                continue
        return functions

type Env = Dict[LocalId, Local]

@dataclass
class WordCtx:
    ctx: CheckCtx
    env: Dict[LocalId, Local]
    type_lookup: TypeLookup
    signatures: List[FunctionSignature]
    globals: IndexedDict[str, Global]
    break_stacks: List[BreakStack] | None = None
    block_returns: Tuple[Type, ...] | None = None
    reachable: bool = True
    scope = ROOT_SCOPE
    struct_literal_ctx: Tuple[Type, ...] | None = None

    def with_break_stacks(self, break_stacks: List[BreakStack], block_returns: Tuple[Type, ...] | None) -> 'WordCtx':
        new = copy.copy(self)
        new.break_stacks = break_stacks
        new.block_returns = block_returns
        return new

    def with_scope(self, scope: ScopeId) -> 'WordCtx':
        new = copy.copy(self)
        new.scope = scope
        return new

    def with_struct_literal_ctx(self, fields: Tuple[Type, ...]) -> 'WordCtx':
        new = copy.copy(self)
        new.struct_literal_ctx = fields
        return new

    def abort(self, token: Token, message: str) -> NoReturn:
        self.ctx.abort(token, message)

    def check_words(self, stack: Stack, scope: ScopeId, remaining_words: List[resolved.Word]) -> Tuple[List[Word], bool]:
        ctx = self.with_scope(scope)
        diverges = False
        resolved: List[Word] = []
        while len(remaining_words) != 0:
            resolved_word = remaining_words.pop(0)
            res = ctx.check_word(stack, remaining_words, resolved_word)
            if res is None:
                continue
            resolved_words,word_diverges = res
            diverges = diverges or word_diverges
            ctx.reachable = not diverges
            resolved.extend(resolved_words)
        return (resolved, diverges)

    def check_word(self, stack: Stack, remaining_words: List[resolved.Word], word: resolved.Word) -> Tuple[List[Word], bool] | None:
        if isinstance(word, NumberWord):
            stack.push(I32())
            return ([word], False)
        if isinstance(word, resolved.words.StringWord):
            stack.push(PtrType(I8()))
            stack.push(I32())
            return ([word], False)
        if isinstance(word, resolved.words.GetLocal):
            return self.check_get_local(stack, word)
        if isinstance(word, resolved.words.RefLocal):
            return self.check_ref_local(stack, word)
        if isinstance(word, resolved.words.InitLocal):
            return self.check_init_local(stack, word)
        if isinstance(word, resolved.words.CallWord):
            return self.check_call(stack, word)
        if isinstance(word, resolved.words.CastWord):
            return self.check_cast(stack, word)
        if isinstance(word, resolved.words.SizeofWord):
            return self.check_sizeof(stack, word)
        if isinstance(word, resolved.words.StructWord):
            return self.check_make_struct(stack, word)
        if isinstance(word, resolved.words.StructWordNamed):
            return self.check_make_struct_named(stack, word)
        if isinstance(word, resolved.words.FunRefWord):
            return self.check_fun_ref(stack, word)
        if isinstance(word, resolved.words.IfWord):
            return self.check_if(stack, remaining_words, word)
        if isinstance(word, resolved.words.LoopWord):
            return self.check_loop(stack, word)
        if isinstance(word, BreakWord):
            return self.check_break(stack, word.token)
        if isinstance(word, resolved.words.SetLocal):
            return self.check_set_local(stack, word)
        if isinstance(word, resolved.words.BlockWord):
            return self.check_block(stack, word)
        if isinstance(word, resolved.words.IndirectCallWord):
            return self.check_indirect_call(stack, word)
        if isinstance(word, resolved.words.StoreWord):
            return self.check_store(stack, word)
        if isinstance(word, resolved.words.LoadWord):
            return self.check_load(stack, word)
        if isinstance(word, resolved.words.MatchWord):
            return self.check_match(stack, word)
        if isinstance(word, resolved.words.MatchVoidWord):
            return self.check_match_void(stack, word)
        if isinstance(word, resolved.words.VariantWord):
            return self.check_make_variant(stack, word)
        if isinstance(word, resolved.words.GetFieldWord):
            return self.check_get_field(stack, word)
        if isinstance(word, resolved.words.StackAnnotation):
            self.check_stack_annotation(stack, word)
            return None
        if isinstance(word, resolved.words.IntrinsicWord):
            return ([self.check_intrinsic(word.token, stack, word.ty, word.generic_arguments)], False)
        if isinstance(word, resolved.words.StructFieldInitWord):
            assert(self.struct_literal_ctx is not None)
            self.expect(stack, word.name, (self.struct_literal_ctx[word.field_index],))
            return ([StructFieldInitWord(word.name, word.field_index)], False)
        assert_never(word)

    def check_get_local(self, stack: Stack, word: resolved.words.GetLocal) -> Tuple[List[Word], bool]:
        if isinstance(word.var, resolved.GlobalId):
            taip = without_holes.with_holes(self.globals.index(word.var.index).taip)
        else:
            taip = self.env[word.var].taip
        fields = self.resolve_field_accesses(taip, word.fields)
        resolved_type = taip if len(fields) == 0 else fields[-1].target_taip
        stack.push(resolved_type)
        return ([GetLocal(word.name, word.var, taip, fields, resolved_type)], False)

    def check_ref_local(self, stack: Stack, word: resolved.words.RefLocal) -> Tuple[List[Word], bool]:
        if isinstance(word.var, resolved.GlobalId):
            globl = self.globals.index(word.var.index)
            def set_reffed():
                globl.was_reffed = True
            taip = without_holes.with_holes(globl.taip)
        else:
            local = self.env[word.var]
            def set_reffed():
                local.was_reffed = True
            taip = local.taip
        fields = self.resolve_field_accesses(taip, word.fields)

        i = 0
        while True:
            if i == len(word.fields):
                set_reffed()
                break
            if isinstance(fields[i].source_taip, PtrType):
                break
            i += 1

        result_type = taip if len(fields) == 0 else fields[-1].target_taip
        stack.push(PtrType(result_type))
        return ([RefWord(word.name, word.var, fields)], False)

    def check_init_local(self, stack: Stack, word: resolved.words.InitLocal) -> Tuple[List[Word], bool]:
        taip = stack.pop()
        if taip is None:
            print(word.name, file=sys.stderr)
        assert(taip is not None)
        self.env[word.local_id] = Local(FromSource(word.name), taip, False, False)
        return ([InitWord(word.name, word.local_id, taip)], False)

    def check_call(self, stack: Stack, word: resolved.words.CallWord) -> Tuple[List[Word], bool]:
        checked_word = self.check_call_word(word)
        signature = self.lookup_signature(word.function)
        args = stack.pop_n(len(signature.parameters))
        generic_arguments = self.infer_generic_arguments_from_args(word.name, args, without_holes.named_types_with_holes(signature.parameters), checked_word.generic_arguments)
        if generic_arguments is None:
            self.abort(word.name, "failed to infer generic arguments")
        checked_word.generic_arguments = generic_arguments
        self.push_returns(stack, without_holes.types_with_holes(signature.returns), checked_word.generic_arguments)
        return ([checked_word], False)

    def parameter_argument_mismatch_error(self, token: Token, arguments: Sequence[Type], parameters: Sequence[NamedType], generic_arguments: Sequence[Type]) -> NoReturn:
        self.type_mismatch_error(
                token,
                [self.insert_generic_arguments(generic_arguments, parameter.taip) for parameter in parameters],
                arguments)

    def infer_generic_arguments_from_args(self, token: Token, arguments: Sequence[Type], parameters: Sequence[NamedType], original_arguments: Tuple[Type, ...]) -> Tuple[Type, ...] | None:
        generic_arguments = list(original_arguments)
        hole_mapping: Dict[Token, Type] = {}
        for i in range(1, len(parameters) + 1):
            if len(arguments) < i:
                self.parameter_argument_mismatch_error(token, arguments, parameters, generic_arguments)
            parameter = parameters[-i].taip
            argument = arguments[-i]
            parameter = self.insert_generic_arguments(generic_arguments, parameter)
            if not self.infer_holes(hole_mapping, token, argument, parameter):
                self.parameter_argument_mismatch_error(token, arguments, parameters, generic_arguments)

        for (i, generic_argument) in enumerate(generic_arguments):
            generic_arguments[i] = self.fill_holes(hole_mapping, generic_argument)

        # TODO: check that the generic arguments don't contain any holes now
        # if any(taip.contains_hole() for taip in generic_arguments):
        #     return None
        return tuple(generic_arguments)


    def infer_holes(self, mapping: Dict[Token, Type], token: Token, actual: Type, holey: Type) -> bool:
        assert not isinstance(actual, HoleType)
        match holey:
            case HoleType(hole):
                if hole in mapping and mapping[hole] != actual:
                    msg = "Failed to infer type for hole, contradicting types inferred:\n"
                    msg += f"inferred now:        {self.type_lookup.type_pretty(actual)}\n"
                    msg += f"inferred previously: {self.type_lookup.type_pretty(mapping[hole])}\n"
                    self.abort(hole, msg)
                mapping[hole] = actual
                return True
            case Bool() | I8() | I32() | I64():
                return actual == holey
            case GenericType():
                return isinstance(actual, GenericType) and actual.generic_index == holey.generic_index
            case PtrType(holey):
                if not isinstance(actual, PtrType):
                    return False
                return self.infer_holes(mapping, token, actual.child, holey)
            case FunctionType():
                if not isinstance(actual, FunctionType):
                    return False
                return self.infer_holes_all(mapping, token, actual.parameters, holey.parameters) and self.infer_holes_all(mapping, token, actual.returns, holey.returns)
            case CustomTypeType():
                if not isinstance(actual, CustomTypeType):
                    return False
                if actual.type_definition != holey.type_definition:
                    return False
                return self.infer_holes_all(mapping, token, actual.generic_arguments, holey.generic_arguments)

    def infer_holes_all(self, mapping: Dict[Token, Type], token: Token, actual: Sequence[Type], holey: Sequence[Type]) -> bool:
        assert(len(actual) == len(holey))
        actuals_correct = True
        for (actual_t, holey_t) in zip(actual, holey):
            actuals_correct &= self.infer_holes(mapping, token, actual_t, holey_t)
        return actuals_correct


    def fill_holes(self, mapping: Dict[Token, Type], taip: Type) -> Type:
        match taip:
            case HoleType(hole):
                if hole not in mapping:
                    self.abort(hole, "failed to infer type for hole")
                return mapping[hole]
            case PtrType(child):
                return PtrType(self.fill_holes(mapping, child))
            case FunctionType(token, parameters, returns):
                return FunctionType(
                    token,
                    tuple(self.fill_holes(mapping, t) for t in parameters),
                    tuple(self.fill_holes(mapping, t) for t in returns))
            case CustomTypeType(name, type_definition, generic_arguments):
                return CustomTypeType(name, type_definition, tuple(self.fill_holes(mapping, t) for t in generic_arguments))
            case other:
                return other

    def push_returns(self, stack: Stack, returns: Sequence[Type], generic_arguments: Tuple[Type, ...] | None):
        for ret in returns:
            if generic_arguments is None:
                stack.push(ret)
            else:
                stack.push(self.insert_generic_arguments(generic_arguments, ret))

    def check_call_word(self, word: resolved.words.CallWord) -> CallWord:
        signature = self.lookup_signature(word.function)
        if len(signature.generic_parameters) != len(word.generic_arguments):
            self.ctx.generic_arguments_mismatch_error(word.name, len(signature.generic_parameters), len(word.generic_arguments))
        return CallWord(word.name, word.function, word.generic_arguments)

    def check_cast(self, stack: Stack, word: resolved.words.CastWord) -> Tuple[List[Word], bool]:
        src = stack.pop()
        if src is None:
            self.abort(word.token, "cast expected a value, got []")
        stack.push(word.dst)
        return ([CastWord(word.token, src, word.dst)], False)

    def check_sizeof(self, stack: Stack, word: resolved.words.SizeofWord) -> Tuple[List[Word], bool]:
        stack.push(I32())
        return ([SizeofWord(word.token, word.taip)], False)

    def check_make_struct(self, stack: Stack, word: resolved.words.StructWord) -> Tuple[List[Word], bool]:
        struct = self.type_lookup.lookup(word.taip.type_definition)
        assert(not isinstance(struct, Variant))
        args = stack.pop_n(len(struct.fields))
        generic_arguments = self.infer_generic_arguments_from_args(word.token, args, struct.fields, word.taip.generic_arguments)
        if generic_arguments is None:
            self.abort(word.token, "failed to infer generic arguments")
        taip = CustomTypeType(word.taip.name, word.taip.type_definition, generic_arguments)
        stack.push(taip)
        return ([UnnamedStructWord(word.token, taip)], False)

    def check_make_struct_named(self, stack: Stack, word: resolved.words.StructWordNamed) -> Tuple[List[Word], bool]:
        struct = self.type_lookup.lookup(word.taip.type_definition)
        if isinstance(struct, Variant):
            self.abort(word.token, "can only make struct types, not variants")
        fields = tuple(with_generics(field.taip, word.taip.generic_arguments) for field in struct.fields)
        words,diverges = self.with_struct_literal_ctx(fields).check_words(stack, word.body.id, list(word.body.words))
        stack.push(word.taip)
        return ([StructWord(word.token, word.taip, Scope(word.body.id, words))], diverges)

    def check_fun_ref(self, stack: Stack, word: resolved.words.FunRefWord) -> Tuple[List[Word], bool]:
        call = self.check_call_word(word.call)
        signature = self.lookup_signature(call.function)
        parameters = tuple(with_generics(without_holes.with_holes(param.taip), word.call.generic_arguments) for param in signature.parameters)
        returns = tuple(with_generics(without_holes.with_holes(ret), word.call.generic_arguments) for ret in signature.returns)
        stack.push(FunctionType(call.name, parameters, returns))
        return ([FunRefWord(call)], False)

    def check_if(self, stack: Stack, remaining_words: List[resolved.words.Word], word: resolved.words.IfWord) -> Tuple[List[Word], bool]:
        if not isinstance(stack.pop(), Bool):
            self.abort(word.token, "expected a bool for `if`")
        true_stack = stack.make_child()

        false_stack = stack.make_child()

        true_words, true_words_diverge = self.check_words(true_stack, word.true_branch.id, list(word.true_branch.words))
        true_parameters = true_stack.negative

        if true_words_diverge and (word.false_branch is None or len(word.false_branch.words) == 0):
            remaining_stack = stack.make_child()
            remaining_stack.use(len(true_parameters))

            checked_remaining_words,remaining_words_diverge = self.check_words(
                    remaining_stack, self.scope, remaining_words)

            stack.drop_n(len(remaining_stack.negative))
            stack.push_many(remaining_stack.stack)

            diverges = remaining_words_diverge
            return ([IfWord(
                word.token,
                tuple(remaining_stack.negative),
                None if diverges else tuple(remaining_stack.stack),
                Scope(word.true_branch.id, true_words),
                Scope(word.false_branch.id, checked_remaining_words),
                diverges)], diverges)
        false_words, false_words_diverge = self.check_words(
                false_stack,
                word.false_branch.id,
                [] if word.false_branch is None else list(word.false_branch.words))
        if not true_words_diverge and not false_words_diverge:
            if not true_stack.compatible_with(false_stack):
                msg  = "stack mismatch between if and else branch:\n\tif   "
                msg += self.type_lookup.types_pretty_bracketed(true_stack.stack)
                msg += "\n\telse "
                msg += self.type_lookup.types_pretty_bracketed(false_stack.stack)
                self.abort(word.token, msg)
            parameters = list(true_stack.negative)
        else:
            # TODO: Check, that the parameters of both branches are compatible
            parameters = true_stack.negative if len(true_stack.negative) > len(false_stack.negative) else false_stack.negative

        parameters.reverse()

        if not true_words_diverge:
            returns = tuple(true_stack.stack)
        elif not false_words_diverge:
            returns = tuple(false_stack.stack)
        else:
            returns = None

        param_count = max(len(true_stack.negative), len(false_stack.negative))
        if true_words_diverge and false_words_diverge:
            stack.drop_n(param_count)
        else:
            self.expect(stack, word.token, parameters)
            if returns is not None:
                stack.push_many(returns)

        diverges = true_words_diverge and false_words_diverge
        return ([IfWord(
            word.token,
            tuple(parameters),
            returns,
            Scope(word.true_branch.id, true_words),
            Scope(word.false_branch.id, false_words),
            diverges)], diverges)

    def check_loop(self, stack: Stack, word: resolved.words.LoopWord) -> Tuple[List[Word], bool]:
        loop_break_stacks: List[BreakStack] = []

        loop_stack = stack.make_child()
        loop_ctx = self.with_break_stacks(
                loop_break_stacks,
                None if word.annotation is None else word.annotation.returns)

        words,_ = loop_ctx.check_words(loop_stack, word.body.id, list(word.body.words))
        diverges = len(loop_break_stacks) == 0
        parameters = tuple(loop_stack.negative) if word.annotation is None else word.annotation.parameters

        if len(loop_break_stacks) != 0:
            first = loop_break_stacks[0]
            diverges = not first.reachable
            for break_stack in loop_break_stacks[1:]:
                if not break_stack.reachable:
                    break
                if first.types != break_stack.types:
                    self.break_stack_mismatch_error(word.token, loop_break_stacks)

        if not seq_eq(parameters, loop_stack.stack):
            self.abort(word.token, "unexpected values remaining on stack at the end of loop")

        if word.annotation is not None:
            returns = word.annotation.returns
        elif len(loop_break_stacks) != 0:
            returns = loop_break_stacks[0].types
        else:
            returns = tuple(loop_stack.stack)

        self.expect(stack, word.token, parameters)
        stack.push_many(returns)
        body = Scope(word.body.id, words)
        return ([LoopWord(word.token, body, parameters, returns, diverges)], diverges)

    def check_break(self, stack: Stack, token: Token) -> Tuple[List[Word], bool]:
        if self.block_returns is None:
            dump = stack.dump()
        else:
            dump = stack.pop_n(len(self.block_returns))

        if self.break_stacks is None:
            self.abort(token, "`break` can only be used inside of blocks and loops")

        self.break_stacks.append(BreakStack(token, tuple(dump), self.reachable))
        return ([BreakWord(token)], True)

    def check_set_local(self, stack: Stack, word: resolved.words.SetLocal) -> Tuple[List[Word], bool]:
        if isinstance(word.var, GlobalId):
            taip = without_holes.with_holes(self.globals.index(word.var.index).taip)
        else:
            local = self.env[word.var]
            taip = local.taip
        fields = self.resolve_field_accesses(taip, word.fields)
        if len(fields) == 0:
            resolved_type = taip
        else:
            resolved_type = fields[-1].target_taip
        self.expect(stack, word.name, [resolved_type])
        return ([SetWord(word.name, word.var, fields)], False)

    def check_block(self, stack: Stack, word: resolved.words.BlockWord) -> Tuple[List[Word], bool]:
        block_break_stacks: List[BreakStack] = []

        block_stack = stack.make_child()
        block_ctx = self.with_break_stacks(
                block_break_stacks,
                None if word.annotation is None else word.annotation.returns)

        words, diverges = block_ctx.check_words(block_stack, word.body.id, list(word.body.words))
        block_end_is_reached = not diverges

        parameters = tuple(block_stack.negative) if word.annotation is None else word.annotation.parameters
        if len(block_break_stacks) != 0:
            first = block_break_stacks[0]
            diverges = not first.reachable
            for break_stack in block_break_stacks[1:]:
                if not break_stack.reachable:
                    diverges = True
                    break
                if first.types != break_stack.types:
                    if block_end_is_reached:
                        block_break_stacks.append(BreakStack(word.end, tuple(block_stack.stack), diverges))
                    self.break_stack_mismatch_error(word.token, block_break_stacks)
            if block_end_is_reached:
                if not seq_eq(block_stack.stack, first.types):
                    block_break_stacks.append(BreakStack(word.end, tuple(block_stack.stack), diverges))
                    self.break_stack_mismatch_error(word.token, block_break_stacks)

        if word.annotation is not None:
            returns = word.annotation.returns
        elif len(block_break_stacks) != 0:
            returns = block_break_stacks[0].types
        else:
            returns = tuple(block_stack.stack)

        self.expect(stack, word.token, parameters)
        stack.push_many(returns)
        body = Scope(word.body.id, words)
        return ([BlockWord(word.token, body, parameters, returns)], diverges)

    def check_indirect_call(self, stack: Stack, word: resolved.words.IndirectCallWord) -> Tuple[List[Word], bool]:
        fun_type = stack.pop()
        if fun_type is None:
            self.abort(word.token, "`->` expected a function on the stack, got: []")
        if not isinstance(fun_type, FunctionType):
            self.abort(word.token, "TODO")
        self.expect(stack, word.token, fun_type.parameters)
        self.push_returns(stack, fun_type.returns, None)
        fun_type = FunctionType(word.token, fun_type.parameters, fun_type.returns)
        return ([IndirectCallWord(word.token, fun_type)], False)

    def check_store(self, stack: Stack, word: resolved.words.StoreWord) -> Tuple[List[Word], bool]:
        if isinstance(word.var, GlobalId):
            globl = self.globals.index(word.var.index)
            taip = without_holes.with_holes(globl.taip)
        else:
            local = self.env[word.var]
            taip = local.taip
        fields = self.resolve_field_accesses(taip, word.fields)
        expected_type = taip if len(fields) == 0 else fields[-1].target_taip
        if not isinstance(expected_type, PtrType):
            self.abort(word.name, "`=>` can only store into ptr types")
        expected_type = expected_type.child
        self.expect(stack, word.name, [expected_type])
        return ([StoreWord(word.name, word.var, fields)], False)

    def check_load(self, stack: Stack, word: resolved.words.LoadWord) -> Tuple[List[Word], bool]:
        taip = stack.pop()
        if taip is None:
            self.abort(word.token, "`~` expected a ptr, got: []")
        if not isinstance(taip, PtrType):
            msg = f"`~` expected a ptr, got: [{taip}]"
            self.abort(word.token, msg)
        stack.push(taip.child)
        return ([LoadWord(word.token, taip.child)], False)

    def check_match_void(self, stack: Stack, word: resolved.words.MatchVoidWord) -> Tuple[List[Word], bool]:
        arg_item = stack.pop()
        if arg_item is None:
            self.abort(word.token, "expected a value to match on")
        arg = arg_item.child if isinstance(arg_item, PtrType) else arg_item
        if not isinstance(arg, CustomTypeType):
            self.abort(word.token, "can only match on variants")
        variant = self.type_lookup.lookup(arg.type_definition)
        if not isinstance(variant, Variant):
            self.abort(word.token, "can only match on variants")
        if len(variant.cases) != 0:
            self.abort(word.token, "expected variant with zero cases")
        return ([word], True)


    def check_match(self, stack: Stack, word: resolved.words.MatchWord) -> Tuple[List[Word], bool]:
        match_diverges = True
        arg_item = stack.pop()
        if arg_item is None:
            self.abort(word.token, "expected a value to match on")
        by_ref = isinstance(arg_item, PtrType)
        arg = arg_item.child if isinstance(arg_item, PtrType) else arg_item
        if not isinstance(arg, CustomTypeType):
            self.abort(word.token, "can only match n variants")
        generic_arguments = arg.generic_arguments
        variant_type = arg
        variant = self.type_lookup.lookup(arg.type_definition)
        if not isinstance(variant, Variant):
            self.abort(word.token, "can only match on variants")

        if word.variant != arg.type_definition:
            self.abort(word.token, f"match argument mismatch.\nExpected to match on:\n\t{self.type_lookup.lookup(word.variant).name.lexeme}\nbut got:\n\t{variant.name.lexeme}")

        remaining_cases: List[str] = [case.name.lexeme for case in variant.cases]
        case_stacks: List[Tuple[Stack, Token, bool]] = []
        visited_cases: List[Token] = []
        cases: List[MatchCase] = []
        for resolved_case in word.cases:
            tag: int | None = resolved_case.tag
            for j, variant_case in enumerate(variant.cases):
                if tag is not None:
                    break
                if variant_case.name.lexeme == resolved_case.name.lexeme:
                    tag = j
            if tag is None:
                self.abort(resolved_case.name, "not part of variant")

            case_type = variant.cases[tag].taip
            case_stack = stack.make_child()
            if case_type is not None:
                if by_ref:
                    case_type = PtrType(case_type)
                case_type = self.insert_generic_arguments(generic_arguments, case_type)
                case_stack.push(case_type)

            words, case_diverges = self.check_words(case_stack, resolved_case.body.id, list(resolved_case.body.words))
            match_diverges = match_diverges and case_diverges
            cases.append(MatchCase(case_type, tag, Scope(resolved_case.body.id, words)))

            if resolved_case.name.lexeme not in remaining_cases:
                other = next(token for token in visited_cases if token.lexeme == resolved_case.name.lexeme)
                msg  = "duplicate case in match:"
                msg += f"\n\t{other.line}:{other.column} {other.lexeme}"
                msg += f"\n\t{resolved_case.name.line}:{resolved_case.name.column} {resolved_case.name.lexeme}"
                self.abort(word.token, msg)

            remaining_cases.remove(resolved_case.name.lexeme)

            case_stacks.append((case_stack, resolved_case.name, case_diverges))
            visited_cases.append(resolved_case.name)

        if word.default is None:
            if len(remaining_cases) != 0:
                msg = "missing case in match:"
                for case in remaining_cases:
                    msg += f"\n\t{case}"
                self.abort(word.token, msg)
            default_case = None
        else:
            def_stack = stack.make_child()
            def_stack.push(arg_item)
            words, default_diverges = self.check_words(def_stack, word.default.body.id, list(word.default.body.words))
            match_diverges = match_diverges and default_diverges
            case_stacks.append((def_stack, word.default.underscore, default_diverges))
            default_case = Scope(word.default.body.id, words)

        first_non_diverging_case: Stack | None = None
        for case_stack,case_token,case_diverges in case_stacks:
            if not case_diverges:
                if first_non_diverging_case is None:
                    first_non_diverging_case = case_stack
                elif not first_non_diverging_case.compatible_with(case_stack):
                    msg = "arms of match case have different types:"
                    for case_stack, case_token, case_diverges in case_stacks:
                        msg += f"\n\t{self.type_lookup.types_pretty_bracketed(case_stack.negative)}"
                        if case_diverges:
                            msg += " -> <diverges>"
                        else:
                            msg += f" -> {self.type_lookup.types_pretty_bracketed(case_stack.stack)}"
                        msg += f" in case {case_token.lexeme}"
                    self.abort(word.token, msg)

        if len(case_stacks) == 0:
            returns: List[Type] | None = []
            parameters = []
        else:
            most_params = case_stacks[0][0]
            for case_stack,_,_ in case_stacks[1:]:
                if len(case_stack.negative) > len(most_params.negative):
                    most_params = case_stack

            parameters = list(most_params.negative)
            parameters.reverse()

            returns = list(parameters)
            for case_stack,_,case_diverges in case_stacks:
                if not case_diverges:
                    del returns[len(returns) - len(case_stack.negative):]
                    returns.extend(case_stack.stack)
                    break

        self.expect(stack, word.token, parameters)
        stack.push_many(returns or [])
        if match_diverges:
            returns = None
        match_word = MatchWord(
                word.token,
                variant_type,
                by_ref,
                tuple(cases),
                default_case,
                tuple(parameters),
                tuple(returns) if returns is not None else None)
        return ([match_word], match_diverges)

    def check_make_variant(self, stack: Stack, word: resolved.words.VariantWord) -> Tuple[List[Word], bool]:
        variant = self.type_lookup.lookup(word.variant.type_definition)
        assert(isinstance(variant, Variant))
        case = variant.cases[word.tag]
        if case.taip is not None:
            expected = self.insert_generic_arguments(word.variant.generic_arguments, case.taip)
            self.expect(stack, word.token, [expected])
        stack.push(word.variant)
        return ([VariantWord(word.token, word.tag, word.variant)], False)

    def check_get_field(self, stack: Stack, word: parser.GetFieldWord) -> Tuple[List[Word], bool]:
        taip = stack.pop()
        if taip is None:
            self.abort(word.token, "expected a value on the stack")
        fields = self.resolve_field_accesses(taip, word.fields)
        on_ptr = isinstance(taip, PtrType)
        taip = fields[-1].target_taip
        taip = PtrType(taip) if on_ptr else taip
        stack.push(taip)
        return ([GetFieldWord(word.token, fields, on_ptr)], False)

    def stack_annotation_mismatch(self, stack: Stack, annotation: resolved.words.StackAnnotation) -> NoReturn:
        expected = annotation.types
        msg = "Stack doesn't match annotation:\n"
        msg += "  actual:   ["
        if len(stack) > len(expected) + 1:
            msg += "..., "
        actual = stack.pop_n(len(expected) + 1)
        msg += self.type_lookup.types_pretty(actual)
        msg += "]\n"
        msg += "  expected: "
        msg += self.type_lookup.types_pretty_bracketed(expected)
        msg += "\n"
        self.abort(annotation.token, msg)

    def check_stack_annotation(self, stack: Stack, word: resolved.words.StackAnnotation) -> None:
        if len(stack) < len(word.types):
            self.stack_annotation_mismatch(stack, word)
        for i, expected in enumerate(reversed(word.types)):
            if stack[-i-1] != expected:
                self.stack_annotation_mismatch(stack, word)
        return None

    def expect_arguments(self, stack: Stack, token: Token, generic_arguments: Tuple[Type, ...], parameters: List[NamedType]):
        i = len(parameters)
        popped: List[Type] = []
        while i != 0:
            expected_type = self.insert_generic_arguments(generic_arguments, parameters[i - 1].taip)
            popped_type = stack.pop()
            error = popped_type is None or popped_type != expected_type
            if popped_type is not None:
                popped.append(popped_type)
            if error:
                while True:
                    popped_type = stack.pop()
                    if popped_type is None:
                        break
                    popped.append(popped_type)
                expected = [self.insert_generic_arguments(generic_arguments, parameter.taip) for parameter in parameters]
                popped.reverse()
                self.type_mismatch_error(token, expected, popped)
            assert(popped_type is not None)
            i -= 1

    def expect(self, stack: Stack, token: Token, expected: Sequence[Type]):
        i = len(expected)
        popped: List[Type] = []
        while i != 0:
            expected_type = expected[i - 1]
            popped_type = stack.pop()
            error = popped_type is None or popped_type != expected_type
            if error:
                popped.reverse()
                self.type_mismatch_error(token, expected, popped)
            assert(popped_type is not None)
            popped.append(popped_type)
            i -= 1

    def type_mismatch_error(self, token: Token, expected: Sequence[Type], actual: Sequence[Type]) -> NoReturn:
        message  = "expected:\n\t" + self.type_lookup.types_pretty_bracketed(expected)
        message += "\ngot:\n\t" + self.type_lookup.types_pretty_bracketed(actual)
        self.abort(token, message)

    def check_intrinsic(self, token: Token, stack: Stack, intrinsic: IntrinsicType, generic_arguments: Tuple[Type, ...]) -> IntrinsicWord:
        match intrinsic:
            case IntrinsicType.ADD | IntrinsicType.SUB:
                if len(stack) < 2:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected two items on stack")
                taip = stack[-2]
                if isinstance(taip, PtrType):
                    narrow_type: PtrType | I8 | I32 | I64 = taip
                    if not isinstance(stack[-1], I32):
                        self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected [.a, i32]")
                    stack.pop()
                elif isinstance(taip, I8):
                    narrow_type = I8()
                    popped = self.expect_stack(token, stack, [I8(), I8()])
                    stack.append(taip)
                elif isinstance(taip, I32):
                    narrow_type = I32()
                    popped = self.expect_stack(token, stack, [I32(), I32()])
                    stack.append(taip)
                elif isinstance(taip, I64):
                    narrow_type = I64()
                    self.expect_stack(token, stack, [I64(), I64()])
                    stack.append(taip)
                else:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]} cannot add to {self.type_lookup.type_pretty(taip)}")
                if intrinsic == IntrinsicType.ADD:
                    return IntrinsicAdd(token, narrow_type)
                if intrinsic == IntrinsicType.SUB:
                    return IntrinsicSub(token, narrow_type)
            case IntrinsicType.DROP:
                dropped_taip = stack.pop()
                if dropped_taip is None:
                    self.abort(token, "`drop` expected non empty stack")
                return IntrinsicDrop(token, dropped_taip)
            case IntrinsicType.MOD | IntrinsicType.MUL | IntrinsicType.DIV:
                if len(stack) < 2:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected two items on stack")
                taip = stack[-2]
                if isinstance(taip, I32):
                    narrow_type = I32()
                    popped = self.expect_stack(token, stack, [I32(), I32()])
                elif isinstance(taip, I64):
                    narrow_type = I64()
                    popped = self.expect_stack(token, stack, [I64(), I64()])
                else:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected [i32, i32] or [i64, i64] on stack")
                stack.append(taip)
                if intrinsic == IntrinsicType.MOD:
                    return IntrinsicMod(token, narrow_type)
                if intrinsic == IntrinsicType.MUL:
                    return IntrinsicMul(token, narrow_type)
                if intrinsic == IntrinsicType.DIV:
                    return IntrinsicDiv(token, narrow_type)
            case IntrinsicType.AND | IntrinsicType.OR:
                if len(stack) < 2:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected two items on stack")
                taip = stack[-1]
                match taip:
                    case I8():
                        popped = self.expect_stack(token, stack, [I8(), I8()])
                    case I32():
                        popped = self.expect_stack(token, stack, [I32(), I32()])
                    case I64():
                        popped = self.expect_stack(token, stack, [I64(), I64()])
                    case Bool():
                        popped = self.expect_stack(token, stack, [Bool(), Bool()])
                    case _:
                        self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` can only and i8, i32, i64 and bool")
                stack.append(popped[0])
                if intrinsic == IntrinsicType.AND:
                    return IntrinsicAnd(token, taip)
                if intrinsic == IntrinsicType.OR:
                    return IntrinsicOr(token, taip)
            case IntrinsicType.SHR | IntrinsicType.SHL | IntrinsicType.ROTR | IntrinsicType.ROTL:
                if len(stack) < 2:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected two items on stack")
                taip = stack[-2]
                if isinstance(taip, I8):
                    popped = self.expect_stack(token, stack, [I8(), I8()])
                elif isinstance(taip, I32):
                    popped = self.expect_stack(token, stack, [I32(), I32()])
                else:
                    popped = self.expect_stack(token, stack, [I64(), I64()])
                stack.append(popped[0])
                if intrinsic == IntrinsicType.SHL:
                    return IntrinsicShl(token, taip)
                if intrinsic == IntrinsicType.SHR:
                    return IntrinsicShr(token, taip)
                if intrinsic == IntrinsicType.ROTR:
                    return IntrinsicRotr(token, taip)
                if intrinsic == IntrinsicType.ROTL:
                    return IntrinsicRotl(token, taip)
            case IntrinsicType.GREATER | IntrinsicType.LESS | IntrinsicType.GREATER_EQ | IntrinsicType.LESS_EQ:
                if len(stack) < 2:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected two items on stack")
                taip = stack[-1]
                if isinstance(taip, I8):
                    narrow_type = I8()
                    self.expect_stack(token, stack, [I8(), I8()])
                elif isinstance(taip, I32):
                    narrow_type = I32()
                    self.expect_stack(token, stack, [I32(), I32()])
                elif isinstance(taip, I64):
                    narrow_type = I64()
                    self.expect_stack(token, stack, [I64(), I64()])
                else:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected [i8, i8] or [i32, i32] or [i64, i64] on stack")
                stack.append(Bool())
                if intrinsic == IntrinsicType.GREATER:
                    return IntrinsicGreater(token, narrow_type)
                if intrinsic == IntrinsicType.LESS:
                    return IntrinsicLess(token, narrow_type)
                if intrinsic == IntrinsicType.GREATER_EQ:
                    return IntrinsicGreaterEq(token, narrow_type)
                if intrinsic == IntrinsicType.LESS_EQ:
                    return IntrinsicLessEq(token, narrow_type)
            case IntrinsicType.MEM_COPY:
                self.expect_stack(token, stack, [PtrType(I8()), PtrType(I8()), I32()])
                return IntrinsicMemCopy(token)
            case IntrinsicType.MEM_FILL:
                self.expect_stack(token, stack, [PtrType(I8()), I8(), I32()])
                return IntrinsicMemFill(token)
            case IntrinsicType.NOT_EQ | IntrinsicType.EQ:
                if len(stack) < 2:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected two items on stack")
                if stack[-1] != stack[-2]:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected [a, a] for any a")
                taip = stack[-1]
                stack.pop()
                stack.pop()
                stack.append(Bool())
                if intrinsic == IntrinsicType.EQ:
                    return IntrinsicEqual(token, taip)
                if intrinsic == IntrinsicType.NOT_EQ:
                    return IntrinsicNotEqual(token, taip)
            case IntrinsicType.FLIP:
                a = stack.pop()
                b = stack.pop()
                if a is None or b is None:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected two items on stack")
                stack.push_many([a, b])
                return IntrinsicFlip(token, b, a)
            case IntrinsicType.MEM_GROW:
                self.expect_stack(token, stack, [I32()])
                stack.append(I32())
                return IntrinsicMemGrow(token)
            case IntrinsicType.STORE:
                if len(stack) < 2:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected two items on stack")
                ptr_type = stack[-2]
                if not isinstance(ptr_type, PtrType) or ptr_type.child != stack[-1]:
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected [.a, a]")
                taip = stack[-1]
                stack.pop()
                stack.pop()
                return IntrinsicStore(token, taip)
            case IntrinsicType.NOT:
                taip = stack[-1]
                if len(stack) == 0 or (not isinstance(taip, I64) and not isinstance(taip, I32) and not isinstance(taip, Bool)):
                    self.abort(token, f"`{INTRINSIC_TO_LEXEME[intrinsic]}` expected an i64, i32 or bool on the stack")
                return IntrinsicNot(token, taip)
            case IntrinsicType.UNINIT:
                if len(generic_arguments) != 1:
                    self.abort(token, "uninit only accepts one generic argument")
                stack.append(generic_arguments[0])
                return IntrinsicUninit(token, generic_arguments[0])
            case IntrinsicType.SET_STACK_SIZE:
                self.expect_stack(token, stack, [I32()])
                return IntrinsicSetStackSize(token)
        assert_never(intrinsic)

    def expect_stack(self, token: Token, stack: Stack, expected: List[Type]) -> List[Type]:
        popped: List[Type] = []
        def abort() -> NoReturn:
            stackdump = stack.dump() + list(reversed(popped))
            self.abort(token, f"expected:\n\t{self.type_lookup.types_pretty_bracketed(expected)}\ngot:\n\t{self.type_lookup.types_pretty_bracketed(stackdump)}")
        for expected_type in reversed(expected):
            top = stack.pop()
            if top is None:
                abort()
            popped.append(top)
            if expected_type != top:
                abort()
        return list(reversed(popped))

    def break_stack_mismatch_error(self, token: Token, break_stacks: List[BreakStack]):
        msg = "break stack mismatch:"
        for break_stack in break_stacks:
            msg += f"\n\t{break_stack.token.line}:{break_stack.token.column} {self.type_lookup.types_pretty_bracketed(break_stack.types)}"
        self.abort(token, msg)

    def lookup_signature(self, function: FunctionHandle) -> FunctionSignature:
        if function.module == self.ctx.module_id:
            return self.signatures[function.index]
        return self.ctx.resolved_modules.index(function.module).functions.index(function.index).signature

    def resolve_field_accesses(self, taip: Type, fields: Sequence[Token]) -> Tuple[FieldAccess, ...]:
        resolved = []
        if len(fields) == 0:
            return ()
        for field_name in fields:
            assert((isinstance(taip, PtrType) and isinstance(taip.child, CustomTypeType)) or isinstance(taip, CustomTypeType))
            unpointered = taip.child if isinstance(taip, PtrType) else taip
            assert(isinstance(unpointered, CustomTypeType))
            custom_type: CustomTypeType = unpointered
            type_definition = self.type_lookup.lookup(custom_type.type_definition)
            if isinstance(type_definition, Variant):
                self.abort(field_name, "variants do not have fields")
            struct: Struct = type_definition
            found_field = False
            for field_index,struct_field in enumerate(struct.fields):
                if struct_field.name.lexeme == field_name.lexeme:
                    target_type = self.insert_generic_arguments(custom_type.generic_arguments, struct_field.taip)
                    resolved.append(FieldAccess(field_name, taip, target_type, field_index))
                    taip = target_type
                    found_field = True
                    break
            if not found_field:
                self.abort(field_name, "field not found")
        return tuple(resolved)

    def insert_generic_arguments(self, generics: Sequence[Type], taip: Type) -> Type:
        if isinstance(taip, PtrType):
            return PtrType(self.insert_generic_arguments(generics, taip.child))
        if isinstance(taip, CustomTypeType):
            return CustomTypeType(taip.name, taip.type_definition, self.insert_generic_arguments_all(generics, taip.generic_arguments))
        if isinstance(taip, FunctionType):
            return FunctionType(
                taip.token,
                self.insert_generic_arguments_all(generics, taip.parameters),
                self.insert_generic_arguments_all(generics, taip.returns),
            )
        if isinstance(taip, GenericType):
            return generics[taip.generic_index]
        return taip

    def insert_generic_arguments_all(self, generics: Sequence[Type], types: Sequence[Type]) -> Tuple[Type, ...]:
        return tuple(self.insert_generic_arguments(generics, taip) for taip in types)
