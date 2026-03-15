import json
import re
from graph.state import UCDState
from utils.llm import openai_chat_completion
from prompts.templates import get_template

def extract_relationships_node(state: UCDState) -> dict:
    """Agent 2: 负责分析实体之间的 UML 关系"""
    print("======== [Agent 2] 正在分析逻辑关系 ========")
    if not state.get("usecases"):
        print("❌ 缺少用例数据，无法提取关系。")
        return {"relationships": {}}

    fallback = "基于以下角色{actors}和用例{usecases}，从文本提取关系。文本：{input_text}"
    era_tpl = get_template("era_template", fallback)
        
    prompt = era_tpl.format(
        input_text=state["input_text"], 
        actors=state["actors"], 
        usecases=state["usecases"]
    )

    res = openai_chat_completion(
        system_prompt="你是一个只输出JSON的UML分析专家", 
        history=[{"role": "user", "content": prompt}]
    )
    
    try:
        match = re.search(r'(\{.*\})', res, re.DOTALL)
        data = json.loads(match.group(1)) if match else json.loads(res)
        print("✅ 逻辑关系解析成功")
        return {"relationships": data}
    except Exception as e:
        print(f"❌ 关系解析失败: {e}")
        return {"relationships": {}}