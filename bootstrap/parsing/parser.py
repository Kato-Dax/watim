from typing import List, Tuple, NoReturn, TypeGuard, Callable
from dataclasses import dataclass

import format
from format import Formattable, Formatter
from lexer import Token, TokenType, TokenLocation
from parsing.types import Type, ForeignType, CustomTypeType, NamedType, I8, I32, I64, Bool, PtrType, GenericType, FunctionType, HoleType
from parsing.words import Word, Words, IfWord, NumberWord, StringWord, InlineRefWord, GetWord, RefWord, LoadWord, BlockAnnotation, BlockWord, StructWord, VariantWord, CastWord, SetWord, StoreWord, InitWord, IndirectCallWord, SizeofWord, GetFieldWord, ForeignCallWord, FunRefWord, LoopWord, MatchCase, MatchWord, CallWord, BreakWord, StackAnnotation, StructWordNamed
from parsing.top_items import Struct, Variant, Function, Extern, Global, TypeDefinition, Import, VariantCase, FunctionSignature, VariantImport

@dataclass
class ParseException(Exception):
    location: TokenLocation | Tuple[str, str] | None
    message: str

    def display(self) -> str:
        if self.location is None:
            return self.message
        if isinstance(self.location, TokenLocation):
            file_path = self.location.file_path
            line = self.location.line
            column = self.location.column
        else:
            file_path = self.location[0]
            lines = self.location[1].splitlines()
            line = len(lines) + 1
            column = len(lines[-1]) + 1 if len(lines) != 0 else 1
        return f"{file_path}:{line}:{column} {self.message}"


@dataclass
class Module(Formattable):
    path: str
    file: str
    imports: List[Import]
    type_definitions: List[TypeDefinition]
    globals: List[Global]
    functions: List[Function | Extern]
    def format(self, fmt: Formatter):
        fmt.named_record("Module", [
            ("imports", format.Seq(self.imports, multi_line=True)),
            ("type-definitions", format.Seq(self.type_definitions, multi_line=True)),
            ("globals", format.Seq(self.globals, multi_line=True)),
            ("functions", format.Seq(self.functions, multi_line=True))])

