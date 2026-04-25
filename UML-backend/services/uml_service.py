"""services/uml_service.py — UML 生成服务（Human-in-the-Loop + RAG）。

工作流：
1. run_extract()       启动 LangGraph，在断点处自动暂停，返回中间态 JSON
2. resume_and_generate() 合并用户确认数据，续跑图，渲染 PUML，返回代码和图片
3. sync_from_puml()    接收 PUML 代码，逆向解析为 JSON，重新渲染
4. get_missing_dependencies() 序列图专用：检查 usecase/class 是否已生成

RAG 支持：
- 在模块生成 UML 时，会自动从原始需求中检索相关段落作为上下文
- 自动从上传的 PDF/TXT 文件中提取文本内容建立索引
"""

from typing import Any, Optional
import os

from jinja2 import Environment, FileSystemLoader

from core.langgraph.workflow import build_graph
from utils.puml_renderer import render_puml_to_url
from core.langgraph.tools.puml_parser import (
    sync_puml_to_state,
    parse_sequence_puml_regex,
    parse_usecase_puml_regex,
    parse_class_puml_regex,
    is_valid_parsed_data,
)
from services.database import database_service
from services.vector_store import vector_store

# Jinja2 模板目录（core/templates/puml/）
_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "core", "templates", "puml"
)
_puml_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR)) if os.path.isdir(_TEMPLATE_DIR) else None


def _build_puml_title(project_name: str = None, module_name: str = None) -> str:
    """构建图表标题前缀：项目名-模块名-图类型。"""
    parts = []
    if project_name:
        parts.append(project_name)
    if module_name:
        parts.append(module_name)
    return "-".join(parts) + "-" if parts else ""


def _render_puml_from_state(
    model_type: str,
    state: dict,
    project_name: str = None,
    module_name: str = None,
) -> str:
    """根据 model_type 和当前 State 数据，使用 Jinja2 模板渲染 PUML 代码。

    注意：时序图不走此函数，由 _render_single_sequence_diagram 按每个用例单独渲染。
    """
    if model_type == "sequence":
        return ""  # sequence 由 generate_multi_sequence 单独处理
    if _puml_env is None:
        return _render_fallback_puml(model_type, state, project_name, module_name)

    template_map = {
        "usecase": "usecase.puml.j2",
        "class": "class.puml.j2",
        "sequence": "sequence.puml.j2",
    }
    tmpl_name = template_map.get(model_type)
    if not tmpl_name:
        return ""

    try:
        tmpl = _puml_env.get_template(tmpl_name)
        return tmpl.render(**_build_context(model_type, state, project_name, module_name))
    except Exception as e:
        print(f"[WARN] PUML template render failed [{model_type}]: {e}")
        return _render_fallback_puml(model_type, state, project_name, module_name)


def _build_context(
    model_type: str,
    state: dict,
    project_name: str = None,
    module_name: str = None,
) -> dict:
    """为每种图类型构建 Jinja2 模板上下文。"""
    ctx = {}
    if project_name is not None:
        ctx["project_name"] = project_name
    if module_name is not None:
        ctx["module_name"] = module_name

    if model_type == "usecase":
        rels = state.get("relationships", {})
        entities = state.get("entities", {})
        ctx.update({
            "actors": state.get("actors", []),
            "usecases": state.get("usecases", []),
            "entities": entities,
            "relationships": {
                "inclusion": _pairs_to_dict(rels.get("include", [])),
                "extension": _pairs_to_dict(rels.get("extend", [])),
                "uc_gen": _pairs_to_dict(rels.get("uc_generalization", [])),
                "act_gen": _pairs_to_dict(rels.get("actor_generalization", [])),
                "association": entities,
            },
        })
        return ctx

    if model_type == "class":
        ctx.update({
            "classes": state.get("classes", []),
            "class_details": state.get("class_details", {}),
            "class_relationships": state.get("class_relationships", {}),
        })
        return ctx

    if model_type == "sequence":
        ctx.update({
            "sequence_data": state.get("sequence_data", {}),
        })
        return ctx

    return ctx


def _pairs_to_dict(pairs: list) -> dict:
    d = {}
    for p, c in pairs:
        d.setdefault(p, []).append(c)
    return d


