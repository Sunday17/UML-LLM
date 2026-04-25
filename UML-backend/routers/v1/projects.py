"""routers/v1/projects.py — 项目管理 CRUD 接口。"""

import io
import os
import uuid
import zipfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List
from sqlmodel import delete
from sqlmodel.ext.asyncio.session import AsyncSession

from models.database import get_session
from models.uml import Project, ProjectModule
from services.database import database_service
from services.llm import split_complex_project_with_qwen
from schemas.uml import (
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ProjectModuleOut,
    ModuleCreate,
    ModuleUpdate,
    ExportModulesRequest,
)
from utils import oss_client


class BatchDeleteRequest(BaseModel):
    ids: List[int]


router = APIRouter()


@router.get("/{project_id}/download-url")
async def get_project_download_url(project_id: int, db: AsyncSession = Depends(get_session)):
    """根据项目 ID 获取原始文件的签名下载 URL。"""
    project = await database_service.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.original_file_url:
        raise HTTPException(status_code=404, detail="该项目没有上传文件")

    try:
        signed_url = oss_client.get_signed_url(project.original_file_url, expire=3600)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"签名 URL 生成失败: {e}")

    return {"download_url": signed_url, "file_key": project.original_file_url}


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_session)):
    """获取所有项目列表（按创建时间倒序）。"""
    return await database_service.list_projects(db)


@router.post("", response_model=ProjectOut)
async def create_project(req: ProjectCreate, db: AsyncSession = Depends(get_session)):
    """创建新项目，自动生成 UUID 作为 thread_id（LangGraph 会话 ID）。"""
    thread_id = str(uuid.uuid4())
    project = await database_service.create_project(
        db,
        name=req.name,
        req_text=req.requirement_text,
        thread_id=thread_id,
        is_complex=req.is_complex,
        original_file_url=req.original_file_url,
        description=req.description,
    )
    return project


