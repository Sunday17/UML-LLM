# agents/sequence_agents.py
import json
from graph.state import UMLState
from utils.llm import openai_reasoning_completion,openai_chat_completion
from prompts.templates import get_template
from tools.extract_json_from_response import extract_json_from_response

def extract_seq_participants_node(state: UMLState) -> dict:
    """Agent 6: 为每个用例提取参与者"""
    print("\n======== [时序图-Agent 1] 正在提取各用例交互参与者 ========")
    usecases = state.get("usecases", [])
    actors = state.get("actors", [])
    classes = state.get("classes", [])
    
    sequence_data = state.get("sequence_data", {})
    prompt_tpl = get_template("sd_participant_prompt", "")
    
    for uc in usecases:
        print(f"  -> 分析用例参与者: [{uc}]")
        prompt = prompt_tpl.format(current_usecase=uc, actors=actors, classes=classes)
        # 这里用 reasoning 或 chat 模型均可
        res = openai_chat_completion(
            "你是一个UML专家",
            [{"role": "user", "content": prompt}],
        )
        try:
            clean_json_str = extract_json_from_response(res)
            data = json.loads(clean_json_str)
        except Exception as e:
            print(f"❌ 参与者 JSON 解析失败: {e}")
            data = {}
        
        if uc not in sequence_data:
            sequence_data[uc] = {}
        sequence_data[uc]["participants"] = data.get("participants", [])
        
    return {"sequence_data": sequence_data}

def extract_seq_messages_node(state: UMLState) -> dict:
    """Agent 7: 为每个用例编排消息序列"""
    print("\n======== [时序图-Agent 2] 正在编排时间线交互消息 ========")
    sequence_data = state.get("sequence_data", {})
    prompt_tpl = get_template("sd_message_prompt", "")
    
    for uc, data in sequence_data.items():
        print(f"  -> 编排交互消息: [{uc}]")
        participants = data.get("participants", [])
        if not participants:
            continue
            
        prompt = prompt_tpl.format(current_usecase=uc, participants=participants)
        res = openai_reasoning_completion(prompt)
        try:
            clean_json_str = extract_json_from_response(res)
            msg_data = json.loads(clean_json_str)
        except Exception as e:
            print(f"❌ 时序消息 JSON 解析失败: {e}")
            msg_data = {}
        
        sequence_data[uc]["interactions"] = msg_data.get("interactions", [])
        
    print("✅ 所有用例时序图数据组装完成！")
    return {"sequence_data": sequence_data}