def _render_fallback_puml(
    model_type: str,
    state: dict,
    project_name: str = None,
    module_name: str = None,
) -> str:
    """模板不存在时，用纯 Python 字符串拼接生成 PUML。"""
    title_prefix = _build_puml_title(project_name, module_name)

    if model_type == "usecase":
        lines = ["@startuml", f"title {title_prefix}用例图"]
        for actor in state.get("actors", []):
            lines.append(f":{actor}:")
        for uc in state.get("usecases", []):
            lines.append(f"({uc})")
        lines.append("@enduml")
        return "\n".join(lines)

    if model_type == "class":
        lines = ["@startuml", f"title {title_prefix}类图", "skinparam classAttributeIconSize 0"]
        for cls_item in state.get("classes", []):
            if isinstance(cls_item, dict):
                cls_name = cls_item.get("name", "UnnamedClass")
                details = cls_item
            else:
                cls_name = str(cls_item)
                details = state.get("class_details", {}).get(cls_name, {})
            lines.append(f"class {cls_name} {{")
            for attr in details.get("attributes", []):
                lines.append(f"  {attr}")
            for method in details.get("methods", []):
                lines.append(f"  {method}()")
            lines.append("}")
        lines.append("@enduml")
        return "\n".join(lines)

    if model_type == "sequence":
        lines = ["@startuml", f"title {title_prefix}时序图"]
        seq_data = state.get("sequence_data", {})
        all_parts = []
        for data in seq_data.values():
            all_parts.extend(data.get("participants", []))
        all_parts = list(dict.fromkeys(all_parts))
        for p in all_parts:
            lines.append(f"participant {p}")
        lines.append("@enduml")
        return "\n".join(lines)

    return "@startuml\n@enduml"


def _render_single_sequence_diagram(
    usecase_name: str,
    seq_data: dict,
    project_name: str = None,
    module_name: str = None,
) -> str:
    """渲染单个用例的时序图 PUML 代码。"""
    if _puml_env is None:
        return _render_seq_fallback(usecase_name, seq_data, project_name, module_name)

    try:
        tmpl = _puml_env.get_template("sequence.puml.j2")
        return tmpl.render(
            usecase_name=usecase_name,
            project_name=project_name,
            module_name=module_name,
            participants=seq_data.get("participants", []),
            interactions=seq_data.get("interactions", []),
            messages=seq_data.get("messages", []),
        )
    except Exception as e:
        print(f"[WARN] sequence template render failed for [{usecase_name}]: {e}")
        return _render_seq_fallback(usecase_name, seq_data, project_name, module_name)


def _render_seq_fallback(
    usecase_name: str,
    seq_data: dict,
    project_name: str = None,
    module_name: str = None,
) -> str:
    """sequence 模板不存在时的兜底渲染。"""
    title_prefix = _build_puml_title(project_name, module_name)
    lines = ["@startuml", f"title {title_prefix}{usecase_name}-时序图"]
    participants = seq_data.get("participants", [])
    all_parts = []
    for p in participants:
        if isinstance(p, dict):
            all_parts.append(p.get("name", str(p)))
        else:
            all_parts.append(str(p))
    for p in all_parts:
        lines.append(f"participant {p}")
    lines.append("@enduml")
    return "\n".join(lines)


def _extract_return_data(model_type: str, state: dict) -> dict:
    """从 LangGraph 运行结果中提取返回给前端的数据。"""
    if model_type == "usecase":
        return {
            "actors": state.get("actors", []),
            "usecases": state.get("usecases", []),
            "entities": state.get("entities", {}),
            "relationships": state.get("relationships", {}),
        }
    if model_type == "class":
        return {
            "classes": state.get("classes", []),
            "class_details": state.get("class_details", {}),
            "class_relationships": state.get("class_relationships", {}),
        }
    if model_type == "sequence":
        return {
            "sequence_data": state.get("sequence_data", {}),
        }
    return {}


async def _get_module_name(db, module_id: int) -> str | None:
    """根据 module_id 查询模块名称。"""
    if module_id is None or db is None:
        return None
    module = await database_service.get_module_by_id(db, module_id)
    return module.module_name if module else None


