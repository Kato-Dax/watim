from enum import Enum

class IntrinsicType(str, Enum):
    ADD = "Add"
    STORE = "Store"
    DROP = "Drop"
    SUB = "Sub"
    EQ = "Eq"
    NOT_EQ = "NotEq"
    MOD = "Mod"
    DIV = "Div"
    AND = "And"
    NOT = "Not"
    OR = "Or"
    LESS = "Lt"
    GREATER = "Gt"
    LESS_EQ = "Le"
    GREATER_EQ = "Ge"
    MUL = "Mul"
    SHL = "Shl"
    SHR = "Shr"
    ROTL = "Rotl"
    ROTR = "Rotr"
    MEM_GROW = "MemGrow"
    MEM_COPY = "MemCopy"
    MEM_FILL = "MemFill"
    FLIP = "Flip"
    UNINIT = "Uninit"
    SET_STACK_SIZE = "SetStackSize"

INTRINSICS: dict[str, IntrinsicType] = {
        "drop": IntrinsicType.DROP,
        "flip": IntrinsicType.FLIP,
        "+": IntrinsicType.ADD,
        "lt": IntrinsicType.LESS,
        "gt": IntrinsicType.GREATER,
        "=": IntrinsicType.EQ,
        "le": IntrinsicType.LESS_EQ,
        "ge": IntrinsicType.GREATER_EQ,
        "not": IntrinsicType.NOT,
        "mem-grow": IntrinsicType.MEM_GROW,
        "-": IntrinsicType.SUB,
        "and": IntrinsicType.AND,
        "%": IntrinsicType.MOD,
        "/": IntrinsicType.DIV,
        "/=": IntrinsicType.NOT_EQ,
        "*": IntrinsicType.MUL,
        "mem-copy": IntrinsicType.MEM_COPY,
        "mem-fill": IntrinsicType.MEM_FILL,
        "shl": IntrinsicType.SHL,
        "shr": IntrinsicType.SHR,
        "rotl": IntrinsicType.ROTL,
        "rotr": IntrinsicType.ROTR,
        "or": IntrinsicType.OR,
        "store": IntrinsicType.STORE,
        "uninit": IntrinsicType.UNINIT,
        "set-stack-size": IntrinsicType.SET_STACK_SIZE,
}
INTRINSIC_TO_LEXEME: dict[IntrinsicType, str] = {v: k for k, v in INTRINSICS.items()}

