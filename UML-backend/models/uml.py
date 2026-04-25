# app/models/uml.py
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from sqlalchemy import Column, Text
from sqlalchemy.dialects.mysql import JSON
from sqlmodel import SQLModel, Field, Relationship


def _now() -> datetime:
    """返回本地时间。"""
    return datetime.now()


class ProjectModule(SQLModel, table=True):
    """项目拆分出的子模块"""
    __tablename__ = "project_modules"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True, description="所属母项目ID")
    module_name: str = Field(max_length=255, description="模块名称")
    description: Optional[str] = Field(default=None, description="模块描述")
    core_requirements: str = Field(sa_column=Column(Text), description="该模块的核心需求文本")
    thread_id: str = Field(max_length=100, unique=True, index=True, description="该子模块的独立会话ID")
    created_at: datetime = Field(default_factory=_now)

    project: "Project" = Relationship(back_populates="split_modules")
    models: List["UMLModel"] = Relationship(
        back_populates="module",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: Optional[int] = Field(default=None, primary_key=True, description="项目ID")
    name: str = Field(max_length=255, description="项目名称")
    description: Optional[str] = Field(default=None, description="项目描述")
    requirement_text: Optional[str] = Field(default=None, description="用户输入的原始需求文本（复杂母项目可为NULL）")
    thread_id: Optional[str] = Field(default=None, max_length=100, unique=True, index=True, description="LangGraph的会话ID（复杂母项目可为NULL）")
    is_complex: bool = Field(default=False, description="是否为复杂母项目")
    original_file_url: Optional[str] = Field(default=None, max_length=500, description="原始上传文件URL")
    original_file_name: Optional[str] = Field(default=None, max_length=255, description="原始上传文件名")
    created_at: datetime = Field(default_factory=_now)

    models: List["UMLModel"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    split_modules: List["ProjectModule"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

class UMLModel(SQLModel, table=True):
    __tablename__ = "uml_models"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="projects.id", index=True, description="所属项目ID（简单模式使用）")
    module_id: Optional[int] = Field(default=None, foreign_key="project_modules.id", index=True, description="所属模块ID（拆分模式使用）")
    model_type: str = Field(max_length=50, description="用例图(usecase)/类图(class)/时序图(sequence)")
    usecase_name: Optional[str] = Field(
        default=None,
        max_length=255,
        index=True,
        description="时序图专用：关联的用例名称，usecase/class 图为 NULL",
    )
    
    # 使用 SQLAlchemy 的 JSON 列，完美适配 MySQL 5.7+
    data_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    puml_code: Optional[str] = Field(default=None, description="PlantUML 源码")
    # 与库表 image_url 一致：可存外链，也可存 data URL（列类型建议 TEXT/LONGTEXT）
    image_url: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="预览图 URL 或 data URL",
    )
    is_confirmed: bool = Field(default=False, description="用户是否已确认")

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now, description="最后更新时间")

    project: Optional["Project"] = Relationship(back_populates="models")
    module: Optional["ProjectModule"] = Relationship(back_populates="models")