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


def _build_rag_context(state: UMLState, extra_context: str = "") -> str:
    """构建 RAG 上下文字符串"""
    if not RAG_ENABLED:
        return ""

    project_id = state.get("project_id")
    original_requirement = state.get("original_requirement", "")
    module_requirements = state.get("input_text", "")

    if not project_id or not original_requirement:
        return ""

    # 合并额外上下文（如当前用例名称）
    query = module_requirements
    if extra_context:
        query = f"{module_requirements} - {extra_context}"

    try:
        context = vector_store.retrieve_with_context(
            module_requirements=query,
            project_id=project_id,
            top_k=RAG_TOP_K,
        )
        return context
    except Exception as e:
        logger.warning(f"[RAG] Failed to retrieve context: {e}")
        return ""


def extract_seq_participants_node(state: UMLState) -> dict:
    """Agent 6: 为选中的用例提取参与者（支持 RAG）

    注意：只使用已确认的角色和类作为参与者候选。
    """
    print("======== [Seq-Agent-1] extracting participants ========")
    input_text = state.get("input_text", "")
    actors = state.get("actors", [])
    classes = state.get("classes", [])
    sequence_data = state.get("sequence_data", {})

    # 仅处理被选中的用例
    target_usecases = state.get("selected_usecases", [])
    if not target_usecases:
        print("[WARN] no selected_usecases, skip participant extraction")
        return {"sequence_data": sequence_data}

    # MOCK 模式：返回固定参与者数据
    if MOCK_MODE:
        print("[MOCK] extract_seq_participants_node")
        mock_participants = {
            "在线挂号": [
                {"name": "Patient", "type": "actor"},
                {"name": "挂号界面2", "type": "boundary"},
                {"name": "挂号服务", "type": "control"},
                {"name": "医生", "type": "entity"},
            ],
            "查询就诊": [
                {"name": "Patient", "type": "actor"},
                {"name": "查询界面", "type": "boundary"},
                {"name": "预约服务", "type": "control"},
            ],
            "选择科室": [
                {"name": "Patient", "type": "actor"},
                {"name": "科室选择界面", "type": "boundary"},
                {"name": "科室服务", "type": "control"},
            ],
            "查看医生信息": [
                {"name": "Patient", "type": "actor"},
                {"name": "医生界面", "type": "boundary"},
                {"name": "医生服务", "type": "control"},
            ],
            "管理号源": [
                {"name": "Admin", "type": "actor"},
                {"name": "排班界面", "type": "boundary"},
                {"name": "排班服务", "type": "control"},
            ],
        }
        for uc in target_usecases:
            if uc in mock_participants:
                sequence_data[uc] = {"participants": mock_participants[uc]}
            else:
                sequence_data[uc] = {"participants": []}
        return {"sequence_data": sequence_data}

    prompt_tpl = get_template("sd_participant_prompt", "")

    for uc in target_usecases:
        print(f"  -> analyzing participants for: [{uc}]")
        prompt_base = prompt_tpl.format(
            input_text=input_text,
            current_usecase=uc,
            actors=actors,
            classes=classes,
        )

        # 使用 RAG 增强 Prompt
        if RAG_ENABLED and state.get("project_id"):
            rag_context = _build_rag_context(state, extra_context=f"用例: {uc}")
            if rag_context:
                prompt = f"{rag_context}\n[当前用例需求]\n{prompt_base}"
            else:
                prompt = prompt_base
        else:
            prompt = prompt_base

        try:
            res = openai_chat_completion(
                "你是一个资深的软件系统架构师，精通UML时序图设计与系统解耦。",
                [{"role": "user", "content": prompt}],
            )
        except Exception as e:
            print(f"[ERROR] LLM call failed for {uc}: {e}")
            data = {}
        else:
            try:
                data = parse_json_from_response(res)
            except Exception as e:
                print(f"[ERROR] participant JSON parse failed for {uc}: {e}")
                data = {}

        if uc not in sequence_data:
            sequence_data[uc] = {}
        sequence_data[uc]["participants"] = data.get("participants", [])

    return {"sequence_data": sequence_data}


