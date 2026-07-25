from __future__ import annotations

from resolving import FunctionHandle as FunctionHandle
from resolving.type_without_holes import (
        CustomTypeType as CustomTypeType,
        FunctionType as FunctionType,
        NamedType as NamedType,
        PtrType as PtrType,
        Type as Type,
)
from unstacking import Break as Break

from inference.inference import (
        InferenceException as InferenceException,
        infer_function as infer_function,
)

__all__ = ['Number', 'String']
from inference.module import (
        Module as Module,
)
from inference.top_items import (
        Extern as Extern,
        Function as Function,
        Global as Global,
        Local as Local,
)
from inference.words import (
        Add as Add,
        And as And,
        Block as Block,
        Call as Call,
        Cast as Cast,
        Div as Div,
        Drop as Drop,
        Eq as Eq,
        FieldAccess as FieldAccess,
        FieldInit as FieldInit,
        Flip as Flip,
        FunRef as FunRef,
        Ge as Ge,
        GetField as GetField,
        GetLocal as GetLocal,
        Gt as Gt,
        If as If,
        IndirectCall as IndirectCall,
        InitLocal as InitLocal,
        Le as Le,
        Load as Load,
        Loop as Loop,
        Lt as Lt,
        MakeStruct as MakeStruct,
        MakeStructNamed as MakeStructNamed,
        MakeVariant as MakeVariant,
        Match as Match,
        MatchCase as MatchCase,
        MatchVoid as MatchVoid,
        MemCopy as MemCopy,
        MemFill as MemFill,
        MemGrow as MemGrow,
        Mod as Mod,
        Mul as Mul,
        Not as Not,
        NotEq as NotEq,
        NumberWord as Number,
        Or as Or,
        RefLocal as RefLocal,
        Rotl as Rotl,
        Rotr as Rotr,
        Scope as Scope,
        SetLocal as SetLocal,
        SetStackSize as SetStackSize,
        Shl as Shl,
        Shr as Shr,
        Sizeof as Sizeof,
        Store as Store,
        StoreLocal as StoreLocal,
        StringWord as String,
        Sub as Sub,
        Uninit as Uninit,
        Word as Word,
)
