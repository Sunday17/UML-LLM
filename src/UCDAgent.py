import llm_utils as llm_utils
import json
import re

class UCDAgent:
    def __init__(self, input_text):
        self.input_text = input_text
        self.actors = []
        self.usecases = []
        self.association_relationships = {} 
        self.inclusion_relationships = {}    
        self.extension_relationships = {}    
        self.generalization_relationships_for_usecases = {} 
        self.generalization_relationships_for_actors = {}   

    def extract_entities(self):
        """[第一步] 智能体 1：合并提取角色与用例"""
        print("======== [1/3] 正在提取实体 (极速模式) ========")
        
        try:
            with open("../prompts/ee_template.txt", encoding='utf-8') as f:
                prompt_tpl = f.read()
        except:
            prompt_tpl = "从文本中提取角色和用例，JSON格式输出：{{\"角色\":[\"用例\"]}}。文本：{input_text}"

        prompt = prompt_tpl.format(input_text=self.input_text)
        system_msg = "你是一个 UML 需求分析助手。请将需求中的参与者和用例提取为 JSON 格式。"
        
        res = llm_utils.openai_chat_completion(
            system_prompt=system_msg, 
            history=[{"role": "user", "content": prompt}],
        )
        
        try:
            data = json.loads(res)
            if data:
                # 暂时保存提取结果，供用户修正
                self._apply_entity_data(data)
                print(f"✅ 自动提取成功: {len(self.actors)}角色 / {len(self.usecases)}用例")
                return data
        except Exception as e:
            print(f"❌ 实体解析失败: {e} \n原始输出: {res[:100]}...")
            return None

    def update_corrected_entities(self, corrected_data):
        """[第二步] 接收用户修正后的数据并更新类内部状态"""
        print("======== [2/3] 正在应用用户修正的实体数据 ========")
        try:
            if isinstance(corrected_data, str):
                corrected_data = json.loads(corrected_data)
                
            self._apply_entity_data(corrected_data)
            print(f"✅ 修正数据已应用: 当前 {len(self.actors)}角色 / {len(self.usecases)}用例")
            return True
        except Exception as e:
            print(f"❌ 修正数据解析或应用失败: {e}")
            return False

    def _apply_entity_data(self, data):
        """内部辅助方法：统一处理实体数据的赋值"""
        self.association_relationships = data
        self.actors = list(data.keys())
        uc_set = set()
        for ucs in data.values(): 
            uc_set.update(ucs)
        self.usecases = list(uc_set)

    def extract_relationships(self):
        """[第三步] 智能体 2：基于（已修正的）实体分析逻辑关系"""
        print("======== [3/3] 正在分析逻辑关系 ========")
        if not self.usecases: 
            print("❌ 缺少用例数据，无法提取关系。")
            return

        try:
            with open("../prompts/era_template.txt", encoding='utf-8') as f:
                era_tpl = f.read()
        except:
            era_tpl = "基于以下角色{actors}和用例{usecases}，从文本提取关系。文本：{input_text}"
            
        prompt = era_tpl.format(
            input_text=self.input_text, 
            actors=self.actors, 
            usecases=self.usecases
        )

        res = llm_utils.openai_chat_completion(
            system_prompt="你是一个只输出JSON的UML分析专家", 
            history=[{"role": "user", "content": prompt}],
        )
        
        try:
            match = re.search(r'(\{.*\})', res, re.DOTALL)
            data = json.loads(match.group(1)) if match else json.loads(res)
            
            self.generalization_relationships_for_actors = self._to_dict(data.get("actor_generalization", []))
            self.generalization_relationships_for_usecases = self._to_dict(data.get("uc_generalization", []))
            self.inclusion_relationships = self._to_dict(data.get("include", []))
            self.extension_relationships = self._to_dict(data.get("extend", []))
            print("✅ 逻辑关系解析成功")
        except Exception as e:
            print(f"❌ 关系解析失败: {e}")

    def _to_dict(self, pair_list):
        d = {}
        for p, c in pair_list:
            d.setdefault(p, []).append(c)
        return d

    def clean_redundant_relationships(self):
        covered_ucs = set()
        for l in self.inclusion_relationships.values(): covered_ucs.update(l)
        for l in self.extension_relationships.values(): covered_ucs.update(l)
        for l in self.generalization_relationships_for_usecases.values(): covered_ucs.update(l)
        
        for actor in self.association_relationships:
            self.association_relationships[actor] = [
                uc for uc in self.association_relationships[actor] if uc not in covered_ucs
            ]

    def generate_diagram(self, path):
        lines = ["@startuml", "left to right direction", "skinparam packageStyle rectangle"]
        for a in self.actors: lines.append(f'actor "{a}"')
        for u in self.usecases: lines.append(f'usecase "{u}"')
        
        for a, ucs in self.association_relationships.items():
            for u in ucs: lines.append(f'"{a}" -- "{u}"')
        for b, ts in self.inclusion_relationships.items():
            for t in ts: lines.append(f'"{b}" ..> "{t}" : <<include>>')
        for b, ts in self.extension_relationships.items():
            for t in ts: lines.append(f'"{b}" <.. "{t}" : <<extend>>')
        for p, cs in self.generalization_relationships_for_usecases.items():
            for c in cs: lines.append(f'"{c}" --|> "{p}"')
        for p, cs in self.generalization_relationships_for_actors.items():
            for c in cs: lines.append(f'"{c}" --|> "{p}"')
            
        lines.append("@enduml")
        with open(path, "w", encoding='utf-8') as f:
            f.write("\n".join(lines))
        print(f"🎉 任务完成！文件已保存至: {path}")

    def save_to_json(self, path):
        data = {
            "actors": self.actors, "usecases": self.usecases,
            "relationships": {
                "inclusion": self.inclusion_relationships,
                "extension": self.extension_relationships,
                "uc_gen": self.generalization_relationships_for_usecases,
                "act_gen": self.generalization_relationships_for_actors,
                "association": self.association_relationships
            }
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)