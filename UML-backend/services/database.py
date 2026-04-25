"""Database service for CRUD operations on Project and UMLModel tables."""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from sqlalchemy import delete, text, select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from models.database import engine
from models.uml import Project, UMLModel, ProjectModule

logger = logging.getLogger(__name__)

# 旧库若先于 ORM 建表，可能缺少下列列；启动时按名补齐（与当前 uml_models 设计一致）。
_UML_MODELS_MISSING_COLUMN_DDL: list[tuple[str, str]] = [
    ("puml_code", "ALTER TABLE uml_models ADD COLUMN puml_code TEXT NULL"),
    ("image_url", "ALTER TABLE uml_models ADD COLUMN image_url LONGTEXT NULL"),
    ("is_confirmed", "ALTER TABLE uml_models ADD COLUMN is_confirmed TINYINT(1) NOT NULL DEFAULT 0"),
    ("updated_at", "ALTER TABLE uml_models ADD COLUMN updated_at DATETIME NULL"),
    ("usecase_name", "ALTER TABLE uml_models ADD COLUMN usecase_name VARCHAR(255) NULL"),
]


async def ensure_uml_models_schema(conn) -> None:
    """若 `uml_models` 表存在但列落后于 `UMLModel`，则执行 ADD COLUMN（幂等）。"""
    try:
        chk = await conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'uml_models'"
            )
        )
        if chk.scalar_one() == 0:
            return
    except Exception as e:
        logger.warning("skip uml_models schema patch: %s", e)
        return

    for col_name, ddl in _UML_MODELS_MISSING_COLUMN_DDL:
        try:
            r = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'uml_models' "
                    "AND COLUMN_NAME = :name"
                ),
                {"name": col_name},
            )
            if r.scalar_one() > 0:
                continue
            await conn.execute(text(ddl))
            logger.info("uml_models: added missing column %s", col_name)
        except Exception as e:
            logger.warning("uml_models: could not add column %s: %s", col_name, e)


