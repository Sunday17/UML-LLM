import json
import re
import logging
from core.langgraph.state import UMLState
from services.llm import openai_chat_completion, openai_reasoning_completion
from core.prompts.templates import get_template
from services.vector_store import vector_store

logger = logging.getLogger(__name__)

# ================================================================
# MOCK 模式开关（调试时设为 True，跳过 LLM 调用）
# ================================================================
MOCK_MODE = False  

# RAG 配置
RAG_TOP_K = 3  # 检索的相关段落数量
RAG_ENABLED = True  # RAG 功能开关


def _build_rag_context(state: UMLState) -> str:
    """构建 RAG 上下文字符串"""
    if not RAG_ENABLED:
        return ""

    project_id = state.get("project_id")
    original_requirement = state.get("original_requirement", "")
    module_requirements = state.get("input_text", "")

    if not project_id or not original_requirement:
        return ""

    try:
        context = vector_store.retrieve_with_context(
            module_requirements=module_requirements,
            project_id=project_id,
            top_k=RAG_TOP_K,
        )
        return context
    except Exception as e:
        logger.warning(f"[RAG] Failed to retrieve context: {e}")
        return ""


def _enhance_prompt_with_rag(prompt_base: str, state: UMLState) -> str:
    """使用 RAG 上下文增强 Prompt"""
    rag_context = _build_rag_context(state)

    if not rag_context:
        return prompt_base

    return (
        f"{rag_context}\n"
        f"[当前模块需求]\n"
        f"{prompt_base}"
    )


def extract_entities_node(state: UMLState) -> dict:
    """Agent 1: 负责从需求文本中提取角色和用例（支持 RAG）

    注意：如果用户已确认过角色/用例列表，禁止添加新实体。
    """
    print("======== [Agent 1] extracting entities ========")
    input_text = state["input_text"]

    # 如果用户已经确认过角色/用例，直接使用确认的列表，禁止添加新实体
    confirmed_actors = state.get("confirmed_actors")
    confirmed_usecases = state.get("confirmed_usecases")
    
    if confirmed_actors or confirmed_usecases:
        print(f"[INFO] Using confirmed entities (no additions allowed)")
        result = {"entities": {}, "actors": confirmed_actors or [], "usecases": confirmed_usecases or []}
        # 如果只有部分确认，构建 entities 映射
        if confirmed_actors:
            for actor in confirmed_actors:
                result["entities"][actor] = confirmed_usecases or []
        return result

    # MOCK 模式：返回固定数据
    if MOCK_MODE:
        print("[MOCK] extract_entities_node")
        return {
            "actors": ["患者", "管理员"],
            "entities": {
                "患者": ["选择科室", "在线挂号", "查询就诊", "查看医生信息"],
                "管理员": ["管理号源"]
            },
            "usecases": ["选择科室", "在线挂号", "查询就诊", "查看医生信息", "管理号源"]
        }

    fallback = "从文本中提取角色和用例，JSON格式输出：{{\"角色\":[\"用例\"]}}。文本：{input_text}"
    prompt_tpl = get_template("ee_template", fallback)
    prompt_base = prompt_tpl.format(input_text=input_text)

    # 使用 RAG 增强 Prompt
    if RAG_ENABLED and state.get("project_id"):
        prompt = _enhance_prompt_with_rag(prompt_base, state)
    else:
        prompt = prompt_base

    system_msg = "你是一个 UML 需求分析助手。请将需求中的参与者和用例提取为 JSON 格式。"

    try:
        res = openai_chat_completion(
            system_prompt=system_msg,
            history=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        return {"entities": {}, "actors": [], "usecases": []}

    try:
        data = json.loads(res)
        actors = list(data.keys())
        uc_set = set()
        for ucs in data.values():
            uc_set.update(ucs)
        usecases = list(uc_set)

        print(f"[OK] entities extracted: {len(actors)} actors / {len(usecases)} usecases")
        return {"entities": data, "actors": actors, "usecases": usecases}
    except Exception as e:
        print(f"[ERROR] entity parsing failed: {e}")
        return {"entities": {}, "actors": [], "usecases": []}


def extract_relationships_node(state: UMLState) -> dict:
    """Agent 2: 负责分析实体之间的 UML 关系（支持 RAG）

    注意：只分析涉及已确认角色/用例的关系。
    """
    print("======== [Agent 2] analyzing relationships ========")

    # MOCK 模式：返回固定数据
    if MOCK_MODE:
        print("[MOCK] extract_relationships_node")
        return {"relationships": {}}

    if not state.get("usecases"):
        print("[WARN] no usecases, skip relationship extraction")
        return {"relationships": {}}

    # 获取用户确认的列表
    confirmed_actors = state.get("confirmed_actors")
    confirmed_usecases = state.get("confirmed_usecases")
    
    # 过滤到确认的列表
    actors = state["actors"]
    usecases = state["usecases"]
    
    if confirmed_actors:
        actors = [a for a in actors if a in confirmed_actors]
    if confirmed_usecases:
        usecases = [u for u in usecases if u in confirmed_usecases]
    
    print(f"[INFO] Analyzing relationships for {len(actors)} actors / {len(usecases)} usecases")

    fallback = "基于以下角色{actors}和用例{usecases}，从文本提取关系。文本：{input_text}"
    era_tpl = get_template("era_template", fallback)

    prompt_base = era_tpl.format(
        input_text=state["input_text"],
        actors=actors,
        usecases=usecases,
    )

    # 使用 RAG 增强 Prompt
    if RAG_ENABLED and state.get("project_id"):
        prompt = _enhance_prompt_with_rag(prompt_base, state)
    else:
        prompt = prompt_base

    try:
        res = openai_chat_completion(
            system_prompt="你是一个只输出JSON的UML分析专家",
            history=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        return {"relationships": {}}

    try:
        match = re.search(r'(\{.*\})', res, re.DOTALL)
        data = json.loads(match.group(1)) if match else json.loads(res)
        
        # 过滤：只保留涉及确认实体的关系
        if confirmed_actors or confirmed_usecases:
            confirmed_set = set()
            if confirmed_actors:
                confirmed_set.update(confirmed_actors)
            if confirmed_usecases:
                confirmed_set.update(confirmed_usecases)

            for key, rel_list in data.items():
                if isinstance(rel_list, list):
                    filtered = []
                    for rel in rel_list:
                        if isinstance(rel, list) and len(rel) >= 2:
                            # 关系对中的所有实体都必须在确认列表中
                            keep = all(item in confirmed_set for item in rel)
                        elif isinstance(rel, str):
                            # 字符串格式的关系
                            parts = rel.replace("->", " ").replace("<-", " ").split()
                            keep = all(p in confirmed_set for p in parts)
                        else:
                            keep = False

                        if keep:
                            filtered.append(rel)
                    data[key] = filtered
        
        print("[OK] relationships parsed")
        return {"relationships": data}
    except Exception as e:
        print(f"[ERROR] relationship parsing failed: {e}")
        return {"relationships": {}}