@dataclass
class Parser:
    file_path: str
    file: str
    tokens: List[Token]
    cursor: int = 0

    # ========================================
    # Utility functions for the parser
    # ========================================
    def peek(self, skip_ws: bool = False) -> Token | None:
        i = self.cursor
        while True:
            if i >= len(self.tokens):
                return None
            token = self.tokens[i]
            if skip_ws and token.ty == TokenType.SPACE:
                i += 1
                continue
            return token

    def advance(self, skip_ws: bool = False):
        while True:
            if self.cursor >= len(self.tokens):
                return None
            token = self.tokens[self.cursor]
            self.cursor += 1
            if skip_ws and token.ty == TokenType.SPACE:
                continue
            return token

    def retreat(self):
        assert(self.cursor > 0)
        self.cursor -= 1

    def abort(self, message: str) -> NoReturn:
        if self.cursor < len(self.tokens):
            current = self.tokens[self.cursor]
            raise ParseException(TokenLocation(self.file_path, current.line, current.column), message)
        else:
            raise ParseException((self.file_path, self.file), message)


    # ========================================
    # Parsing routines
    # ========================================
    def parse(self) -> Module:
        top_items: List[Import | TypeDefinition | Global | Function | Extern] = []
        while len(self.tokens) != 0:
            token = self.advance(skip_ws=True)
            if token is None:
                break
            if token.ty == TokenType.IMPORT:
                file_path = self.advance(skip_ws=True)
                if file_path is None or file_path.ty != TokenType.STRING:
                    self.abort("Expected file path")

                ass = self.advance(skip_ws=True)
                if ass is None or ass.ty != TokenType.AS:
                    self.abort("Expected `as`")

                module_qualifier = self.advance(skip_ws=True)
                if module_qualifier is None or module_qualifier.ty != TokenType.IDENT:
                    self.abort("Expected an identifier as module qualifier")

                paren = self.peek(skip_ws=True)
                items = []
                if paren is not None and paren.ty == TokenType.LEFT_PAREN:
                    self.advance(skip_ws=True) # skip LEFT_PAREN
                    while True:
                        item = self.advance(skip_ws=True)
                        if item is None:
                            self.abort("expected a function or type to import")
                        if item.ty == TokenType.RIGHT_PAREN:
                            break
                        comma = self.advance(skip_ws=True)
                        if comma is None or comma.ty == TokenType.RIGHT_PAREN:
                            items.append(item)
                            break
                        if comma.ty == TokenType.LEFT_PAREN:
                            constructors: List[Token] = []
                            while True:
                                constructor = self.advance(skip_ws=True)
                                if constructor is None:
                                    self.abort("expected a constructor to import")
                                if constructor.ty == TokenType.RIGHT_PAREN:
                                    break
                                constructors.append(constructor)
                                commaa = self.advance(skip_ws=True)
                                if commaa is None or commaa.ty == TokenType.RIGHT_PAREN:
                                    break
                                if commaa.ty != TokenType.COMMA:
                                    self.abort("expected `,`")
                            comma = self.advance(skip_ws=True)
                            items.append(VariantImport(item, tuple(constructors)))
                        else:
                            items.append(item)
                        if comma is None or comma.ty == TokenType.RIGHT_PAREN:
                            break
                        if comma.ty != TokenType.COMMA:
                            self.abort("expected `)`")
                top_items.append(Import(token, file_path, module_qualifier, tuple(items)))
                continue

            if token.ty == TokenType.FN:
                top_items.append(self.parse_function(token))
                continue

            if token.ty == TokenType.EXTERN:
                module = self.advance(skip_ws=True)
                if module is None or module.ty != TokenType.STRING:
                    self.abort("Expected string as extern function module name")
                name = self.advance(skip_ws=True)
                if name is None or name.ty != TokenType.STRING:
                    self.abort("Expected string as extern function name")
                fn = self.advance(skip_ws=True)
                if fn is None or fn.ty != TokenType.FN:
                    self.abort("Expected `fn`")
                signature = self.parse_function_signature()
                top_items.append(Extern(token, module, name, signature))
                continue

            if token.ty == TokenType.STRUCT:
                name = self.advance(skip_ws=True)
                if name is None or name.ty != TokenType.IDENT:
                    self.abort("Expected identifier as struct name")
                generic_parameters = self.parse_generic_parameters()
                brace = self.advance(skip_ws=True)
                if brace is None or brace.ty != TokenType.LEFT_BRACE:
                    self.abort("Expected `{`")
                fields = []
                while True:
                    next = self.advance(skip_ws=True)
                    if next is not None and next.ty == TokenType.RIGHT_BRACE:
                        break
                    field_name = next
                    if field_name is None or field_name.ty != TokenType.IDENT:
                        self.abort("Expected identifier as struct field name")
                    colon = self.advance(skip_ws=True)
                    if colon is None or colon.ty != TokenType.COLON:
                        self.abort("Expected `:` after field name")
                    taip = self.parse_type(generic_parameters)
                    fields.append(NamedType(field_name, taip))
                top_items.append(Struct(token, name, tuple(fields), generic_parameters))
                continue

            if token.ty == TokenType.VARIANT:
                name = self.advance(skip_ws=True)
                if name is None:
                    self.abort("Expected an identifier")
                generic_parameters = self.parse_generic_parameters()
                brace = self.advance(skip_ws=True)
                if brace is None or brace.ty != TokenType.LEFT_BRACE:
                    self.abort("Expected `{`")
                cases: List[VariantCase] = []
                while True:
                    next = self.peek(skip_ws=True)
                    if next is None or next.ty == TokenType.RIGHT_BRACE:
                        self.advance(skip_ws=True)
                        break
                    case = self.advance(skip_ws=True)
                    if case is None or case.ty != TokenType.CASE:
                        self.abort("expected `case`")
                    ident = self.advance(skip_ws=True)
                    if ident is None or ident.ty != TokenType.IDENT:
                        self.abort("expected an identifier")
                    arrow = self.peek(skip_ws=True)
                    if arrow is None or arrow.ty != TokenType.ARROW:
                        cases.append(VariantCase(ident, None))
                        continue
                    self.advance(skip_ws=True)
                    cases.append(VariantCase(ident, self.parse_type(generic_parameters)))
                top_items.append(Variant(name, generic_parameters, cases))
                continue

            if token.ty == TokenType.GLOBAL:
                name = self.advance(skip_ws=True)
                if name is None:
                    self.abort("expected an identifier")
                colon = self.advance(skip_ws=True)
                if colon is None or colon.ty != TokenType.COLON:
                    self.abort("Expected `:`")
                taip = self.parse_type(())
                top_items.append(Global(token, name, taip))
                continue

            self.abort("Expected function import or struct definition")
        def is_import(obj: object) -> TypeGuard[Import]:
            return isinstance(obj, Import)
        def is_type_definition(obj: object) -> TypeGuard[TypeDefinition]:
            return isinstance(obj, Struct) or isinstance(obj, Variant)
        def is_global(obj: object) -> TypeGuard[Global]:
           return isinstance(obj, Global)
        imports: List[Import] = list(filter(is_import, top_items))
        type_definitions: List[TypeDefinition] = list(filter(is_type_definition, top_items))
        globals: List[Global] = list(filter(is_global, top_items))
        functions: List[Function | Extern] = [f for f in top_items if isinstance(f, Function) or isinstance(f, Extern)]
        return Module(self.file_path, self.file, imports, type_definitions, globals, functions)

    def parse_function(self, start: Token) -> Function:
        signature = self.parse_function_signature()
        token = self.advance(skip_ws=True)
        if token is None or token.ty != TokenType.LEFT_BRACE:
            self.abort("Expected `{`")
        body = self.parse_words(signature.generic_parameters)
        return Function(start, signature, body.words)

    def parse_words(self, generic_parameters: Tuple[Token, ...]) -> Words:
        words: List[Word] = []
        while True:
            token = self.peek(skip_ws=True)
            if token is not None and token.ty == TokenType.RIGHT_BRACE:
                self.advance(skip_ws=True)
                return Words(tuple(words), token)
            words.append(self.parse_word(generic_parameters))

    def parse_word(self, generic_parameters: Tuple[Token, ...]) -> Word:
        token = self.advance(skip_ws=True)
        if token is None:
            self.abort("Expected a word")
        if token.ty == TokenType.NUMBER:
            return NumberWord(token)
        if token.ty == TokenType.STRING:
            string = bytearray()
            i = 1
            while i < len(token.lexeme) - 1:
                if token.lexeme[i] != "\\":
                    string.extend(token.lexeme[i].encode('utf-8'))
                    i += 1
                    continue
                if token.lexeme[i + 1] == "\"":
                    string.extend(b"\"")
                elif token.lexeme[i + 1] == "n":
                    string.extend(b"\n")
                elif token.lexeme[i + 1] == "t":
                    string.extend(b"\t")
                elif token.lexeme[i + 1] == "r":
                    string.extend(b"\r")
                elif token.lexeme[i + 1] == "\\":
                    string.extend(b"\\")
                else:
                    assert(False)
                i += 2
            return StringWord(token, string)
        if token.ty == TokenType.AMPERSAND:
            next = self.peek(skip_ws=False)
            if next is not None and next.ty == TokenType.SPACE:
                return InlineRefWord(token)
        if token.ty in [TokenType.DOLLAR, TokenType.AMPERSAND, TokenType.HASH, TokenType.DOUBLE_ARROW]:
            indicator_token = token
            name = self.advance(skip_ws=True)
            if name is None or name.ty != TokenType.IDENT:
                self.abort("Expected an identifier as variable name")
            token = self.peek(skip_ws=True)
            def construct(name: Token, fields: Tuple[Token, ...]) -> Word:
                match indicator_token.ty:
                    case TokenType.DOLLAR:
                        return GetWord(indicator_token, name, fields)
                    case TokenType.AMPERSAND:
                        return RefWord(indicator_token, name, fields)
                    case TokenType.HASH:
                        return SetWord(indicator_token, name, fields)
                    case TokenType.DOUBLE_ARROW:
                        return StoreWord(indicator_token, name, fields)
                    case _:
                        assert(False)
            if token is None or token.ty == TokenType.SPACE:
                return construct(name, ())
            fields = self.parse_field_accesses()
            return construct(name, fields)
        if token.ty == TokenType.AT:
            ident = self.advance(skip_ws=False)
            if ident is None or ident.ty != TokenType.IDENT:
                self.abort("Expected an identifier as variable name")
            return InitWord(token, ident)
        if token.ty == TokenType.IDENT:
            return self.parse_call_word(generic_parameters, token)
        if token.ty == TokenType.BACKSLASH:
            backslash = token
            token = self.advance(skip_ws=True) # skip `\`
            assert(token is not None)
            return FunRefWord(backslash, self.parse_call_word(generic_parameters, token))
        if token.ty == TokenType.IF:
            brace = self.advance(skip_ws=True)
            if brace is None or brace.ty != TokenType.LEFT_BRACE:
                self.abort("Expected `{`")
            if_words = self.parse_words(generic_parameters)
            next = self.peek(skip_ws=True)
            if next is None or next.ty != TokenType.ELSE:
                return IfWord(token, if_words, None)
            self.advance(skip_ws=True) # skip `else`
            brace = self.advance(skip_ws=True)
            if brace is None or brace.ty != TokenType.LEFT_BRACE:
                self.abort("Expected `{`")
            else_words = self.parse_words(generic_parameters)
            return IfWord(token, if_words, else_words)
        if token.ty == TokenType.TILDE:
            return LoadWord(token)
        if token.ty == TokenType.LOOP or token.ty == TokenType.BLOCK:
            brace = self.advance(skip_ws=True)
            if brace is None:
                self.abort("Expected `{`")
            if brace.ty == TokenType.LEFT_BRACE:
                parameters = None
                returns = None
            else:
                parameters = []
                while True:
                    next = self.peek(skip_ws=True)
                    if next is None or next.ty == TokenType.ARROW:
                       self.advance(skip_ws=True) # skip `->`
                       break
                    parameters.append(self.parse_type(generic_parameters))
                    comma = self.peek(skip_ws=True)
                    if comma is None or comma.ty == TokenType.ARROW:
                        self.advance(skip_ws=True) # skip `->`
                        break
                    if comma.ty != TokenType.COMMA:
                        self.abort("Expected `,`")
                    self.advance(skip_ws=True)
                returns = []
                while True:
                    next = self.peek(skip_ws=True)
                    if next is None or next.ty == TokenType.RIGHT_PAREN:
                        self.advance(skip_ws=True) # skip `)`
                        break
                    returns.append(self.parse_type(generic_parameters))
                    comma = self.advance(skip_ws=True)
                    if comma is None or comma.ty == TokenType.RIGHT_PAREN:
                        break
                    if comma.ty != TokenType.COMMA:
                        self.abort("Expected `,`")
                brace = self.advance(skip_ws=True)
                if brace is None or brace.ty != TokenType.LEFT_BRACE:
                    self.abort("Expected `{`")
            annotation = None if parameters is None and returns is None else BlockAnnotation(parameters or [], returns or [])
            words = self.parse_words(generic_parameters)
            if token.ty == TokenType.LOOP:
                return LoopWord(token, words, annotation)
            if token.ty == TokenType.BLOCK:
                return BlockWord(token, words, annotation)
        if token.ty == TokenType.BREAK:
            return BreakWord(token)
        if token.ty == TokenType.BANG:
            return CastWord(token, self.parse_type(generic_parameters))
        if token.ty == TokenType.SIZEOF:
            paren = self.advance(skip_ws=True)
            if paren is None or paren.ty != TokenType.LEFT_PAREN:
                self.abort("Expected `(`")
            taip = self.parse_type(generic_parameters)
            paren = self.advance(skip_ws=True)
            if paren is None or paren.ty != TokenType.RIGHT_PAREN:
                self.abort("Expected `)`")
            return SizeofWord(token, taip)
        if token.ty == TokenType.DOT:
            self.retreat()
            return GetFieldWord(token, self.parse_field_accesses())
        if token.ty == TokenType.MAKE:
            struct_name_token = self.advance(skip_ws=True)
            taip = self.parse_struct_type(struct_name_token, generic_parameters)
            dot = self.peek(skip_ws=False)
            if dot is not None and dot.ty == TokenType.DOT:
                self.advance(skip_ws=False)
                case_name = self.advance(skip_ws=False)
                if case_name is None or case_name.ty != TokenType.IDENT:
                    self.abort("expected an identifier")
                return VariantWord(token, taip, case_name)
            brace = self.peek(skip_ws=True)
            if brace is not None and brace.ty == TokenType.LEFT_BRACE:
                brace = self.advance(skip_ws=True)
                words = self.parse_words(generic_parameters)
                return StructWordNamed(token, taip.name, taip, words.words)
            return StructWord(token, taip.name, taip)
        if token.ty == TokenType.MATCH:
            brace = self.advance(skip_ws=True)
            if brace is None or brace.ty != TokenType.LEFT_BRACE:
                self.abort("Expected `{`")
            cases: List[MatchCase] = []
            while True:
                cays = self.peek(skip_ws=True)
                if cays is None or cays.ty == TokenType.RIGHT_BRACE:
                    self.advance(skip_ws=True)
                    return MatchWord(token, tuple(cases), None)
                case = self.advance(skip_ws=True)
                if case is None or case.ty != TokenType.CASE:
                    self.abort("expected `case`")
                case_name = self.advance(skip_ws=True)
                if case_name is None or (case_name.ty != TokenType.IDENT and case_name.ty != TokenType.UNDERSCORE):
                    self.abort("Expected an identifier")
                next = self.peek()
                if next is not None and next.ty == TokenType.COLON:
                    self.advance()
                    module_name = case_name
                    case_name = self.advance()
                    if case_name is None or case_name.ty != TokenType.IDENT:
                        self.abort("Expected an identifier")
                else:
                    module_name = None
                next = self.peek()
                if next is not None and next.ty == TokenType.DOT:
                    self.advance()
                    variant_name = case_name
                    case_name = self.advance()
                    if case_name is None or case_name.ty != TokenType.IDENT:
                        self.abort("Expected an identifier")
                else:
                    variant_name = None
                arrow = self.advance(skip_ws=True)
                if arrow is None or arrow.ty != TokenType.ARROW:
                    self.abort("Expected `->`")
                brace = self.advance(skip_ws=True)
                if brace is None or brace.ty != TokenType.LEFT_BRACE:
                    self.abort("Expected `{`")
                words = self.parse_words(generic_parameters)
                if case_name.ty == TokenType.UNDERSCORE:
                    brace = self.advance(skip_ws=True)
                    if brace is None or brace.ty != TokenType.RIGHT_BRACE:
                        self.abort("Expected `}`")
                    return MatchWord(token, tuple(cases), MatchCase(cays, None, None, case_name, words.words))
                cases.append(MatchCase(cays, module_name, variant_name, case_name, words.words))
        if token.ty == TokenType.COLON:
            next = self.advance(skip_ws=True)
            if next is None or next.ty != TokenType.LEFT_PAREN:
                self.abort("Expected `(`")
            types: List[Type] = []
            while True:
                next = self.peek(skip_ws=True)
                if next is not None and next.ty == TokenType.RIGHT_PAREN:
                    self.advance(skip_ws=True)
                    return StackAnnotation(token, ())
                types.append(self.parse_type(generic_parameters))
                next = self.advance(skip_ws=True)
                if next is None:
                    self.abort("Expected `,` or `)`")
                if next.ty == TokenType.RIGHT_PAREN:
                    return StackAnnotation(token, tuple(types))
                if next.ty != TokenType.COMMA:
                    self.abort("Expected `,` or `)`")
        if token.ty == TokenType.LEFT_PAREN:
            fun_type = self.parse_fun_type(generic_parameters, token)
            return IndirectCallWord(token, fun_type.parameters, fun_type.returns)
        self.abort("Expected word")

    def parse_call_word(self, generic_parameters: Tuple[Token, ...], token: Token) -> CallWord | ForeignCallWord:
        next = self.peek(skip_ws=False)
        if next is not None and next.ty == TokenType.COLON:
            module = token
            self.advance(skip_ws=False) # skip the `:`
            name = self.advance(skip_ws=False)
            if name is None or name.ty != TokenType.IDENT:
                self.abort("Expected an identifier")
            next = self.peek()
            generic_arguments = self.parse_generic_arguments(generic_parameters) if next is not None and next.ty == TokenType.LEFT_TRIANGLE else ()
            return ForeignCallWord(module, name, generic_arguments)
        name = token
        generic_arguments = self.parse_generic_arguments(generic_parameters) if next is not None and next.ty == TokenType.LEFT_TRIANGLE else ()
        return CallWord(name, generic_arguments)

    def parse_field_accesses(self) -> Tuple[Token, ...]:
        fields = []
        while True:
            token = self.peek(skip_ws=False)
            if token is None or token.ty != TokenType.DOT:
                break
            self.advance(skip_ws=False) # skip the `.`
            token = self.advance(skip_ws=False)
            if token is None or token.ty != TokenType.IDENT:
                self.abort("Expected an identifier as field name")
            fields.append(token)
        return tuple(fields)

    def parse_function_signature(self) -> FunctionSignature:
        function_ident = self.advance(skip_ws=True)
        if function_ident is None or function_ident.ty != TokenType.IDENT:
            self.abort("Expected identifier as function name")

        token = self.peek(skip_ws=True)
        if token is None:
            self.abort("Expected `<` or `(`")
        if token.ty == TokenType.LEFT_TRIANGLE:
            generic_parameters = self.parse_generic_parameters()
        else:
            generic_parameters = ()

        token = self.advance(skip_ws=True)
        if token is None or token.ty not in [TokenType.LEFT_PAREN, TokenType.STRING]:
            self.abort("Expected either `(` or a string as name of an exported function")

        if token.ty == TokenType.STRING:
            function_export_name = token
            token = self.advance(skip_ws=True)
            if token is None or token.ty != TokenType.LEFT_PAREN:
                self.abort("Expected `(`)")
        else:
            function_export_name = None

        parameters = []
        while True:
            token = self.advance(skip_ws=True)
            if token is not None and token.ty == TokenType.RIGHT_PAREN:
                break
            if token is None or token.ty != TokenType.IDENT:
                self.abort("Expected `)` or an identifier as a function parameter name")
            parameter_name = token
            token = self.advance(skip_ws=True)
            if token is None or token.ty != TokenType.COLON:
                self.abort("Expected `:` after function parameter name")

            parameter_type = self.parse_type(generic_parameters)
            parameters.append(NamedType(parameter_name, parameter_type))
            token = self.advance(skip_ws=True)
            if token is not None and token.ty == TokenType.RIGHT_PAREN:
                break
            if token is None or token.ty != TokenType.COMMA:
                self.abort("Expected `,` after function parameter")

        returns = []
        token = self.peek(skip_ws=True)
        if token is not None and token.ty == TokenType.ARROW:
            self.advance(skip_ws=True) # skip the `->`
            while True:
                taip = self.parse_type(generic_parameters)
                returns.append(taip)
                token = self.peek(skip_ws=True)
                if token is None or token.ty != TokenType.COMMA:
                    break
                self.advance(skip_ws=True) # skip the `,`

        return FunctionSignature(function_export_name, function_ident, generic_parameters, tuple(parameters), tuple(returns))

    def parse_triangle_listed[T](self, elem: Callable[['Parser'], T]) -> Tuple[T, ...]:
        token = self.advance(skip_ws=True)
        if token is None or token.ty != TokenType.LEFT_TRIANGLE:
            self.abort("Expected `<`")
        items = []
        while True:
            token = self.peek(skip_ws=True)
            if token is None:
                self.abort("Expected `>` or an identifier")
            if token.ty == TokenType.RIGHT_TRIANGLE:
                self.advance(skip_ws=True) # skip `>`
                break
            items.append(elem(self))
            token = self.advance(skip_ws=True)
            if token is None or token.ty == TokenType.RIGHT_TRIANGLE:
                break
            if token.ty != TokenType.COMMA:
                self.abort("Expected `,`")
        return tuple(items)

    def parse_generic_arguments(self, generic_parameters: Tuple[Token, ...]) -> Tuple[Type, ...]:
        next = self.peek(skip_ws=False)
        return self.parse_triangle_listed(lambda self: self.parse_type(generic_parameters)) if next is not None and next.ty == TokenType.LEFT_TRIANGLE else ()

    def parse_generic_parameters(self) -> Tuple[Token, ...]:
        def parse_ident(self):
            token = self.advance(skip_ws=True)
            if token is None or token.ty != TokenType.IDENT:
                self.abort("Expected an identifier as generic paramter")
            return token
        next = self.peek(skip_ws=False)
        return self.parse_triangle_listed(parse_ident) if next is not None and next.ty == TokenType.LEFT_TRIANGLE else ()

    def parse_struct_type(self, token: Token | None, generic_parameters: Tuple[Token, ...]) -> CustomTypeType | ForeignType:
        if token is None or token.ty != TokenType.IDENT:
            self.abort("Expected an identifer as struct name")
        next = self.peek(skip_ws=True)
        if next is not None and next.ty == TokenType.COLON:
            self.advance(skip_ws=True) # skip the `:`
            module = token
            struct_name = self.advance(skip_ws=True)
            if struct_name is None or struct_name.ty != TokenType.IDENT:
                self.abort("Expected an identifier as struct name")
            return ForeignType(module, struct_name, self.parse_generic_arguments(generic_parameters))
        else:
            struct_name = token
            if struct_name is None or struct_name.ty != TokenType.IDENT:
                self.abort("Expected an identifier as struct name")
            return CustomTypeType(struct_name, self.parse_generic_arguments(generic_parameters))

    def parse_type(self, generic_parameters: Tuple[Token, ...]) -> Type:
        token = self.advance(skip_ws=True)
        if token is None:
            self.abort("Expected a type")
        if token.ty == TokenType.I8:
            return I8()
        if token.ty == TokenType.I32:
            return I32()
        if token.ty == TokenType.I64:
            return I64()
        if token.ty == TokenType.Bool:
            return Bool()
        if token.ty == TokenType.DOT:
            return PtrType(self.parse_type(generic_parameters))
        if token.ty == TokenType.UNDERSCORE:
            return HoleType(token)
        if token.ty == TokenType.IDENT:
            for generic_index, lexeme in enumerate(map(lambda t: t.lexeme, generic_parameters)):
                if lexeme == token.lexeme:
                    return GenericType(token, generic_index)
            return self.parse_struct_type(token, generic_parameters)
        if token.ty == TokenType.LEFT_PAREN:
            return self.parse_fun_type(generic_parameters, token)
        self.abort("Expected type")

    def parse_fun_type(self, generic_parameters: Tuple[Token, ...], token: Token) -> FunctionType:
        args = []
        while True:
            next = self.peek(skip_ws=True)
            if next is not None and next.ty == TokenType.ARROW:
                self.advance(skip_ws=True) # skip `=>`
                break
            args.append(self.parse_type(generic_parameters))
            next = self.peek(skip_ws=True)
            if next is not None and next.ty == TokenType.ARROW:
                self.advance(skip_ws=True) # skip `=>`
                break
            comma = self.advance(skip_ws=True)
            if comma is None or comma.ty != TokenType.COMMA:
                self.abort("Expected `,` in argument list of function type.")
        rets = []
        while True:
            next = self.peek(skip_ws=True)
            if next is not None and next.ty == TokenType.RIGHT_PAREN:
                self.advance(skip_ws=True) # skip `)`
                break
            rets.append(self.parse_type(generic_parameters))
            next = self.peek(skip_ws=True)
            if next is not None and next.ty == TokenType.RIGHT_PAREN:
                self.advance(skip_ws=True) # skip `)`
                break
            comma = self.advance(skip_ws=True)
            if comma is None or comma.ty != TokenType.COMMA:
                self.abort("Expected `,` in return list of function type.")
        return FunctionType(token, tuple(args), tuple(rets))