class DatabaseService:
    """Async CRUD service for projects and UML models."""

    # ------------------------------------------------------------------
    # 1. 系统基础
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """检查数据库连通性（main.py 启动时会调用）。"""
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"数据库连通性检查失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 2. 项目 (Project) CRUD
    # ------------------------------------------------------------------

    async def create_project(
        self,
        db: AsyncSession,
        name: str,
        req_text: str,
        thread_id: str,
        is_complex: bool = False,
        original_file_url: str = None,
        description: str = None,
    ) -> Project:
        """创建一个新的建模项目。"""
        project = Project(
            name=name,
            description=description,
            requirement_text=req_text,
            thread_id=thread_id,
            is_complex=is_complex,
            original_file_url=original_file_url,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return project

    async def list_projects(self, db: AsyncSession) -> List[Project]:
        """返回所有项目，按创建时间倒序。"""
        statement = select(Project).order_by(Project.created_at.desc())
        result = await db.exec(statement)
        return list(result.all())

    async def get_project_by_id(
        self, db: AsyncSession, project_id: int
    ) -> Optional[Project]:
        """通过 project_id 查找项目。"""
        statement = select(Project).where(Project.id == project_id)
        result = await db.exec(statement)
        return result.first()

    async def get_project_by_thread(
        self, db: AsyncSession, thread_id: str
    ) -> Optional[Project]:
        """通过 thread_id 查找项目。"""
        statement = select(Project).where(Project.thread_id == thread_id)
        result = await db.exec(statement)
        return result.first()

    async def delete_project(self, db: AsyncSession, project_id: int) -> bool:
        """删除项目（先删子表，再删项目）。

        不使用 ``session.delete(project)``：ORM 级联会懒加载 ``UMLModel``，若库表列少于模型定义会 SELECT 失败。
        全程用 ``delete()`` 语句，只发 DELETE，不加载子行。
        """
        project = await self.get_project_by_id(db, project_id)
        if not project:
            return False
        await db.execute(delete(UMLModel).where(UMLModel.project_id == project_id))
        await db.execute(delete(ProjectModule).where(ProjectModule.project_id == project_id))
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()
        return True

    async def delete_projects_batch(self, db: AsyncSession, project_ids: List[int]) -> int:
        """批量删除项目，返回成功删除的数量。"""
        deleted_count = 0
        for project_id in project_ids:
            success = await self.delete_project(db, project_id)
            if success:
                deleted_count += 1
        return deleted_count

    async def update_project(
        self,
        db: AsyncSession,
        project_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        requirement_text: Optional[str] = None,
    ) -> Optional[Project]:
        """更新项目的基本信息（名称、描述、需求文本）。"""
        project = await self.get_project_by_id(db, project_id)
        if not project:
            return None
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if requirement_text is not None:
            project.requirement_text = requirement_text
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return project

    # ------------------------------------------------------------------
    # 4. 子模块 (ProjectModule) CRUD
    # ------------------------------------------------------------------

    async def list_modules_by_project(
        self, db: AsyncSession, project_id: int
    ) -> List[ProjectModule]:
        """列出某复杂项目下的所有子模块。"""
        statement = (
            select(ProjectModule)
            .where(ProjectModule.project_id == project_id)
            .order_by(ProjectModule.created_at.asc())
        )
        result = await db.exec(statement)
        return list(result.all())

    async def get_module_by_id(
        self, db: AsyncSession, module_id: int
    ) -> Optional[ProjectModule]:
        """通过 module_id 查找子模块。"""
        statement = select(ProjectModule).where(ProjectModule.id == module_id)
        result = await db.exec(statement)
        return result.first()

    async def create_module(
        self,
        db: AsyncSession,
        project_id: int,
        module_name: str,
        core_requirements: str,
        thread_id: str,
        description: Optional[str] = None,
    ) -> ProjectModule:
        """手动新增一个子模块。"""
        module = ProjectModule(
            project_id=project_id,
            module_name=module_name,
            description=description,
            core_requirements=core_requirements,
            thread_id=thread_id,
        )
        db.add(module)
        await db.commit()
        await db.refresh(module)
        return module

    async def update_module(
        self,
        db: AsyncSession,
        module_id: int,
        module_name: Optional[str] = None,
        description: Optional[str] = None,
        core_requirements: Optional[str] = None,
    ) -> Optional[ProjectModule]:
        """更新模块的名称、描述或核心需求。"""
        module = await self.get_module_by_id(db, module_id)
        if not module:
            return None
        if module_name is not None:
            module.module_name = module_name
        if description is not None:
            module.description = description
        if core_requirements is not None:
            module.core_requirements = core_requirements
        db.add(module)
        await db.commit()
        await db.refresh(module)
        return module

    async def delete_module(self, db: AsyncSession, module_id: int) -> bool:
        """删除模块（级联删除其关联的 UMLModel）。"""
        module = await self.get_module_by_id(db, module_id)
        if not module:
            return False
        # 关联的 UMLModel 通过 cascade all,delete-orphan 自动删除
        await db.execute(delete(UMLModel).where(UMLModel.module_id == module_id))
        await db.execute(delete(ProjectModule).where(ProjectModule.id == module_id))
        await db.commit()
        return True

    async def delete_modules_batch(self, db: AsyncSession, module_ids: List[int]) -> int:
        """批量删除模块（级联删除其关联的 UMLModel），返回删除数量。"""
        if not module_ids:
            return 0
        # 先删除关联的 UMLModel
        await db.execute(delete(UMLModel).where(UMLModel.module_id.in_(module_ids)))
        # 再删除模块
        await db.execute(delete(ProjectModule).where(ProjectModule.id.in_(module_ids)))
        await db.commit()
        return len(module_ids)

    async def get_module_models(
        self, db: AsyncSession, module_id: int
    ) -> List[UMLModel]:
        """获取某模块关联的所有 UML 模型。"""
        statement = (
            select(UMLModel)
            .where(UMLModel.module_id == module_id)
            .order_by(UMLModel.created_at.asc())
        )
        result = await db.exec(statement)
        return list(result.all())

    async def get_modules_by_ids(
        self, db: AsyncSession, module_ids: List[int]
    ) -> List[ProjectModule]:
        """批量获取模块列表。"""
        if not module_ids:
            return []
        statement = select(ProjectModule).where(ProjectModule.id.in_(module_ids))
        result = await db.exec(statement)
        return list(result.all())

    # ------------------------------------------------------------------
    # 5. UML 模型 (UMLModel) CRUD
    # ------------------------------------------------------------------

    async def save_initial_uml_model(
        self,
        db: AsyncSession,
        project_id: int,
        model_type: str,
        data_json: Dict[str, Any],
        usecase_name: str = None,
        module_id: int = None,
    ) -> UMLModel:
        """保存 LLM 提取的中间态 JSON（is_confirmed=False）。

        模块模式下按 module_id 去重；非模块模式按 project_id 去重。
        """
        existing = None
        if model_type == "sequence" and usecase_name:
            existing = await self.get_sequence_model(db, project_id, usecase_name, module_id)
        else:
            existing = await self.get_latest_model(db, project_id, model_type, module_id)

        if existing:
            existing.data_json = data_json
            existing.is_confirmed = False
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
            return existing

        uml_model = UMLModel(
            project_id=project_id,
            module_id=module_id,
            model_type=model_type,
            data_json=data_json,
            is_confirmed=False,
            usecase_name=usecase_name,
        )
        db.add(uml_model)
        await db.commit()
        await db.refresh(uml_model)
        return uml_model

    async def update_model_with_puml(
        self,
        db: AsyncSession,
        project_id: int,
        model_type: str,
        confirmed_data: Dict[str, Any],
        puml_code: str = None,
        image_url: str = None,
        usecase_name: str = None,
        is_regenerate: bool = True,
        module_id: int = None,
    ) -> Optional[UMLModel]:
        """更新/保存最终 UML 模型（is_confirmed=True），支持模块模式。"""
        # 查询已有记录：按 module_id 或 project_id 区分
        statement = select(UMLModel).where(UMLModel.model_type == model_type)
        if module_id is not None:
            statement = statement.where(UMLModel.module_id == module_id)
        else:
            statement = statement.where(UMLModel.project_id == project_id)
        if model_type == "sequence" and usecase_name:
            statement = statement.where(UMLModel.usecase_name == usecase_name)
        else:
            statement = statement.where(UMLModel.usecase_name.is_(None))
        result = await db.exec(statement)
        model = result.first()

        if model:
            # 更新已有记录
            model.data_json = confirmed_data
            model.puml_code = puml_code
            model.image_url = image_url
            model.is_confirmed = True
            model.usecase_name = usecase_name
            model.updated_at = datetime.now()
            if is_regenerate:
                model.created_at = datetime.now()
            db.add(model)
            await db.commit()
            await db.refresh(model)
            return model

        # 不存在则新建（首次生成时刻）
        uml_model = UMLModel(
            project_id=project_id,
            module_id=module_id,
            model_type=model_type,
            data_json=confirmed_data,
            puml_code=puml_code,
            image_url=image_url,
            is_confirmed=True,
            usecase_name=usecase_name,
        )
        # 确保创建时间和修改时间一致
        uml_model.updated_at = uml_model.created_at
        db.add(uml_model)
        await db.commit()
        await db.refresh(uml_model)
        return uml_model

    async def save_sequence_diagram(
        self,
        db: AsyncSession,
        project_id: int,
        usecase_name: str,
        data_json: Dict[str, Any],
        puml_code: str,
        image_url: str,
        is_regenerate: bool = True,
        module_id: int = None,
    ) -> UMLModel:
        """时序图专用：为每个用例保存或更新一条记录。

        模块模式下按 module_id 查询；非模块模式按 project_id 查询。
        """
        existing = await self.get_sequence_model(db, project_id, usecase_name, module_id)
        if existing:
            existing.data_json = data_json
            existing.puml_code = puml_code
            existing.image_url = image_url
            existing.is_confirmed = True
            existing.updated_at = datetime.now()
            if is_regenerate:
                existing.created_at = datetime.now()
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
            return existing

        uml_model = UMLModel(
            project_id=project_id,
            module_id=module_id,
            model_type="sequence",
            usecase_name=usecase_name,
            data_json=data_json,
            puml_code=puml_code,
            image_url=image_url,
            is_confirmed=True,
        )
        uml_model.updated_at = uml_model.created_at
        db.add(uml_model)
        await db.commit()
        await db.refresh(uml_model)
        return uml_model

    async def get_sequence_model(
        self, db: AsyncSession, project_id: int, usecase_name: str, module_id: int = None
    ) -> Optional[UMLModel]:
        """时序图专用：按项目+用例名查询，支持模块模式。"""
        statement = select(UMLModel).where(
            UMLModel.model_type == "sequence",
            UMLModel.usecase_name == usecase_name,
        )
        if module_id is not None:
            statement = statement.where(UMLModel.module_id == module_id)
        else:
            statement = statement.where(UMLModel.project_id == project_id)
        statement = statement.order_by(UMLModel.created_at.desc())
        result = await db.exec(statement)
        return result.first()

    async def list_sequence_models(
        self, db: AsyncSession, project_id: int, module_id: int = None
    ) -> List[UMLModel]:
        """时序图专用：列出某项目/模块下所有用例的时序图。"""
        statement = (
            select(UMLModel)
            .where(UMLModel.model_type == "sequence")
            .order_by(UMLModel.created_at.desc())
        )
        if module_id is not None:
            statement = statement.where(UMLModel.module_id == module_id)
        else:
            statement = statement.where(UMLModel.project_id == project_id)
        result = await db.exec(statement)
        return list(result.all())

    async def get_latest_model(
        self, db: AsyncSession, project_id: int, model_type: str, module_id: int = None
    ) -> Optional[UMLModel]:
        """获取指定项目和类型的最新模型记录，支持模块模式。"""
        statement = select(UMLModel).where(UMLModel.model_type == model_type)
        if module_id is not None:
            statement = statement.where(UMLModel.module_id == module_id)
        else:
            statement = statement.where(UMLModel.project_id == project_id)
        statement = statement.order_by(UMLModel.created_at.desc())
        result = await db.exec(statement)
        return result.first()

    async def get_latest_confirmed_model(
        self, db: AsyncSession, project_id: int, model_type: str, module_id: int = None
    ) -> Optional[UMLModel]:
        """获取指定项目和类型的最新已确认模型记录，支持模块模式。"""
        statement = select(UMLModel).where(
            UMLModel.model_type == model_type,
            UMLModel.is_confirmed == True,
        )
        if module_id is not None:
            statement = statement.where(UMLModel.module_id == module_id)
        else:
            statement = statement.where(UMLModel.project_id == project_id)
        statement = statement.order_by(UMLModel.created_at.desc())
        result = await db.exec(statement)
        return result.first()

    async def delete_uml_model(
        self,
        db: AsyncSession,
        project_id: int,
        model_type: str,
        usecase_name: Optional[str] = None,
        module_id: int = None,
    ) -> bool:
        """删除 UML 模型记录。

        - module_id 非空时：按 module_id 过滤（模块模式）。
        - model_type 为 sequence 且传入 usecase_name：仅删除该特定用例的消息记录。
        - 否则：删除该 project_id + model_type 下的全部记录。
        返回 True 表示有记录被删除，False 表示无匹配记录。
        """
        statement = select(UMLModel).where(
            UMLModel.model_type == model_type,
        )
        if module_id is not None:
            statement = statement.where(UMLModel.module_id == module_id)
        else:
            statement = statement.where(UMLModel.project_id == project_id)
        if model_type == "sequence" and usecase_name:
            statement = statement.where(UMLModel.usecase_name == usecase_name)

        result = await db.exec(statement)
        records = list(result.all())
        if not records:
            return False

        for record in records:
            await db.delete(record)
        await db.commit()
        return True

    async def list_models_by_project(
        self, db: AsyncSession, project_id: int
    ) -> List[UMLModel]:
        """列出某项目下的所有 UML 模型。"""
        statement = (
            select(UMLModel)
            .where(UMLModel.project_id == project_id)
            .order_by(UMLModel.created_at.desc())
        )
        result = await db.exec(statement)
        return list(result.all())


# 模块级单例，供其他模块直接引入
database_service = DatabaseService()
