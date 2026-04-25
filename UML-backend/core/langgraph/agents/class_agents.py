import json
import logging
from core.langgraph.state import UMLState
from services.llm import openai_reasoning_completion, openai_chat_completion
from core.prompts.templates import get_template
from core.langgraph.tools.extract_json_from_response import parse_json_from_response
from services.vector_store import vector_store

logger = logging.getLogger(__name__)

# ================================================================
# MOCK 模式开关（调试时设为 True，跳过 LLM 调用）
# ================================================================
MOCK_MODE = False  # TODO: 调试完成后改为 False

# RAG 配置
RAG_TOP_K = 3  # 检索的相关段落数量
RAG_ENABLED = True  # RAG 功能开关


def _build_rag_context(state: UMLState) -> str:
    """构建 RAG 上下文字符串

    从原始需求中检索与当前模块相关的段落，
    格式化为可插入 Prompt 的字符串。
    """
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


def _enhance_prompt_with_rag(prompt_template: str, state: UMLState) -> str:
    """使用 RAG 上下文增强 Prompt"""
    rag_context = _build_rag_context(state)

    if not rag_context:
        return prompt_template

    return (
        f"{rag_context}\n"
        f"[当前模块需求]\n"
        f"{prompt_template}"
    )


def extract_classes_node(state: UMLState) -> dict:
    """Agent 3: 负责从需求中提取实体类（支持 RAG）

    注意：如果 state 中已有 confirmed_classes，说明用户已确认过实体列表，
    此时应直接返回确认的列表，禁止添加新类。
    """
    print("======== [Class-Agent-1] extracting classes ========")
    input_text = state["input_text"]

    # 如果用户已经确认过类名，直接使用确认的列表，禁止添加新类
    confirmed_classes = state.get("confirmed_classes")
    if confirmed_classes:
        print(f"[INFO] Using confirmed classes (no additions allowed): {confirmed_classes}")
        return {"classes": confirmed_classes}

    # MOCK 模式：返回固定数据
    if MOCK_MODE:
        print("[MOCK] extract_classes_node")
        return {"classes": ["Book", "User", "Loan"]}

    fallback = '从文本提取核心实体类，JSON输出 {"classes":[]}'
    prompt_tpl = get_template("cd_entity_prompt", fallback)

    # 使用 RAG 增强 Prompt
    if RAG_ENABLED and state.get("project_id"):
        prompt = prompt_tpl.format(input_text=input_text, classes=[])
        prompt = _enhance_prompt_with_rag(prompt, state)
    else:
        prompt = prompt_tpl.format(input_text=input_text, classes=[])

    try:
        #res = openai_reasoning_completion(prompt)
        res = openai_chat_completion(prompt,[])
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        return {"classes": []}

    try:
        data = parse_json_from_response(res)
        classes = data.get("classes", [])
        print(f"[OK] classes extracted: {classes}")
        return {"classes": classes}
    except Exception as e:
        print(f"[ERROR] class extraction failed: {e}")
        return {"classes": []}