@router.post("/batch-delete")
async def batch_delete_projects(req: BatchDeleteRequest, db: AsyncSession = Depends(get_session)):
    """批量删除项目及关联 OSS 文件。"""
    project_ids = req.ids
    if not project_ids:
        raise HTTPException(status_code=400, detail="请选择要删除的项目")

    # 先收集所有需要清理的 OSS Key
    oss_keys_to_delete: list[str] = []
    for pid in project_ids:
        proj = await database_service.get_project_by_id(db, pid)
        if proj and proj.original_file_url:
            oss_keys_to_delete.append(proj.original_file_url)

    # 删除数据库记录
    deleted_count = await database_service.delete_projects_batch(db, project_ids)

    # 批量清理 OSS 文件（不阻断返回）
    for key in oss_keys_to_delete:
        try:
            oss_client.delete_file(key)
            print(f"[INFO] OSS 文件已删除: {key}")
        except Exception as e:
            print(f"[WARN] OSS 文件删除失败: {key}，错误: {e}")

    return {"message": f"成功删除 {deleted_count} 个项目", "deleted_count": deleted_count}


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: int, req: ProjectUpdate, db: AsyncSession = Depends(get_session)):
    """更新项目的基本信息（名称、描述、需求文本）。"""
    project = await database_service.update_project(
        db,
        project_id=project_id,
        name=req.name,
        description=req.description,
        requirement_text=req.requirement_text,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_session)):
    """删除项目、关联 UML 模型及 OSS 文件（级联删除）。"""
    project = await database_service.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 记录 OSS Key，删除成功后清理
    oss_key = project.original_file_url

    deleted = await database_service.delete_project(db, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    # OSS 文件清理（不阻断返回）
    if oss_key:
        try:
            oss_client.delete_file(oss_key)
            print(f"[INFO] OSS 文件已删除: {oss_key}")
        except Exception as e:
            print(f"[WARN] OSS 文件删除失败: {oss_key}，错误: {e}")

    return {"message": "Project and associated UML models deleted"}


@router.post("/{project_id}/split", response_model=List[ProjectModuleOut])
async def split_project(project_id: int, db: AsyncSession = Depends(get_session)):
    """
    将复杂项目拆分为多个子模块。

    流程（自动判断）：
    1. 查询母项目，获取 requirement_text、original_file_url（OSS Key）和 is_complex 标志
    2. 根据文件类型和 is_complex 自动选择处理路径：
       - 非复杂项目 → 纯文本模式（vl_text）
       - PDF → PDF 转图片 → VL 图片模式（同时提取文本用于 RAG）
       - TXT → 纯文本模式
       - 图片文件 → VL 图片模式
    3. 清理该 project_id 下历史遗留的旧子模块
    4. 为每个模块生成独立 thread_id，存入 project_modules 表
    5. 将提取的文本存入项目的 requirement_text，建立 RAG 索引
    6. 返回新生成的子模块列表
    """
    project = await database_service.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    requirement_text = project.requirement_text or ""
    oss_key = project.original_file_url  # OSS Key，如 "uploads/xxx.pdf"
    is_complex = project.is_complex

    # 清理历史遗留的旧子模块
    await db.execute(delete(ProjectModule).where(ProjectModule.project_id == project_id))
    await db.commit()

    # 根据文件类型和 is_complex 决定处理模式
    ext = os.path.splitext(oss_key or "")[-1].lower() if oss_key else ""
    is_image_ext = ext in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

    if is_complex and ext in {".pdf"}:
        process_mode = "vl_image"
        print(f"[INFO] Split 模式: PDF 复杂项目 → vl_image")
    elif is_complex and is_image_ext:
        process_mode = "vl_image"
        print(f"[INFO] Split 模式: 复杂图片项目 → vl_image")
    elif is_complex:
        # 复杂但无文件：退化为文本模式
        process_mode = "vl_text"
        print(f"[INFO] Split 模式: 复杂项目无文件 → vl_text")
    else:
        process_mode = "vl_text"
        print(f"[INFO] Split 模式: 非复杂项目 → vl_text")

    result = await split_complex_project_with_qwen(requirement_text, oss_key, process_mode)
    modules_data = result.get("modules", [])
    extracted_text = result.get("extracted_text", "")  # PDF 提取的文本

    if not modules_data:
        raise HTTPException(status_code=422, detail="LLM 未返回有效的模块列表")

    # 5. 遍历列表，为每个模块生成独立 thread_id，存入数据库
    created_modules: List[ProjectModule] = []
    for mod in modules_data:
        thread_id = uuid.uuid4().hex
        pm = ProjectModule(
            project_id=project_id,
            module_name=mod.get("module_name", "未命名模块"),
            description=mod.get("description"),
            core_requirements=mod.get("core_requirements", ""),
            thread_id=thread_id,
        )
        db.add(pm)
        created_modules.append(pm)

    await db.commit()

    # 6. 保存提取的文本到 requirement_text 并建立 RAG 索引
    if is_complex and extracted_text and len(extracted_text) > 50:
        print(f"[RAG] 保存提取的文本到 requirement_text，长度: {len(extracted_text)} 字符")
        try:
            project.requirement_text = extracted_text
            await db.commit()
            print(f"[RAG] requirement_text 已保存到数据库")

            # 建立 RAG 索引
            from services.vector_store import vector_store
            col_info = vector_store.get_collection_info(project_id)
            if not col_info:
                print(f"[RAG] 开始建立向量索引 for project {project_id}...")
                chunk_count = vector_store.index_text(extracted_text, project_id, chunk_size=300)
                print(f"[RAG] 向量索引建立完成: {chunk_count} 个文本块")
            else:
                print(f"[RAG] 项目 {project_id} 已存在索引，跳过")
        except Exception as e:
            print(f"[RAG] 保存文本或建立索引失败: {e}")

    # refresh 所有记录以获取数据库生成的 id 和 created_at
    for pm in created_modules:
        await db.refresh(pm)

    return created_modules


# ================================================================
# 复杂项目子模块 CRUD
# ================================================================

@router.get("/{project_id}/modules", response_model=List[ProjectModuleOut])
async def list_modules(project_id: int, db: AsyncSession = Depends(get_session)):
    """获取某复杂项目下的所有子模块列表。"""
    project = await database_service.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    modules = await database_service.list_modules_by_project(db, project_id)
    return modules


@router.post("/{project_id}/modules", response_model=ProjectModuleOut, status_code=201)
async def create_module(project_id: int, req: ModuleCreate, db: AsyncSession = Depends(get_session)):
    """手动新增一个子模块，自动生成唯一 uuid 作为 thread_id。"""
    project = await database_service.get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    thread_id = str(uuid.uuid4())
    module = await database_service.create_module(
        db,
        project_id=project_id,
        module_name=req.module_name,
        description=req.description,
        core_requirements=req.core_requirements,
        thread_id=thread_id,
    )
    return module


@router.put("/modules/{module_id}", response_model=ProjectModuleOut)
async def update_module(module_id: int, req: ModuleUpdate, db: AsyncSession = Depends(get_session)):
    """更新模块的名称、描述或核心需求。"""
    module = await database_service.update_module(
        db,
        module_id=module_id,
        module_name=req.module_name,
        description=req.description,
        core_requirements=req.core_requirements,
    )
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    return module


@router.delete("/modules/{module_id}", status_code=204)
async def delete_module(module_id: int, db: AsyncSession = Depends(get_session)):
    """删除模块（级联删除其图表）。"""
    deleted = await database_service.delete_module(db, module_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Module not found")
    return None


@router.post("/{project_id}/modules/batch-delete")
async def batch_delete_modules(
    project_id: int,
    req: BatchDeleteRequest,
    db: AsyncSession = Depends(get_session)
):
    """批量删除模块（级联删除其图表）。"""
    module_ids = req.ids
    if not module_ids:
        raise HTTPException(status_code=400, detail="请选择要删除的模块")

    # 验证模块是否属于该项目
    modules = await database_service.list_modules_by_project(db, project_id)
    valid_ids = [m.id for m in modules if m.id in module_ids]
    if len(valid_ids) != len(module_ids):
        raise HTTPException(status_code=400, detail="部分模块不属于该项目")

    deleted_count = await database_service.delete_modules_batch(db, module_ids)
    return {"message": f"成功删除 {deleted_count} 个模块", "deleted_count": deleted_count}


@router.post("/{project_id}/export-modules")
async def export_modules(
    project_id: int,
    req: ExportModulesRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    批量导出指定模块的 UML 图片，压缩为 zip 下载。

    - 遍历 module_ids 查出对应 ProjectModule 及其关联的 UMLModel
    - 命名规则与 /assets/{project_id} 一致：
      {模块名}/用例图.png、{模块名}/类图.png、{模块名}/时序图_{usecase_name}.png
    - 无 image_url 的记录会被跳过
    """
    if not req.module_ids:
        raise HTTPException(status_code=400, detail="module_ids 不能为空")

    modules = await database_service.get_modules_by_ids(db, req.module_ids)
    if not modules:
        raise HTTPException(status_code=404, detail="未找到任何指定的模块")

    project = await database_service.get_project_by_id(db, project_id)
    project_name = project.name if project else f"project_{project_id}"
    zip_name = f"{project_name}_UML图.zip"

    import aiohttp
    from urllib.parse import quote

    # 先收集所有图片数据，再统一写入 zip
    zip_contents: List[tuple[str, bytes]] = []  # (filename, content)

    # 图类型中文名映射（与 /assets/{project_id} 命名一致）
    model_type_name_map = {
        "usecase": "用例图",
        "class": "类图",
        "sequence": "时序图",
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        for module in modules:
            models = await database_service.get_module_models(db, module.id)
            for model in models:
                if not model.image_url:
                    continue

                # 命名规则：{模块名}/用例图.png、{模块名}/类图.png、{模块名}/时序图_{usecase_name}.png
                if model.model_type == "sequence" and model.usecase_name:
                    filename = f"{module.module_name}/时序图_{model.usecase_name}.png"
                else:
                    chinese_name = model_type_name_map.get(model.model_type, model.model_type)
                    filename = f"{module.module_name}/{chinese_name}.png"

                try:
                    if model.image_url.startswith("http"):
                        # 远程地址（PlantUML 渲染服务器等），异步下载
                        async with session.get(model.image_url) as resp:
                            resp.raise_for_status()
                            content = await resp.read()
                    else:
                        # 本地路径或 OSS Key，读取为 bytes
                        if "/" in model.image_url and not model.image_url.startswith("/"):
                            # OSS Key，生成签名 URL 后下载
                            signed_url = oss_client.get_signed_url(model.image_url, expire=3600)
                            async with session.get(signed_url) as resp:
                                resp.raise_for_status()
                                content = await resp.read()
                        else:
                            # 本地文件路径
                            with open(model.image_url, "rb") as f:
                                content = f.read()

                    zip_contents.append((filename, content))
                except Exception as e:
                    print(f"[WARN] 下载图片失败 ({filename}): {e}")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, fcontent in zip_contents:
            zf.writestr(fname, fcontent)

    encoded_name = quote(zip_name)
    zip_buffer.seek(0)
    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.post("/{project_id}/export-all-modules-images")
async def export_all_modules_images(
    project_id: int,
    req: ExportModulesRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    一键打包复杂项目的所有模块图片。

    - 查询所有子模块及其 UMLModel
    - 命名规则与 /assets/{project_id} 一致：
      {模块名}/用例图.png、{模块名}/类图.png、{模块名}/时序图_{usecase_name}.png
    - 无 image_url 的记录会被跳过
    """
    if not req.module_ids:
        raise HTTPException(status_code=400, detail="module_ids 不能为空")

    modules = await database_service.get_modules_by_ids(db, req.module_ids)
    if not modules:
        raise HTTPException(status_code=404, detail="未找到任何指定的模块")

    project = await database_service.get_project_by_id(db, project_id)
    project_name = project.name if project else f"project_{project_id}"
    zip_name = f"{project_name}_UML图.zip"

    import aiohttp
    from urllib.parse import quote

    zip_contents: List[tuple[str, bytes]] = []
    model_type_name_map = {
        "usecase": "用例图",
        "class": "类图",
        "sequence": "时序图",
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        for module in modules:
            models = await database_service.get_module_models(db, module.id)
            for model in models:
                if not model.image_url:
                    continue
                if model.model_type == "sequence" and model.usecase_name:
                    filename = f"{module.module_name}/时序图_{model.usecase_name}.png"
                else:
                    chinese_name = model_type_name_map.get(model.model_type, model.model_type)
                    filename = f"{module.module_name}/{chinese_name}.png"
                try:
                    if model.image_url.startswith("http"):
                        async with session.get(model.image_url) as resp:
                            resp.raise_for_status()
                            content = await resp.read()
                    else:
                        if "/" in model.image_url and not model.image_url.startswith("/"):
                            signed_url = oss_client.get_signed_url(model.image_url, expire=3600)
                            async with session.get(signed_url) as resp:
                                resp.raise_for_status()
                                content = await resp.read()
                        else:
                            with open(model.image_url, "rb") as f:
                                content = f.read()
                    zip_contents.append((filename, content))
                except Exception as e:
                    print(f"[WARN] 下载图片失败 ({filename}): {e}")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, fcontent in zip_contents:
            zf.writestr(fname, fcontent)

    encoded_name = quote(zip_name)
    zip_buffer.seek(0)
    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )
