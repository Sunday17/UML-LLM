# graph/workflow.py
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import UMLState
# 导入用例图 Agents
from agents.usecase_agents import extract_entities_node, extract_relationships_node
# 导入新增的类图 Agents
from agents.class_agents import extract_classes_node, extract_class_details_node, extract_class_rels_node

def route_start(state: UMLState):
    """根据当前指定的任务，进入对应的流水线"""
    diagram = state.get("current_diagram")
    if diagram == "usecase":
        return "entity_agent"
    elif diagram == "class":
        return "class_entity_agent"
    return END

def build_graph():
    """构建并编译 Multi-Agent 并行工作流"""
    workflow = StateGraph(UMLState)
    
    # --- 1. 注册用例图节点 ---
    workflow.add_node("entity_agent", extract_entities_node)
    workflow.add_node("relationship_agent", extract_relationships_node)
    
    # --- 2. 注册类图节点 ---
    workflow.add_node("class_entity_agent", extract_classes_node)
    workflow.add_node("class_attr_method_agent", extract_class_details_node)
    workflow.add_node("class_rel_agent", extract_class_rels_node)
    
    # 3. 从 START 路由到指定的流水线
    workflow.add_conditional_edges(
        START,
        route_start,
        {
            "entity_agent": "entity_agent",
            "class_entity_agent": "class_entity_agent",
            END: END
        }
    )
    
    # --- 4. 编排用例图内部边 ---
    workflow.add_edge("entity_agent", "relationship_agent")
    workflow.add_edge("relationship_agent", END)
    
    # --- 5. 编排类图内部边 ---
    workflow.add_edge("class_entity_agent", "class_attr_method_agent")
    workflow.add_edge("class_attr_method_agent", "class_rel_agent")
    workflow.add_edge("class_rel_agent", END)
    
    # --- 6. 开启记忆存储 (用于支持 Human-in-the-loop) ---
    memory = MemorySaver()
    app = workflow.compile(
        checkpointer=memory,
        # 拦截点：
        # 1. relationship_agent 前 (确认用例实体)
        # 2. class_attr_method_agent 前 (确认类实体)
        interrupt_before=["relationship_agent", "class_attr_method_agent"] 
    )
    
    return app