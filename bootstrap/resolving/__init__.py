from resolving.top_items import (
        Local as Local, LocalName as LocalName,
        Struct as Struct, Variant as Variant, VariantCase as VariantCase,
        Global as Global, Function as Function,
        Extern as Extern, TypeDefinition as TypeDefinition,
        FunctionHandle as FunctionHandle,
        CustomTypeHandle as CustomTypeHandle,
        FunctionSignature as FunctionSignature,
)
from resolving import (words as words)
from resolving.words import (
        Word as Word,
        IntrinsicType as IntrinsicType,
        StackAnnotation as StackAnnotation,
        LocalId as LocalId,
        GlobalId as GlobalId,
        ScopeId as ScopeId,
        ROOT_SCOPE as ROOT_SCOPE,
)
from resolving.types import (
        Type as Type,
        NamedType as NamedType,
        CustomTypeType as CustomTypeType,
        FunctionType as FunctionType,
        GenericType as GenericType,
        PtrType as PtrType,
        HoleType as HoleType,
)
from resolving.type_resolver import (
        TypeLookup as TypeLookup
)
from resolving.resolver import (
        ModuleResolver as ModuleResolver
)
from resolving.module import (
        Module as Module,
        ResolveException as ResolveException,
)
