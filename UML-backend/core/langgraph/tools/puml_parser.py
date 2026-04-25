"""PlantUML code parser and reverse-sync utilities."""

import json
from typing import Dict, Any

from services.llm import openai_chat_completion
from core.prompts.templates import get_template

# ================================================================
# MOCK 模式开关（调试时设为 True，跳过 LLM 调用）
# ================================================================
MOCK_MODE = False  # TODO: 调试完成后改为 False


def parse_puml_to_json(puml_code: str) -> Dict[str, Any]:
    """将 PlantUML 代码直接解析为 JSON 数据结构（用于逆向同步）。"""
    return sync_puml_to_state(diagram_type="usecase", puml_code=puml_code, current_state={})


def sync_puml_to_state(
    diagram_type: str, puml_code: str, current_state: Dict[str, Any]
) -> Dict[str, Any]:
    """读取修改后的 PUML 代码，调用大模型将其变更同步回 State JSON。"""
    print(f"[SYNC] analyzing {diagram_type} PUML changes and syncing to state...")

    # MOCK 模式：直接透传 current_state 中的 sequence_data（已是正确结构）
    if MOCK_MODE:
        print("[MOCK] sync_puml_to_state - returning current state")
        return current_state

    prompt_tpl = get_template("puml_sync_prompt", "将PUML解析为JSON")

    if diagram_type == "usecase":
        original_data = {
            "entities": current_state.get("entities"),
            "actors": current_state.get("actors"),
            "usecases": current_state.get("usecases"),
            "relationships": current_state.get("relationships"),
        }
    elif diagram_type == "class":
        original_data = {
            "classes": current_state.get("classes"),
            "class_details": current_state.get("class_details"),
            "class_relationships": current_state.get("class_relationships"),
        }
    elif diagram_type == "sequence":
        original_data = {
            "sequence_data": current_state.get("sequence_data", {}),
        }

    prompt = prompt_tpl.format(
        diagram_type=diagram_type,
        original_json=json.dumps(original_data, ensure_ascii=False),
        puml_code=puml_code,
    )

    res = openai_chat_completion(
        "你是一个JSON还原器，只输出有效的JSON。",
        [{"role": "user", "content": prompt}],
    )

    try:
        updated_data = json.loads(res)
        print("[OK] PUML changes parsed and merged to state")
        return updated_data
    except Exception as e:
        print(f"[WARN] PUML reverse-parse failed: {e}, returning empty dict")
        return {}


# ================================================================
# 正则解析器（极速模式，无需调用 LLM）
# ================================================================

import re


def _clean_puml_lines(puml_code: str) -> list:
    """清理 PUML 代码：去除空行、注释和装饰性指令。"""
    lines = puml_code.split('\n')
    cleaned = []
    for line in lines:
        # 去除首尾空白
        line = line.strip()
        # 跳过空行
        if not line:
            continue
        # 跳过注释行（' 开头）
        if line.startswith("'"):
            continue
        # 跳过 @startuml / @enduml
        if line in ("@startuml", "@enduml"):
            continue
        # 跳过 skinparam 等配置行
        if line.startswith("skinparam") or line.startswith("left to right direction") or line.startswith("top to bottom direction"):
            continue
        cleaned.append(line)
    return cleaned


def parse_sequence_puml_regex(puml_code: str) -> dict:
    """解析时序图 PUML 代码（纯正则，无需 LLM）。

    返回格式：{"participants": ["A", "B"], "messages": [{"source": "A", "target": "B", "message": "msg"}]}
    """
    result = {"participants": [], "messages": []}
    participants_set = set()
    messages = []

    lines = _clean_puml_lines(puml_code)

    # 箭头模式：source -> target : message
    # 兼容箭头类型：->, -->, <-, <--, ->>, <<-, <->, 等
    arrow_pattern = re.compile(
        r"^(.+?)\s*(->|-->|<-|<--|->>|<-|<->|<-->|<-->)+\s*(.+?)\s*:\s*(.+)$"
    )

    # 参与者声明：participant "Name" as alias, actor Name, database Name
    participant_pattern = re.compile(
        r"^(participant|actor|database)\s+[\"']?(\w+)[\"']?\s+(?:as\s+)?(\w+)?",
        re.IGNORECASE
    )
    # 简化的参与者声明：participant Name
    simple_participant_pattern = re.compile(
        r"^(participant|actor|database)\s+(\w+)$",
        re.IGNORECASE
    )

    for line in lines:
        # 匹配参与者声明
        match = participant_pattern.match(line)
        if match:
            # 优先取别名，否则取名称
            alias = match.group(3) if match.group(3) else match.group(2)
            participants_set.add(alias)
            continue

        # 匹配简化的参与者声明
        match = simple_participant_pattern.match(line)
        if match:
            participants_set.add(match.group(2))
            continue

        # 匹配消息箭头
        match = arrow_pattern.match(line)
        if match:
            source = match.group(1).strip()
            target = match.group(3).strip()
            message = match.group(4).strip()
            messages.append({
                "source": source,
                "target": target,
                "message": message
            })
            # 自动添加参与者
            participants_set.add(source)
            participants_set.add(target)

    result["participants"] = list(participants_set)
    result["messages"] = messages
    return result


