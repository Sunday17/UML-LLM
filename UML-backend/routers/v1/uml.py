"""routers/v1/uml.py — 通用 UML 业务路由（支持 usecase / class / sequence）。

路由结构：
  POST /uml/{type}/extract   — 启动 LLM 提取，运行到断点暂停，返回中间态 JSON
  POST /uml/{type}/generate — 接收确认数据，继续图执行，生成 PUML
  POST /uml/sync           — PUML 代码逆向同步

每种图类型的中间态数据结构（extracted_data）：
  usecase  -> {actors, usecases, entities, relationships}
  class    -> {classes, class_details, class_relationships}
  sequence -> {sequence_data}
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from sqlmodel.ext.asyncio.session import AsyncSession

from models.database import get_session
from services.database import database_service
from services.uml_service import uml_service
from schemas.uml import (
    ExtractRequest,
    TableDataResponse,
    GenerateRequest,
    UMLFinalResponse,
    SyncRequest,
    SyncResponse,
    SequenceDiagramItem,
    SequenceExtractResponse,
    SequenceOptionsResponse,
    UMLDeleteRequest,
    GetUMLResponse,
    UMLModelItem,
)


router = APIRouter()

_VALID_TYPES = {"usecase", "class", "sequence"}


def _validate_type(model_type: str) -> str:
    """校验图类型参数，不合法则抛 400。"""
    if model_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model_type '{model_type}'. Must be one of: {sorted(_VALID_TYPES)}",
        )
    return model_type


# ================================================================
# 0. 时序图选项（用例列表）
# ================================================================

@router.get("/sequence/options/{project_id}", response_model=SequenceOptionsResponse)
async def get_sequence_options(
    project_id: int,
    db: AsyncSession = Depends(get_session),
):
    """
    返回当前项目可用的时序图选项（已确认用例图的用例名称列表）。
    前端先调用此接口获取可选用例，再传入 selected_usecases 调用 extract。
    """
    project = await database_service.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    usecase_model = await database_service.get_latest_model(db, project_id, "usecase")
    if not usecase_model:
        raise HTTPException(
            status_code=400,
            detail="项目下暂无用例图数据，请先前往提取并生成用例图。",
        )
    if not usecase_model.is_confirmed:
        raise HTTPException(
            status_code=400,
            detail="用例图尚未确认，请先在用例图页面确认后，再生成时序图。",
        )
    if not usecase_model.data_json:
        return SequenceOptionsResponse(project_id=project_id, options=[])

    options = usecase_model.data_json.get("usecases", [])
    return SequenceOptionsResponse(project_id=project_id, options=options)


# ================================================================
# 0.5 获取已保存的 UML 数据
# ================================================================

@router.get("/{model_type}/saved", response_model=GetUMLResponse)
async def get_saved_uml(
    model_type: str,
    project_id: int,
    module_id: int = None,
    db: AsyncSession = Depends(get_session),
):
    """
    获取项目下已保存的 UML 数据。

    - module_id 非空时：按模块模式获取（优先）
    - usecase / class：返回最新一条记录
    - sequence：返回所有用例的时序图记录（按创建时间倒序）
    """
    model_type = _validate_type(model_type)

    project = await database_service.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 模块模式校验
    if module_id is not None:
        module = await database_service.get_module_by_id(db, module_id)
        if not module:
            raise HTTPException(status_code=404, detail="Module not found")
        if module.project_id != project_id:
            raise HTTPException(status_code=400, detail="Module does not belong to this project")

    # 时序图返回所有记录
    if model_type == "sequence":
        models = await database_service.list_sequence_models(db, project_id, module_id)
        return GetUMLResponse(
            model_type=model_type,
            records=[UMLModelItem.model_validate(m) for m in models],
        )

    # 其他类型返回最新一条
    model = await database_service.get_latest_model(db, project_id, model_type, module_id)
    return GetUMLResponse(
        model_type=model_type,
        records=[UMLModelItem.model_validate(model)] if model else [],
    )


# ================================================================
# 1. 启动 LLM 提取（断点暂停，返回中间态 JSON）
# ================================================================

@router.post("/{model_type}/extract")
async def extract_uml(
    model_type: str,
    req: ExtractRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    启动 LangGraph 提取流程，运行到断点暂停，返回中间态 JSON（供前端表格展示）。

    工作流程：
    1. 根据 model_type 初始化 initial_state（触发 route_start 路由）
    2. ainvoke 执行，在 interrupt_before 设定的节点处自动挂起
    3. 返回提取结果，前端可编辑确认

    注意：此接口只提取实体，不保存到数据库。
          数据库记录在 generate 接口成功生成时创建。
    """
    model_type = _validate_type(model_type)

    # 模块模式解析：优先使用 module_id，兼容 project_id
    project = None
    thread_id: str = None
    requirement_text: str = None
    effective_project_id: int = None
    effective_module_id: int = None

    if req.module_id is not None:
        module = await database_service.get_module_by_id(db, req.module_id)
        if not module:
            raise HTTPException(status_code=404, detail="Module not found")
        effective_project_id = module.project_id
        effective_module_id = module.id
        thread_id = module.thread_id
        requirement_text = module.core_requirements or ""
        project = await database_service.get_project_by_id(db, effective_project_id)
    else:
        project = await database_service.get_project_by_id(db, req.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        effective_project_id = project.id
        thread_id = project.thread_id
        requirement_text = project.requirement_text or ""

    if model_type == "sequence":
        missing = await uml_service.get_missing_dependencies(db, effective_project_id, effective_module_id)
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"生成时序图前需先完成以下图表：{', '.join(missing)}，请先前往生成。",
            )
        if not req.selected_usecases:
            raise HTTPException(
                status_code=400,
                detail="时序图生成必须传入 selected_usecases 参数，请先调用 /uml/sequence/options/{project_id} 获取可选用例。",
            )

    extracted_data = await uml_service.run_extract(
        model_type=model_type,
        requirement_text=requirement_text,
        thread_id=thread_id,
        project_id=effective_project_id,
        module_id=effective_module_id,
        db=db,
        selected_usecases=req.selected_usecases,
    )

    # 时序图：完整执行后直接生成并保存，返回所有用例的完整数据
    if model_type == "sequence":
        diagrams_data = extracted_data.get("diagrams", [])
        diagrams = []
        for diag in diagrams_data:
            uc_name = diag["usecase_name"]
            model = await database_service.save_sequence_diagram(
                db,
                project_id=effective_project_id,
                module_id=effective_module_id,
                usecase_name=uc_name,
                data_json={"sequence_data": {uc_name: diag}},
                puml_code=diag.get("puml_code", ""),
                image_url=diag.get("image_url", ""),
                is_regenerate=True,
            )
            diagrams.append({
                "usecase_name": uc_name,
                "puml_code": diag.get("puml_code", ""),
                "image_url": diag.get("image_url", ""),
            })
        print(f"[extract] sequence: saved {len(diagrams)} diagrams")

        return SequenceExtractResponse(
            project_id=effective_project_id,
            thread_id=thread_id,
            diagrams=diagrams,
        )

    return TableDataResponse(
        project_id=effective_project_id,
        thread_id=thread_id,
        model_type=model_type,
        extracted_data=extracted_data,
    )