def extract_seq_messages_node(state: UMLState) -> dict:
    """Agent 7: 为选中的用例编排消息序列（支持 RAG）"""
    print("======== [Seq-Agent-2] arranging interaction messages ========")
    input_text = state.get("input_text", "")
    sequence_data = state.get("sequence_data", {})

    # 仅处理被选中的用例
    target_usecases = state.get("selected_usecases", [])
    if not target_usecases:
        print("[WARN] no selected_usecases, skip message extraction")
        return {"sequence_data": sequence_data}

    # MOCK 模式：返回固定消息数据
    if MOCK_MODE:
        print("[MOCK] extract_seq_messages_node")
        mock_interactions = {
            "在线挂号": [
                {"source": "Patient", "target": "挂号界面", "action": "选择科室和医生", "is_return": False},
                {"source": "挂号界面", "target": "挂号服务", "action": "提交挂号请求", "is_return": False},
                {"source": "挂号服务", "target": "医生", "action": "检查医生排班", "is_return": False},
                {"source": "医生", "target": "挂号服务", "action": "返回可用号源", "is_return": True},
                {"source": "挂号服务", "target": "挂号界面", "action": "确认挂号成功", "is_return": True},
                {"source": "挂号界面", "target": "Patient", "action": "显示挂号结果", "is_return": True},
            ],
            "查询就诊": [
                {"source": "Patient", "target": "查询界面", "action": "输入查询条件", "is_return": False},
                {"source": "查询界面", "target": "预约服务", "action": "查询就诊信息", "is_return": False},
                {"source": "预约服务", "target": "查询界面", "action": "返回查询结果", "is_return": True},
                {"source": "查询界面", "target": "Patient", "action": "展示就诊信息", "is_return": True},
            ],
            "选择科室": [
                {"source": "Patient", "target": "科室选择界面", "action": "查看科室列表", "is_return": False},
                {"source": "科室选择界面", "target": "科室服务", "action": "获取科室信息", "is_return": False},
                {"source": "科室服务", "target": "科室选择界面", "action": "返回科室列表", "is_return": True},
                {"source": "科室选择界面", "target": "Patient", "action": "展示科室", "is_return": True},
            ],
            "查看医生信息": [
                {"source": "Patient", "target": "医生界面", "action": "搜索医生", "is_return": False},
                {"source": "医生界面", "target": "医生服务", "action": "查询医生信息", "is_return": False},
                {"source": "医生服务", "target": "医生界面", "action": "返回医生详情", "is_return": True},
                {"source": "医生界面", "target": "Patient", "action": "展示医生信息", "is_return": True},
            ],
            "管理号源": [
                {"source": "Admin", "target": "排班界面", "action": "查看排班表", "is_return": False},
                {"source": "排班界面", "target": "排班服务", "action": "获取排班数据", "is_return": False},
                {"source": "排班服务", "target": "排班界面", "action": "返回排班信息", "is_return": True},
                {"source": "Admin", "target": "排班服务", "action": "修改号源设置", "is_return": False},
                {"source": "排班服务", "target": "Admin", "action": "保存成功", "is_return": True},
            ],
        }
        for uc in target_usecases:
            if uc in sequence_data and uc in mock_interactions:
                sequence_data[uc]["interactions"] = mock_interactions[uc]
            elif uc in sequence_data:
                sequence_data[uc]["interactions"] = []
        print("[OK] all sequence diagram data assembled")
        return {"sequence_data": sequence_data}

    prompt_tpl = get_template("sd_message_prompt", "")

    for uc in target_usecases:
        print(f"  -> arranging messages for: [{uc}]")
        uc_data = sequence_data.get(uc, {})
        participants = uc_data.get("participants", [])

        if not participants:
            continue

        prompt_base = prompt_tpl.format(
            input_text=input_text,
            current_usecase=uc,
            participants=participants,
        )

        # 使用 RAG 增强 Prompt
        if RAG_ENABLED and state.get("project_id"):
            rag_context = _build_rag_context(state, extra_context=f"用例: {uc}")
            if rag_context:
                prompt = f"{rag_context}\n[当前用例需求]\n{prompt_base}"
            else:
                prompt = prompt_base
        else:
            prompt = prompt_base

        try:
            #res = openai_reasoning_completion(prompt)
            res = openai_chat_completion(prompt,[])
        except Exception as e:
            print(f"[ERROR] LLM call failed for {uc}: {e}")
            msg_data = {}
        else:
            try:
                msg_data = parse_json_from_response(res)
            except Exception as e:
                print(f"[ERROR] message JSON parse failed for {uc}: {e}")
                msg_data = {}

        sequence_data[uc]["interactions"] = msg_data.get("interactions", [])

    print("[OK] all sequence diagram data assembled")
    return {"sequence_data": sequence_data}