def parse_usecase_puml_regex(puml_code: str) -> dict:
    """解析用例图 PUML 代码（纯正则，无需 LLM）。

    返回格式：{"actors": [], "usecases": [], "entities": {"ActorA": ["Usecase1"]}}
    """
    result = {"actors": [], "usecases": [], "entities": {}}
    actors_set = set()
    usecases_set = set()
    associations = {}  # {actor: [usecase1, usecase2]}

    lines = _clean_puml_lines(puml_code)

    # actor 声明：actor ActorName
    actor_pattern = re.compile(r"^actor\s+[\"']?(\w+)[\"']?$", re.IGNORECASE)
    # 用例声明：(UsecaseName) 或 usecase "UsecaseName"
    usecase_pattern = re.compile(r"^\(([^)]+)\)$|^usecase\s+[\"']?(\w+)[\"']?$", re.IGNORECASE)
    # 连线关系：ActorA --> Usecase1, ActorA ---> (Usecase2)
    association_pattern = re.compile(
        r"^([\w]+)\s*-+-+\s*(?:\(([^)]+)\)|([\w]+))",
        re.IGNORECASE
    )

    for line in lines:
        # 匹配 actor
        match = actor_pattern.match(line)
        if match:
            actors_set.add(match.group(1))
            continue

        # 匹配用例（带括号的格式）
        match = usecase_pattern.match(line)
        if match:
            usecase_name = match.group(1) or match.group(2)
            usecases_set.add(usecase_name)
            continue

        # 匹配关联连线
        match = association_pattern.match(line)
        if match:
            actor = match.group(1)
            usecase = match.group(2) or match.group(3)
            if actor and usecase:
                if actor not in associations:
                    associations[actor] = []
                if usecase not in associations[actor]:
                    associations[actor].append(usecase)
                actors_set.add(actor)
                usecases_set.add(usecase)

    result["actors"] = list(actors_set)
    result["usecases"] = list(usecases_set)
    result["entities"] = associations
    return result


def parse_class_puml_regex(puml_code: str) -> dict:
    """解析类图 PUML 代码（纯正则，无需 LLM）。

    返回格式：{"classes": [{"name": "ClassA"}, {"name": "ClassB"}]}
    """
    result = {"classes": [], "class_details": {}, "class_relationships": {}}
    classes_set = set()

    lines = _clean_puml_lines(puml_code)

    # class 声明：class "Name" { 或 class Name {
    # 支持双引号、单引号、无引号
    class_pattern = re.compile(r"^class\s+[\"']?(\w+)[\"']?\s*\{?", re.IGNORECASE)

    for line in lines:
        match = class_pattern.match(line)
        if match:
            class_name = match.group(1)
            classes_set.add(class_name)

    # 转换为需要的格式
    result["classes"] = [{"name": name} for name in sorted(classes_set)]
    return result


def is_valid_parsed_data(model_type: str, parsed_data: dict) -> bool:
    """验证正则解析结果是否有效。

    Returns:
        True: 解析成功且数据有效
        False: 解析失败或数据为空，需要降级到 LLM
    """
    if not parsed_data:
        return False

    if model_type == "sequence":
        # 时序图：必须有参与者和消息
        participants = parsed_data.get("participants", [])
        messages = parsed_data.get("messages", [])
        return len(participants) > 0 or len(messages) > 0

    elif model_type == "usecase":
        # 用例图：至少要有 actors、usecases 或 entities
        actors = parsed_data.get("actors", [])
        usecases = parsed_data.get("usecases", [])
        entities = parsed_data.get("entities", {})
        return len(actors) > 0 or len(usecases) > 0 or len(entities) > 0

    elif model_type == "class":
        # 类图：至少要有一个类
        classes = parsed_data.get("classes", [])
        return len(classes) > 0

    return False
