import json

def _to_dict(pair_list):
    """将 [["A","B"]] 转为 {"A":["B"]}"""
    d = {}
    if pair_list:
        for p, c in pair_list:
            d.setdefault(p, []).append(c)
    return d

def generate_outputs(state: dict, json_path: str, puml_path: str):
    """生成最终产物：修复了连线丢失问题并优化了 UML 语法方向"""
    entities = state.get("entities", {})
    actors = state.get("actors", [])
    usecases = state.get("usecases", [])
    rels = state.get("relationships", {})

    # 1. 提取各类关系
    act_gen = _to_dict(rels.get("actor_generalization", []))
    uc_gen = _to_dict(rels.get("uc_generalization", []))
    include_rels = _to_dict(rels.get("include", []))
    extend_rels = _to_dict(rels.get("extend", []))

    # 2. 【核心修改】取消冗余清理逻辑
    # 不再从 entities 中移除被包含或被扩展的用例，确保用户与核心功能的连线完整
    cleaned_association = entities 

    # 3. 保存 JSON 数据
    data = {
        "actors": actors, 
        "usecases": usecases,
        "relationships": {
            "inclusion": include_rels, 
            "extension": extend_rels,
            "uc_gen": uc_gen, 
            "act_gen": act_gen,
            "association": cleaned_association
        }
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    # 4. 生成 PlantUML
    lines = ["@startuml", "left to right direction", "skinparam packageStyle rectangle"]
    
    # 定义实体
    for a in actors: 
        lines.append(f'actor "{a}"')
    for u in usecases: 
        lines.append(f'usecase "{u}"')
    
    # 建立参与者与用例的关联线 (Association)
    for actor, ucs in cleaned_association.items():
        for uc in ucs:
            lines.append(f'"{actor}" -- "{uc}"')
            
    # 建立包含关系 (Include)：基础用例 ..> 被包含用例
    for base, target_list in include_rels.items():
        for target in target_list:
            lines.append(f'"{base}" ..> "{target}" : <<include>>')
            
    # 建立扩展关系 (Extend)：扩展用例 ..> 基础用例
    # 注意：在 UML 中箭头是从“扩展点”指向“基础用例”，或使用 <.. 标明关系
    for base, extension_list in extend_rels.items():
        for ext in extension_list:
            lines.append(f'"{ext}" ..> "{base}" : <<extend>>')
            
    # 建立用例泛化关系 (Generalization)
    for parent, children in uc_gen.items():
        for child in children:
            lines.append(f'"{child}" --|> "{parent}"')
            
    # 建立参与者泛化关系
    for parent, children in act_gen.items():
        for child in children:
            lines.append(f'"{child}" --|> "{parent}"')
        
    lines.append("@enduml")
    
    # 写入文件
    with open(puml_path, "w", encoding='utf-8') as f:
        f.write("\n".join(lines))
        
    print(f"🎉 任务完成！连线已修复。结果已保存至 \n- {json_path}\n- {puml_path}")