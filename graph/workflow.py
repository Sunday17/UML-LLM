from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import UCDState
from agents.entity_agent import extract_entities_node
from agents.rel_agent import extract_relationships_node

def build_graph():
    """构建并编译 Multi-Agent 工作流"""
    workflow = StateGraph(UCDState)
    
    # 1. 注册智能体节点
    workflow.add_node("entity_agent", extract_entities_node)
    workflow.add_node("relationship_agent", extract_relationships_node)
    
    # 2. 编排边 (路由)
    workflow.add_edge(START, "entity_agent")
    workflow.add_edge("entity_agent", "relationship_agent")
    workflow.add_edge("relationship_agent", END)
    
    # 3. 开启记忆存储 (用于支持 Human-in-the-loop 断点)
    memory = MemorySaver()
    app = workflow.compile(
        checkpointer=memory,
        interrupt_before=["relationship_agent"]  # 在关系提取前挂起
    )
    
    return app