# ================================================================
# 2. 接收确认数据，继续执行，生成 PUML
# ================================================================

@router.post("/{model_type}/generate", response_model=UMLFinalResponse)
async def generate_uml(
    model_type: str,
    req: GenerateRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    用户在表格中确认/修改数据后，调用此接口：
    1. 将 confirmed_data 写入 LangGraph checkpoint 状态
    2. 传入 None 恢复执行，从断点继续直到图结束
    3. 渲染 PlantUML 代码
    4. 持久化最终产物（is_confirmed=True）
    """
    model_type = _validate_type(model_type)

    # 模块模式解析：优先使用 module_id，兼容 project_id
    project = None
    thread_id: str = None
    effective_project_id: int = None
    effective_module_id: int = None

    if req.module_id is not None:
        module = await database_service.get_module_by_id(db, req.module_id)
        if not module:
            raise HTTPException(status_code=404, detail="Module not found")
        effective_project_id = module.project_id
        effective_module_id = module.id
        thread_id = module.thread_id
        project = await database_service.get_project_by_id(db, effective_project_id)
    else:
        project = await database_service.get_project_by_id(db, req.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        effective_project_id = project.id
        thread_id = project.thread_id

    if model_type == "sequence":
        missing = await uml_service.get_missing_dependencies(db, effective_project_id, effective_module_id)
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"生成时序图前需先完成以下图表：{', '.join(missing)}，请先前往生成。",
            )

    result = await uml_service.resume_and_generate(
        model_type=model_type,
        thread_id=thread_id,
        confirmed_data=req.confirmed_data,
        project_id=effective_project_id,
        module_id=effective_module_id,
        db=db,
        selected_usecases=req.selected_usecases,
    )

    # 时序图：每个用例单独存一条记录
    if model_type == "sequence" and "diagrams" in result:
        saved_diagrams = []
        for diag in result["diagrams"]:
            uc_name = diag["usecase_name"]
            uc_data = {"sequence_data": {uc_name: diag}}
            model = await database_service.save_sequence_diagram(
                db,
                project_id=effective_project_id,
                module_id=effective_module_id,
                usecase_name=uc_name,
                data_json=uc_data,
                puml_code=diag["puml_code"],
                image_url=diag["image_url"],
                is_regenerate=True,
            )
            saved_diagrams.append(model)
        print(f"[generate] sequence: saved {len(saved_diagrams)} diagrams")

        return UMLFinalResponse(
            diagrams=[
                SequenceDiagramItem(
                    usecase_name=d["usecase_name"],
                    puml_code=d["puml_code"],
                    image_url=d["image_url"],
                )
                for d in result["diagrams"]
            ]
        )

    await database_service.update_model_with_puml(
        db,
        project_id=effective_project_id,
        module_id=effective_module_id,
        model_type=model_type,
        confirmed_data=req.confirmed_data,
        puml_code=result["puml_code"],
        image_url=result["image_url"],
        is_regenerate=True,
    )

    return UMLFinalResponse(
        puml_code=result["puml_code"],
        image_url=result["image_url"],
    )


# ================================================================
# 3. PUML 代码逆向同步
# ================================================================

@router.post("/sync", response_model=SyncResponse)
async def sync_puml_code(
    req: SyncRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    用户手动修改 PUML 代码 -> 逆向解析为 JSON -> 重新渲染图片 -> 更新数据库。
    支持模块模式（module_id 非空时按 module_id 保存）。
    """
    req.model_type = _validate_type(req.model_type)

    # 解析 module_id（优先），并获取对应的 project_id
    effective_project_id = req.project_id
    effective_module_id = req.module_id

    if req.module_id is not None:
        module = await database_service.get_module_by_id(db, req.module_id)
        if not module:
            raise HTTPException(status_code=404, detail="Module not found")
        effective_project_id = module.project_id
        effective_module_id = module.id
    else:
        project = await database_service.get_project_by_id(db, req.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

    # 时序图：获取当前用例的记录，更新 JSON 数据
    if req.model_type == "sequence":
        current_model = await database_service.get_sequence_model(
            db, effective_project_id, req.usecase_name, effective_module_id
        )
        current_state = current_model.data_json if current_model else {}
    else:
        current_model = await database_service.get_latest_model(
            db, effective_project_id, req.model_type, effective_module_id
        )
        current_state = current_model.data_json if current_model else {}

    sync_result = await uml_service.sync_from_puml(
        model_type=req.model_type,
        puml_code=req.puml_code,
        current_state=current_state,
        usecase_name=req.usecase_name,
        project_id=effective_project_id,
        db=db,
    )

    # 时序图：区分单图同步（指定 usecase_name）和多图同步
    if req.model_type == "sequence":
        if "usecase_name" in sync_result:
            # 单图同步：直接覆盖该用例的记录
            uc_name = sync_result["usecase_name"]
            uc_data = {"sequence_data": {uc_name: sync_result.get("new_json_data", {}).get(uc_name, {})}}
            await database_service.save_sequence_diagram(
                db,
                project_id=effective_project_id,
                module_id=effective_module_id,
                usecase_name=uc_name,
                data_json=uc_data,
                puml_code=sync_result.get("puml_code", req.puml_code),
                image_url=sync_result.get("image_url", ""),
                is_regenerate=False,
            )
            return SyncResponse(
                diagrams=[
                    SequenceDiagramItem(
                        usecase_name=uc_name,
                        puml_code=sync_result.get("puml_code", req.puml_code),
                        image_url=sync_result.get("image_url", ""),
                    )
                ]
            )

        if "diagrams" in sync_result:
            # 多图同步：循环保存每个用例的记录
            for diag in sync_result["diagrams"]:
                uc_name = diag["usecase_name"]
                uc_data = {"sequence_data": {uc_name: diag}}
                await database_service.save_sequence_diagram(
                    db,
                    project_id=effective_project_id,
                    module_id=effective_module_id,
                    usecase_name=uc_name,
                    data_json=uc_data,
                    puml_code=diag["puml_code"],
                    image_url=diag["image_url"],
                    is_regenerate=False,
                )
            return SyncResponse(
                diagrams=[
                    SequenceDiagramItem(
                        usecase_name=d["usecase_name"],
                        puml_code=d["puml_code"],
                        image_url=d["image_url"],
                    )
                    for d in sync_result["diagrams"]
                ]
            )

    # 非 sequence 或其他情况：按 module_id / project_id 统一覆盖
    await database_service.update_model_with_puml(
        db,
        project_id=effective_project_id,
        module_id=effective_module_id,
        model_type=req.model_type,
        confirmed_data=sync_result["new_json_data"],
        puml_code=req.puml_code,
        image_url=sync_result["image_url"],
        is_regenerate=False,
    )

    return SyncResponse(
        image_url=sync_result["image_url"],
    )


# ================================================================
# 4. UML 图表删除
# ================================================================

@router.delete("/record", status_code=204)
async def delete_uml_record(
    req: UMLDeleteRequest,
    db: AsyncSession = Depends(get_session),
):
    """根据 project_id、model_type 和（可选的）module_id 删除特定 UML 记录。

    - module_id 非空时：按 module_id 过滤（模块模式）。
    - usecase / class：删除该类型全部记录。
    - sequence + usecase_name：仅删除该用例的记录。
    - sequence 无 usecase_name：删除该类型全部记录。
    """
    # 验证项目存在
    project = await database_service.get_project_by_id(db, req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 验证模块存在（如传入 module_id）
    if req.module_id is not None:
        module = await database_service.get_module_by_id(db, req.module_id)
        if not module:
            raise HTTPException(status_code=404, detail="Module not found")
        if module.project_id != req.project_id:
            raise HTTPException(status_code=400, detail="Module does not belong to this project")

    success = await database_service.delete_uml_model(
        db,
        project_id=req.project_id,
        model_type=req.model_type,
        usecase_name=req.usecase_name,
        module_id=req.module_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="UML Record not found")

    return None


# ================================================================
# 5. 获取所有 UML 资产（用于批量导出）
# ================================================================

@router.get("/assets/{project_id}")
async def get_uml_assets(
    project_id: int,
    module_id: Optional[int] = None,
    db: AsyncSession = Depends(get_session),
):
    """返回项目下所有已确认的 UML 图表资产信息（image_url 等）。"""
    project = await database_service.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    usecase = await database_service.get_latest_confirmed_model(db, project_id, "usecase", module_id)
    class_model = await database_service.get_latest_confirmed_model(db, project_id, "class", module_id)
    sequence_records = await database_service.list_sequence_models(db, project_id, module_id)

    return {
        "usecase": {
            "image_url": usecase.image_url if usecase else None,
            "is_confirmed": usecase.is_confirmed if usecase else False,
        } if usecase else None,
        "class": {
            "image_url": class_model.image_url if class_model else None,
            "is_confirmed": class_model.is_confirmed if class_model else False,
        } if class_model else None,
        "sequence": [
            {
                "usecase_name": r.usecase_name,
                "image_url": r.image_url,
            }
            for r in sequence_records
            if r.image_url  # 只返回有有效图片 URL 的时序图
        ],
    }
