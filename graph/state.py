from typing import TypedDict, List, Dict, Any

class UCDState(TypedDict):
    """LangGraph 运行时的全局状态 (State)"""
    input_text: str                   # 用户的原始输入文本
    entities: Dict[str, List[str]]    # {角色: [用例]}
    actors: List[str]                 # 独立的角色列表
    usecases: List[str]               # 独立的用例列表
    relationships: Dict[str, Any]     # include, extend, generalization 等关系