from typing import Sequence, Tuple, Dict, NoReturn
from dataclasses import dataclass
import copy

from indexed_dict import IndexedDict

import parsing.words as parsing
from lexer import Token
from resolving.words import Word, IntrinsicWord, FunctionHandle, GlobalId
from resolving.module import Module, ResolveException
import resolving.words as resolved
from resolving.intrinsics import INTRINSICS
import resolving.type_without_holes as without_holes
import resolving.types as with_holes
from resolving.type_resolver import TypeResolver, TypeLookup
from resolving.top_items import Import, Local, SyntheticName, FromSource, CustomTypeHandle, Variant, Struct, Global, LocalId, FunctionSignature, VariantImport, Signature
from resolving.env import Env

@dataclass
class StructLiteralEnv:
    struct: CustomTypeHandle
    all_fields: Dict[str, int]
    remaining_fields: Dict[str, int]

    @staticmethod
    def of_struct(struct: Struct, handle: CustomTypeHandle) -> 'StructLiteralEnv':
        return StructLiteralEnv(
            handle,
            { field.name.lexeme: field_index for field_index, field in enumerate(struct.fields) },
            { field.name.lexeme: field_index for field_index, field in enumerate(struct.fields) })

@dataclass
class WordResolver:
    module_id: int
    module_path: str
    imports: Dict[str, Tuple[Import, ...]]
    globals: IndexedDict[str, Global]
    signatures: IndexedDict[str, FunctionSignature]
    type_resolver: TypeResolver
    modules: IndexedDict[str, Module]
    type_lookup: TypeLookup
    env: Env
    static_data: bytearray
    struct_literal_env: StructLiteralEnv | None = None
    is_in_block: bool = False

    def abort(self, token: Token, message: str) -> NoReturn:
        raise ResolveException(self.module_path, token, message)

    def with_env(self, env: Env) -> 'WordResolver':
        self = copy.copy(self)
        self.env = env
        return self

    def with_struct_literal_env(self, env: StructLiteralEnv) -> 'WordResolver':
        self = copy.copy(self)
        self.struct_literal_env = env
        return self

    def without_struct_literal_env(self) -> 'WordResolver':
        self = copy.copy(self)
        self.struct_literal_env = None
        return self

    def with_in_block(self) -> 'WordResolver':
        self = copy.copy(self)
        self.is_in_block = True
        return self

    def allocate_static_data(self, data: bytes) -> int:
        offset = self.static_data.find(data)
        if offset == -1:
            offset = len(self.static_data)
            self.static_data.extend(data)
        return offset

    def forbid_holes(self, taip: with_holes.Type) -> without_holes.Type:
        without = without_holes.without_holes(taip)
        if isinstance(without, Token):
            self.abort(without, "hole not allowed here")
        return without

    def lookup_signature(self, handle: FunctionHandle) -> Signature:
        if handle.module == self.module_id:
            return self.signatures.index(handle.index)
        else:
            return self.modules.index(handle.module).functions.index(handle.index).signature

    def resolve_words(self, words: Sequence[parsing.Word]) -> Tuple[Word, ...]:
        return tuple(resolved_word for word in words for resolved_word in self.resolve_word(word))

    def resolve_word(self, word: parsing.Word) -> Sequence[Word]:
        match word:
            case parsing.NumberWord():
                return word,
            case parsing.StringWord():
                offset = self.allocate_static_data(bytes(word.data))
                return resolved.StringWord(word.token, offset, len(word.data)),
            case parsing.BreakWord():
                if not self.is_in_block:
                    self.abort(word.token, "`break` can only be used inside of blocks and loops")
                return word,
            case parsing.CallWord():
                call = self.resolve_call(word)
                if call is None:
                    if word.ident.lexeme in INTRINSICS:
                        return IntrinsicWord(
                                word.ident,
                                INTRINSICS[word.ident.lexeme],
                                self.type_resolver.resolve_types(word.generic_arguments) if word.generic_arguments is not None else None),
                    self.abort(word.ident, f"function `{word.ident.lexeme}` not found")
                return call,
            case parsing.ForeignCallWord():
                return self.resolve_foreign_call(word),
            case parsing.CastWord():
                return resolved.CastWord(word.token, self.type_resolver.resolve_type(word.taip)),
            case parsing.InitWord():
                return self.resolve_init_local(word),
            case parsing.GetWord():
                return resolved.GetLocal(word.ident, self.lookup_variable(word.ident), word.fields),
            case parsing.SetWord():
                return resolved.SetLocal(word.ident, self.lookup_variable(word.ident), word.fields),
            case parsing.RefWord():
                return resolved.RefLocal(word.ident, self.lookup_variable(word.ident), word.fields),
            case parsing.StoreWord():
                return self.resolve_store_local(word),
            case parsing.LoadWord():
                return word,
            case parsing.SizeofWord():
                return resolved.SizeofWord(word.token, self.forbid_holes(self.type_resolver.resolve_type(word.taip))),
            case parsing.VariantWord():
                return self.resolve_make_variant(word),
            case parsing.IndirectCallWord():
                return resolved.IndirectCallWord(
                    word.token,
                    self.type_resolver.resolve_types(word.parameters),
                    self.type_resolver.resolve_types(word.returns)),
            case parsing.FunRefWord():
                call = self.resolve_call(word.call)
                if call is None:
                    self.abort(word.call.ident, f"function `{word.call.ident.lexeme}` not found")
                return resolved.FunRefWord(call),
            case parsing.GetFieldWord():
                return word,
            case parsing.InlineRefWord():
                return self.resolve_inline_ref_word(word)
            case parsing.StackAnnotation():
                return resolved.StackAnnotation(word.token, self.type_resolver.resolve_types(word.types)),
            case parsing.StructWord():
                custom_type = self.type_resolver.resolve_custom_type(word.taip)
                if isinstance(self.type_lookup.lookup(custom_type.type_definition), Variant):
                    self.abort(word.token, "expected a struct")
                return resolved.StructWord(word.token, word.name, custom_type),
            case parsing.StructWordNamed():
                return self.resolve_struct_word_named(word),
            case parsing.MatchWord():
                return self.resolve_match_word(word)
            case parsing.IfWord():
                return resolved.IfWord(
                    word.token,
                    self.resolve_scope(word.true_words.words),
                    self.resolve_scope(word.false_words.words if word.false_words is not None else ())),
            case parsing.LoopWord():
                ctx = self.with_in_block()
                return resolved.LoopWord(word.token, ctx.resolve_scope(word.words.words), ctx.resolve_block_annotation(word.annotation)),
            case parsing.BlockWord():
                ctx = self.with_in_block()
                return resolved.BlockWord(
                    word.token,
                    word.words.end,
                    ctx.resolve_scope(word.words.words),
                    ctx.resolve_block_annotation(word.annotation)),

    def resolve_inline_ref_word(self, word: parsing.InlineRefWord) -> Sequence[resolved.Word]:
        local = Local(SyntheticName(word.token, "synth:ref"), None)
        local_id = self.env.insert(local)
        return (resolved.InitLocal(word.token, local_id), resolved.RefLocal(word.token, local_id, ()))

    def resolve_call(self, word: parsing.CallWord | parsing.ForeignCallWord) -> resolved.CallWord | None:
        if isinstance(word, parsing.ForeignCallWord):
            return self.resolve_foreign_call(word)
        if word.ident.lexeme not in self.signatures:
            for imports in self.imports.values():
                for imp in imports:
                    for item in imp.items:
                        if isinstance(item.handle, FunctionHandle) and item.name.lexeme == word.ident.lexeme:
                            return resolved.CallWord(
                                word.ident,
                                item.handle,
                                self.type_resolver.resolve_types(word.generic_arguments) if word.generic_arguments is not None else None)
            return None

        function_handle = FunctionHandle(self.module_id, self.signatures.index_of(word.ident.lexeme))
        signature = self.lookup_signature(function_handle)
        generic_arguments = self.resolve_generic_arguments(word.ident, word.generic_arguments, len(signature.generic_parameters))
        return resolved.CallWord(
            word.ident,
            function_handle,
            generic_arguments)

    def resolve_generic_arguments(self, token: Token, generic_arguments: Tuple[parsing.Type, ...] | None, expected: int) -> Tuple[resolved.Type, ...] | None:
        if generic_arguments is None:
            return None
        args = self.type_resolver.resolve_types(generic_arguments)
        if len(args) != expected:
            self.abort(token, "resolve-generic-arguments TODO")
        return args

    def resolve_foreign_call(self, word: parsing.ForeignCallWord) -> resolved.CallWord:
        if word.module.lexeme not in self.imports:
            self.abort(word.module, "module not found")
        for imp in self.imports[word.module.lexeme]:
            module = self.modules.index(imp.module)
            item = module.lookup_item(word.ident)
            if isinstance(item, FunctionHandle):
                return resolved.CallWord(word.ident, item, self.type_resolver.resolve_types(word.generic_arguments) if word.generic_arguments is not None else None)
        self.abort(word.ident, f"function `{word.ident.lexeme}` not found")

    def lookup_variable(self, name: Token) -> LocalId | GlobalId:
        local_id = self.env.lookup(name)
        if local_id is not None:
            return local_id
        if name.lexeme in self.globals:
            return GlobalId(name, self.module_id, self.globals.index_of(name.lexeme))
        self.abort(name, "variable not found")

    def resolve_init_local(self, word: parsing.InitWord) -> resolved.InitLocal | resolved.StructFieldInitWord:
        if self.struct_literal_env is not None:
            field_name = word.ident.lexeme
            if field_name in self.struct_literal_env.all_fields:
                if field_name not in self.struct_literal_env.remaining_fields:
                    self.abort(word.ident, "field has already been initialized")
                del self.struct_literal_env.remaining_fields[field_name]
                field_index = self.struct_literal_env.all_fields[field_name]
                return resolved.StructFieldInitWord(word.ident, self.struct_literal_env.struct, field_index)
        local_id = self.env.insert(Local(FromSource(word.ident), None))
        return resolved.InitLocal(word.ident, local_id)

    def resolve_scope(self, parsed_words: Tuple[parsing.Word, ...], keep_struct_literal_env=False) -> resolved.Scope:
        env = self.env.child()
        if not keep_struct_literal_env:
            self = self.without_struct_literal_env()
        words = self.with_env(env).resolve_words(parsed_words)
        return resolved.Scope(env.scope_id, words)

    def resolve_store_local(self, word: parsing.StoreWord) -> resolved.StoreWord:
        local_id = self.env.lookup(word.ident)
        if local_id is None:
            self.abort(word.ident, "local not found")
        return resolved.StoreWord(word.ident, local_id, word.fields)

    def resolve_block_annotation(self, annotation: parsing.BlockAnnotation | None) -> resolved.BlockAnnotation | None:
        if annotation is None:
            return None
        return resolved.BlockAnnotation(
                self.type_resolver.resolve_types(annotation.parameters),
                self.type_resolver.resolve_types(annotation.returns))

    def resolve_make_variant(self, word: parsing.VariantWord) -> resolved.VariantWord:
        variant_type = self.type_resolver.resolve_custom_type(word.taip)
        variant = self.type_lookup.lookup(variant_type.type_definition)
        if not isinstance(variant, Variant):
            self.abort(word.token, "can not make this type")
        tag: None | int = None
        for i,case in enumerate(variant.cases):
            if case.name.lexeme == word.case.lexeme:
                tag = i
        if tag is None:
            self.abort(word.token, "case is not part of variant")
        case = variant.cases[tag]
        return resolved.VariantWord(word.token, tag, variant_type)

    def resolve_match_word(self, word: parsing.MatchWord) -> Sequence[resolved.Word]:
        if len(word.cases) == 0 and word.default is None:
            return resolved.MatchVoidWord(word.token),
        if len(word.cases) == 0 and word.default is not None:
            return self.resolve_scope(word.default.words).words
        variant_handle = self.infer_match_type(word)
        variant = self.type_lookup.lookup(variant_handle)
        assert(isinstance(variant, Variant))
        cases = tuple(self.resolve_match_case(variant, cays) for cays in word.cases)
        default = resolved.DefaultCase(
                word.default.name,
                self.resolve_scope(word.default.words)) if word.default is not None else None
        if word.default is None:
            self.error_on_missing_cases(variant, word, cases)
        return resolved.MatchWord(
                word.token,
                variant_handle,
                cases,
                default),

    def error_on_missing_cases(self, variant: Variant, match: parsing.MatchWord, cases: Sequence[resolved.MatchCase]):
        cases_matched = list(False for _ in variant.cases)
        for case in cases:
            if cases_matched[case.tag]:
                self.abort(case.name, "duplicate case")
            cases_matched[case.tag] = True
        if not all(cases_matched):
            self.abort(match.token, "missing cases in match")

    def infer_match_type(self, match: parsing.MatchWord) -> CustomTypeHandle:
        inferred: CustomTypeHandle | None = None
        for case in match.cases:
            if case.module is None:
                if case.variant is None:
                    handle,_ = self.lookup_constructor(case.name)
                    if inferred is not None and inferred != handle:
                        self.abort(case.name, "constructors belong to different variants")
                    inferred = handle
                else:
                    handle = self.type_resolver.resolve_custom_type_name(case.variant)
                    if not isinstance(self.type_lookup.lookup(handle), Variant):
                        self.abort(case.variant, "expected variant")
                    if inferred is not None and inferred != handle:
                        self.abort(case.name, "constructors belong to different variants")
                    inferred = handle
            else:
                assert(case.variant is not None)
                if case.module.lexeme not in self.imports:
                    self.abort(case.module, "module not found")
                for qualifier,imports in self.imports.items():
                    if qualifier != case.module.lexeme:
                        continue
                    found = False
                    for imp in imports:
                        module = self.modules.index(imp.module)
                        if case.variant.lexeme in module.type_definitions:
                            handle = CustomTypeHandle(imp.module, module.type_definitions.index_of(case.variant.lexeme))
                            if inferred is not None and inferred != handle:
                                self.abort(case.name, "foo constructors belong to different variants")
                            inferred = handle
                            found = True
                    if not found:
                        self.abort(case.variant, "variant not found")

        if inferred is None:
            self.abort(match.token, "could not determine type of match")
        return inferred

    def lookup_constructor(self, name: Token) -> Tuple[CustomTypeHandle, int]:
        for imports in self.imports.values():
            for imp in imports:
                for item in imp.items:
                    if isinstance(item, VariantImport):
                        variant = self.type_lookup.lookup(item.handle)
                        assert(not isinstance(variant, Struct))
                        for constructor in item.constructors:
                            if variant.cases[constructor].name.lexeme == name.lexeme:
                                return item.handle, constructor
                    pass
        if self.type_lookup.type_definitions is not None:
            for index, type_definition in enumerate(self.type_lookup.type_definitions.values()):
                if not isinstance(type_definition, Struct):
                    for tag, case in enumerate(type_definition.cases):
                        if case.name.lexeme == name.lexeme:
                            return CustomTypeHandle(self.module_id, index), tag
        self.abort(name, f"constructor {name.lexeme} not found")

    def resolve_match_case(self, variant: Variant, cays: parsing.MatchCase) -> resolved.MatchCase:
        tag = None
        for i, variant_case in enumerate(variant.cases):
            if variant_case.name.lexeme == cays.name.lexeme:
                tag = i
        if tag is None:
            self.abort(cays.name, "case not found")
        return resolved.MatchCase(tag, cays.name, self.resolve_scope(cays.words))

    def resolve_struct_word_named(self, word: parsing.StructWordNamed) -> resolved.StructWordNamed:
        taip = self.type_resolver.resolve_custom_type(word.taip)
        struct = self.type_lookup.lookup(taip.type_definition)
        if isinstance(struct, Variant):
            self.abort(word.name, "expected struct")
        struct_literal_env = StructLiteralEnv.of_struct(struct, taip.type_definition)
        words = self.with_struct_literal_env(struct_literal_env).resolve_scope(word.words, keep_struct_literal_env=True)
        if len(struct_literal_env.remaining_fields) != 0:
            error_message = "missing fields in struct literal:"
            for field_name,field_index in struct_literal_env.remaining_fields.items():
                field_taip = with_holes.with_generics(without_holes.with_holes(struct.fields[field_index].taip), taip.generic_arguments)
                error_message += f"\n\t{field_name}: {self.type_lookup.type_pretty(field_taip)}"
            self.abort(word.token, error_message)
        return resolved.StructWordNamed(
            word.token,
            word.name,
            taip,
            words)