class UMLService:
    """UML 生成服务，封装 LangGraph HITL 工作流调用。"""

    def __init__(self):
        # 延迟构建：避免在模块导入时触发（此时 dotenv 尚未加载）
        self._graph = None

    @property
    def app_graph(self):
        """懒加载编译好的 LangGraph 应用。"""
        if self._graph is None:
            self._graph = build_graph()
        return self._graph

    async def run_extract(
        self,
        model_type: str,
        requirement_text: str,
        thread_id: str,
        project_id: int = None,
        db=None,
        selected_usecases: list = None,
        module_id: int = None,
    ) -> dict:
        """启动 LangGraph，运行到断点暂停，返回中间态 JSON。

        时序图特殊处理：从数据库读取已确认的 usecase/class 数据填充状态。
        RAG 支持：仅针对复杂项目，自动从上传的原始文件（PDF/TXT）中提取文本建立索引。
        """
        config = {"configurable": {"thread_id": thread_id}}

        # 获取原始需求（用于 RAG）
        # 仅针对复杂项目，优先从上传的原始文件提取，其次使用 requirement_text
        original_requirement = ""
        is_complex = False

        if db and project_id:
            project = await database_service.get_project_by_id(db, project_id)
            if project:
                is_complex = project.is_complex

                if is_complex and project.requirement_text:
                    # 复杂项目：直接使用已存储的 requirement_text（split 时已提取并存储）
                    original_requirement = project.requirement_text
                    print(f"[RAG] 使用已存储的 requirement_text，长度: {len(original_requirement)} 字符")
                else:
                    if is_complex:
                        print(f"[RAG] 复杂项目但无 requirement_text，跳过")
                    else:
                        print(f"[RAG] 非复杂项目，跳过 RAG")

        initial_state = {
            "input_text": requirement_text,
            "original_requirement": original_requirement,
            "project_id": project_id if is_complex else None,
            "current_diagram": model_type,
            "entities": {},
            "actors": [],
            "usecases": [],
            "relationships": {},
            "classes": [],
            "class_details": {},
            "class_relationships": {},
            "selected_usecases": selected_usecases or [],
            "sequence_data": {},
        }

        # RAG: 仅对复杂项目索引原始需求（仅首次或需要更新时）
        if is_complex and project_id and original_requirement:
            try:
                # 检查是否已索引，避免重复索引
                col_info = vector_store.get_collection_info(project_id)
                if not col_info:
                    print(f"[RAG] Indexing original requirement for project {project_id}")
                    vector_store.index_text(original_requirement, project_id)
                else:
                    print(f"[RAG] Using existing index for project {project_id}")
            except Exception as e:
                print(f"[RAG] Warning: Failed to index requirement: {e}")

        # 时序图：从数据库读取 usecase/class 完整数据填充状态
        if model_type == "sequence" and db and project_id:
            db_filled = await self._fill_state_from_db(db, project_id, module_id)
            if db_filled:
                print(f"[Sequence Extract] 从数据库回填状态: {list(db_filled.keys())}")
                initial_state = {**initial_state, **db_filled}
            else:
                print("[Sequence Extract] 警告：数据库中未找到 usecase/class 数据")

        result = await self.app_graph.ainvoke(initial_state, config)

        # 时序图：完整执行后直接渲染 PUML 和图片
        if model_type == "sequence":
            project_name, module_name = await self._get_names(db, project_id, module_id)
            diagrams = await self._render_sequence_diagrams(
                result.get("sequence_data", {}),
                selected_usecases,
                project_name,
                module_name,
            )
            return {"sequence_data": result.get("sequence_data", {}), "diagrams": diagrams}

        return _extract_return_data(model_type, result)

    async def get_missing_dependencies(
        self, db, project_id: int, module_id: int = None
    ) -> list[str]:
        """时序图专用：检查 usecase / class 是否都已生成并确认，返回缺失的类型列表。"""
        missing = []
        for dep in ("usecase", "class"):
            model = await database_service.get_latest_confirmed_model(db, project_id, dep, module_id)
            if not model:
                missing.append(dep)
        return missing

    async def _fill_state_from_db(self, db, project_id: int, module_id: int = None) -> dict:
        """时序图专用：从数据库读取已确认的 usecase/class JSON，填充到状态中。"""
        filled = {}

        usecase_model = await database_service.get_latest_confirmed_model(db, project_id, "usecase", module_id)
        if usecase_model and usecase_model.data_json:
            filled["actors"] = usecase_model.data_json.get("actors", [])
            filled["usecases"] = usecase_model.data_json.get("usecases", [])
            filled["entities"] = usecase_model.data_json.get("entities", {})
            filled["relationships"] = usecase_model.data_json.get("relationships", {})

        class_model = await database_service.get_latest_confirmed_model(db, project_id, "class", module_id)
        if class_model and class_model.data_json:
            filled["classes"] = class_model.data_json.get("classes", [])
            filled["class_details"] = class_model.data_json.get("class_details", {})
            filled["class_relationships"] = class_model.data_json.get("class_relationships", {})

        return filled

    async def _get_names(
        self, db, project_id: int, module_id: int = None
    ) -> tuple[str | None, str | None]:
        """获取项目名称和模块名称，用于图表标题。"""
        project_name = None
        module_name = None
        if db and project_id:
            project = await database_service.get_project_by_id(db, project_id)
            if project:
                project_name = project.name
        if module_id:
            module_name = await _get_module_name(db, module_id)
        return project_name, module_name

    async def resume_and_generate(
        self,
        model_type: str,
        thread_id: str,
        confirmed_data: dict,
        project_id: int = None,
        db=None,
        selected_usecases: list = None,
        module_id: int = None,
    ) -> dict:
        """接收用户确认的数据，合并到 checkpoint 状态，续跑图，生成 PUML。

        RAG 支持：直接使用 split 时已存储的 requirement_text，不重复提取。
        """
        config = {"configurable": {"thread_id": thread_id}}

        current_state = self.app_graph.get_state(config).values

        # 获取原始需求（用于 RAG）
        # 直接使用 split 时已存储的 requirement_text，不重复提取
        original_requirement = ""
        is_complex = False

        if db and project_id:
            project = await database_service.get_project_by_id(db, project_id)
            if project:
                is_complex = project.is_complex

                if is_complex and project.requirement_text:
                    # 复杂项目：直接使用已存储的 requirement_text
                    original_requirement = project.requirement_text
                    print(f"[RAG] 使用已存储的 requirement_text，长度: {len(original_requirement)} 字符")
                    current_state["original_requirement"] = original_requirement
                    current_state["project_id"] = project_id
                else:
                    if is_complex:
                        print(f"[RAG] 复杂项目但无 requirement_text，跳过")
                    else:
                        print(f"[RAG] 非复杂项目，跳过 RAG")

        # 时序图：强制从数据库回填 usecase/class 完整数据
        if model_type == "sequence" and db and project_id:
            db_filled = await self._fill_state_from_db(db, project_id, module_id)
            if db_filled:
                print(f"[Sequence] 从数据库回填状态: {list(db_filled.keys())}")
                current_state = {**current_state, **db_filled}
            else:
                print("[Sequence] 警告：数据库中未找到 usecase/class 数据")

        # 合并用户确认的数据
        merged_state = {**current_state, **confirmed_data}
        
        # 设置确认列表约束：当 confirmed_data 包含 classes/actors/usecases 时，禁止 agent 添加新实体
        if "classes" in confirmed_data and confirmed_data["classes"]:
            merged_state["confirmed_classes"] = confirmed_data["classes"]
        if "actors" in confirmed_data and confirmed_data["actors"]:
            merged_state["confirmed_actors"] = confirmed_data["actors"]
        if "usecases" in confirmed_data and confirmed_data["usecases"]:
            merged_state["confirmed_usecases"] = confirmed_data["usecases"]
        
        if model_type == "sequence":
            if selected_usecases:
                merged_state["selected_usecases"] = selected_usecases
            merged_state["current_diagram"] = model_type

        self.app_graph.update_state(config, merged_state)
        result = await self.app_graph.ainvoke(None, config)

        project_name, module_name = await self._get_names(db, project_id, module_id)

        if model_type == "sequence":
            return await self.generate_multi_sequence(
                result, selected_usecases, project_name, module_name
            )

        puml_code = _render_puml_from_state(
            model_type, result, project_name, module_name
        )
        image_url = await render_puml_to_url(puml_code)

        return {
            "puml_code": puml_code,
            "image_url": image_url,
        }

    async def generate_multi_sequence(
        self,
        result_state: dict,
        selected_usecases: list = None,
        project_name: str = None,
        module_name: str = None,
    ) -> dict:
        """时序图专用：为每个用例单独生成一张 PUML 图和图片。"""
        sequence_data = result_state.get("sequence_data", {})
        diagrams = await self._render_sequence_diagrams(
            sequence_data, selected_usecases, project_name, module_name
        )
        print(f"[Sequence] 共生成 {len(diagrams)} 张时序图")
        return {"diagrams": diagrams}

    async def _render_sequence_diagrams(
        self,
        sequence_data: dict,
        selected_usecases: list = None,
        project_name: str = None,
        module_name: str = None,
    ) -> list:
        """渲染每个用例的时序图，返回 PUML + 图片列表。"""
        diagrams = []
        for usecase_name, seq_data in sequence_data.items():
            if selected_usecases and usecase_name not in selected_usecases:
                continue
            puml_code = _render_single_sequence_diagram(
                usecase_name, seq_data, project_name, module_name
            )
            image_url = await render_puml_to_url(puml_code)
            diagrams.append({
                "usecase_name": usecase_name,
                "puml_code": puml_code,
                "image_url": image_url,
            })
            print(f"[Sequence] 渲染完成: {usecase_name} ({len(puml_code)} chars)")
        return diagrams

    async def sync_from_puml(
        self,
        model_type: str,
        puml_code: str,
        current_state: dict,
        usecase_name: str = None,
        project_id: int = None,
        db=None,
        module_id: int = None,
    ) -> dict:
        """接收 PUML 代码，逆向解析为 JSON，重新渲染图片。"""
        import logging
        logger = logging.getLogger(__name__)

        project_name, module_name = await self._get_names(db, project_id, module_id)

        # 步骤1: 优先使用正则解析器
        new_json_data = None
        regex_parse_success = False

        try:
            if model_type == "sequence":
                regex_result = parse_sequence_puml_regex(puml_code)
                if is_valid_parsed_data(model_type, regex_result):
                    participants = regex_result.get("participants", [])
                    messages = regex_result.get("messages", [])
                    new_json_data = {usecase_name: {
                        "participants": participants,
                        "messages": messages,
                        "interactions": self._messages_to_interactions(messages)
                    }} if usecase_name else {}
                    regex_parse_success = True
                    logger.info("[SYNC] 正则解析成功（时序图）")
            elif model_type == "usecase":
                regex_result = parse_usecase_puml_regex(puml_code)
                if is_valid_parsed_data(model_type, regex_result):
                    new_json_data = regex_result
                    regex_parse_success = True
                    logger.info("[SYNC] 正则解析成功（用例图）")
            elif model_type == "class":
                regex_result = parse_class_puml_regex(puml_code)
                if is_valid_parsed_data(model_type, regex_result):
                    new_json_data = regex_result
                    regex_parse_success = True
                    logger.info("[SYNC] 正则解析成功（类图）")
        except Exception as e:
            logger.warning(f"[SYNC] 正则解析过程异常，降级调用 LLM: {e}")

        # 步骤2: 正则解析失败，降级使用 LLM
        if not regex_parse_success:
            logger.warning("[SYNC] 正则解析失效或数据不完整，降级调用 LLM 兜底解析...")
            try:
                llm_result = sync_puml_to_state(model_type, puml_code, current_state)
                if llm_result:
                    new_json_data = llm_result
                    logger.info("[SYNC] LLM 解析成功")
            except Exception as e:
                logger.error(f"[SYNC] LLM 解析也失败: {e}")
                new_json_data = current_state

        # 步骤3: 根据图类型渲染
        if model_type == "sequence":
            if usecase_name:
                image_url = await render_puml_to_url(puml_code)
                return {
                    "usecase_name": usecase_name,
                    "new_json_data": new_json_data,
                    "image_url": image_url,
                    "puml_code": puml_code,
                }
            diagrams = []
            sequence_data = new_json_data or {}
            for uc_name, seq_data in sequence_data.items():
                image_url = await render_puml_to_url(puml_code)
                diagrams.append({
                    "usecase_name": uc_name,
                    "puml_code": puml_code,
                    "image_url": image_url,
                })
            return {"diagrams": diagrams, "new_json_data": new_json_data}

        image_url = await render_puml_to_url(puml_code)
        return {
            "new_json_data": new_json_data,
            "image_url": image_url,
        }

    def _messages_to_interactions(self, messages: list) -> list:
        """将消息列表转换为交互列表（用于时序图）。"""
        interactions = []
        for msg in messages:
            interactions.append({
                "from": msg.get("source", ""),
                "to": msg.get("target", ""),
                "content": msg.get("message", ""),
            })
        return interactions


# 模块级单例，供路由层直接引入使用
uml_service = UMLService()