def extract_class_details_node(state: UMLState) -> dict:
    """Agent 4: 负责提取每个类的属性和方法（支持 RAG）

    注意：如果用户已确认类名列表，只为列表中的类提取属性和方法。
    """
    print("======== [Class-Agent-2] extracting attributes/methods ========")

    # MOCK 模式：返回固定数据
    if MOCK_MODE:
        print("[MOCK] extract_class_details_node")
        return {
            "class_details": {
                "Book": {
                    "attributes": ["- title", "- author", "- ISBN", "- available"],
                    "methods": ["+ getInfo()", "+ checkAvailability()"]
                },
                "User": {
                    "attributes": ["- name", "- userID", "- currentLoans"],
                    "methods": ["+ borrowBook()", "+ returnBook()"]
                },
                "Loan": {
                    "attributes": ["- loanID", "- userID", "- bookID", "- borrowDate", "- dueDate", "- returnDate"],
                    "methods": ["+ create()", "+ complete()"]
                }
            }
        }

    classes = state.get("classes", [])
    # 获取用户确认的类名列表（如果存在）
    confirmed_classes = state.get("confirmed_classes")
    
    # 如果有确认列表，过滤只保留确认的类
    if confirmed_classes:
        classes = [c for c in classes if c in confirmed_classes]
        print(f"[INFO] Filtering to confirmed classes: {classes}")
    
    if not classes:
        print("[WARN] no classes found, skip attribute/method extraction")
        return {"class_details": {}}

    prompt_tpl = get_template(
        "cd_attr_method_prompt",
        '{"class_details":{"ClassName":{"attributes":[],"methods":[]}}}',
    )
    prompt_base = prompt_tpl.format(input_text=state["input_text"], classes=classes)

    # 使用 RAG 增强 Prompt
    if RAG_ENABLED and state.get("project_id"):
        prompt = _enhance_prompt_with_rag(prompt_base, state)
    else:
        prompt = prompt_base

    try:
        res = openai_chat_completion(prompt,[])
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        return {"class_details": {}}

    try:
        data = parse_json_from_response(res)
        details = data.get("class_details", {})
        # 过滤：只保留确认列表中的类的属性
        if confirmed_classes:
            details = {k: v for k, v in details.items() if k in confirmed_classes}
        print(f"[OK] attributes/methods extracted for {len(details)} classes")
        return {"class_details": details}
    except Exception as e:
        print(f"[ERROR] attribute/method extraction failed: {e}")
        return {"class_details": {}}


def extract_class_rels_node(state: UMLState) -> dict:
    """Agent 5: 负责分析类之间的 UML 关系（支持 RAG）

    注意：如果用户已确认类名列表，只输出涉及确认类之间的关系。
    """
    print("======== [Class-Agent-3] analyzing class relationships ========")

    # MOCK 模式：返回固定数据
    if MOCK_MODE:
        print("[MOCK] extract_class_rels_node")
        return {
            "class_relationships": {
                "association": [
                    "Book -- Loan",
                    "User -- Loan"
                ]
            }
        }

    classes = state.get("classes", [])
    confirmed_classes = state.get("confirmed_classes")


    
    if len(classes) < 2:
        print("[WARN] less than 2 classes, skip relationship analysis")
        return {"class_relationships": {}}

    prompt_tpl = get_template(
        "cd_rel_prompt",
        '{"association":[],"generalization":[],"composition":[],"aggregation":[],"dependency":[]}',
    )
    prompt_base = prompt_tpl.format(input_text=state["input_text"], classes=classes)

    # 使用 RAG 增强 Prompt
    if RAG_ENABLED and state.get("project_id"):
        prompt = _enhance_prompt_with_rag(prompt_base, state)
    else:
        prompt = prompt_base

    try:
        #res = openai_reasoning_completion(prompt)
        res = openai_chat_completion(prompt,[])
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        return {"class_relationships": {}}

    #print(f"[DEBUG] LLM raw response: {res[:500]}")

    try:
        data = json.loads(res.strip())
        #print(f"[DEBUG] Direct json.loads succeeded: {type(data)}")
    except Exception as e1:
        #print(f"[DEBUG] Direct json.loads failed: {e1}, trying parse_json_from_response...")
        try:
            data = parse_json_from_response(res)
            #print(f"[DEBUG] parse_json_from_response result: {data}")
        except Exception as e2:
            print(f"[ERROR] All JSON parsing failed: {e2}")
            return {"class_relationships": {}}

    relationships = data.get("class_relationships", {}) if isinstance(data, dict) else {}
    # 如果 class_relationships 不存在，但 data 本身包含关系字段，直接使用 data
    if not relationships and isinstance(data, dict):
        # 检查 data 是否直接包含关系字段
        rel_keys = {"association", "generalization", "composition", "aggregation", "dependency"}
        if rel_keys & set(data.keys()):
            relationships = data
    #print(f"[DEBUG] Parsed relationships: {relationships}")
    print("[OK] class relationships parsed")
    return {"class_relationships": relationships}