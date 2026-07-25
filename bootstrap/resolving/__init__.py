from __future__ import annotations

from resolving import words as words
from resolving.module import (
        Module as Module,
        ResolveException as ResolveException,
)
from resolving.resolver import ModuleResolver as ModuleResolver
from resolving.top_items import (
        CustomTypeHandle as CustomTypeHandle,
        Extern as Extern,
        Function as Function,
        FunctionHandle as FunctionHandle,
        FunctionSignature as FunctionSignature,
        Global as Global,
        Local as Local,
        LocalName as LocalName,
        Struct as Struct,
        TypeDefinition as TypeDefinition,
        Variant as Variant,
        VariantCase as VariantCase,
)
from resolving.type_resolver import TypeLookup as TypeLookup
from resolving.types import (
        CustomTypeType as CustomTypeType,
        FunctionType as FunctionType,
        GenericType as GenericType,
        HoleType as HoleType,
        NamedType as NamedType,
        PtrType as PtrType,
        Type as Type,
)
from resolving.words import (
        ROOT_SCOPE as ROOT_SCOPE,
        GlobalId as GlobalId,
        IntrinsicType as IntrinsicType,
        LocalId as LocalId,
        ScopeId as ScopeId,
        StackAnnotation as StackAnnotation,
        Word as Word,
)
