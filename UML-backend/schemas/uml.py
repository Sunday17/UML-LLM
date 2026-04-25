"""UML-related Pydantic schemas."""

from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, List, Optional


# ================================================================
# 1. 项目管理
# ================================================================

class ProjectCreate(BaseModel):
    name: str = Field(..., example="图书管理系统")
    description: Optional[str] = Field(default=None, example="一个用于管理图书借阅的系统")
    requirement_text: str = Field(..., example="用户可以注册、登录、查询图书")
    is_complex: bool = Field(default=False, description="是否为复杂项目（上传文档后自动置为 True）")
    original_file_url: Optional[str] = Field(default=None, description="原始上传文件的本地路径或 file:// URL")


class ProjectOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    requirement_text: str
    thread_id: str
    user_id: int = 0
    is_complex: bool = False
    original_file_url: Optional[str] = None
    created_at: Any

    model_config = {"from_attributes": True}

    @field_validator("user_id", mode="before")
    @classmethod
    def user_id_none_as_zero(cls, v: object) -> int:
        """库中 user_id 可为 NULL，与 int 字段冲突时统一为 0。"""
        if v is None:
            return 0
        return int(v)  # type: ignore[arg-type]


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, description="项目名称（可选）")
    description: Optional[str] = Field(default=None, description="项目描述（可选）")
    requirement_text: Optional[str] = Field(default=None, description="需求文本（可选）")


# ================================================================
# 2. 提取接口 (针对不同图类型)
# ================================================================

class ExtractRequest(BaseModel):
    project_id: int
    module_id: Optional[int] = Field(default=None, description="模块 ID（模块模式下使用，优先于 project_id）")
    selected_usecases: Optional[List[str]] = Field(
        default=None,
        description="时序图专用：前端选择的用例列表，不传则提取全部",
    )


# ================================================================
# 3. 时序图选项（用例列表）
# ================================================================

class SequenceOptionsResponse(BaseModel):
    project_id: int
    options: List[str] = Field(description="已确认的用例名称列表，供前端选择")

class TableDataResponse(BaseModel):
    project_id: int
    thread_id: str
    model_type: str
    extracted_data: Dict[str, Any] = Field(
        ...,
        description=(
            "usecase: {actors:[], usecases:[], entities:{}}  "
            "class:  {classes:[], class_details:{}, class_relationships:{}}  "
            "sequence:{sequence_data:{}}"
        ),
    )
    usecase_name: Optional[str] = Field(default=None, description="时序图专用：关联的用例名称")


# ================================================================
# 4. 确认并生成请求
# ================================================================

class GenerateRequest(BaseModel):
    project_id: int
    module_id: Optional[int] = Field(default=None, description="模块 ID（模块模式下使用，优先于 project_id）")
    confirmed_data: Dict[str, Any] = Field(
        ...,
        description="用户在表格中修改后的确认数据，格式同 extracted_data",
    )
    selected_usecases: Optional[List[str]] = Field(
        default=None,
        description="时序图专用：指定重新生成哪些用例，不传则生成全部",
    )


# ================================================================
# 5. 最终产物响应
# ================================================================

class SequenceDiagramItem(BaseModel):
    """时序图单个用例的完整数据。"""
    usecase_name: str
    puml_code: str = Field(..., description="该用例的 PlantUML 源码")
    image_url: str = Field(..., description="该用例的预览图")


class SequenceExtractResponse(BaseModel):
    """时序图 extract 阶段响应：每个用例返回 PUML 源码 + 预览图。"""
    project_id: int
    thread_id: str
    diagrams: List[SequenceDiagramItem]
    extracted_data: Dict[str, Any] = Field(default_factory=dict, description="时序图的 sequence_data")


class UMLFinalResponse(BaseModel):
    puml_code: Optional[str] = Field(default=None, description="PlantUML 源码（usecase/class 用）")
    image_url: Optional[str] = Field(default=None, description="预览图（usecase/class 用）")
    diagrams: Optional[List[SequenceDiagramItem]] = Field(
        default=None,
        description="时序图专用：按用例拆分的多张图列表",
    )


# ================================================================
# 7. UML 图表删除
# ================================================================

class UMLDeleteRequest(BaseModel):
    project_id: int
    module_id: Optional[int] = Field(default=None, description="模块 ID（模块模式下使用）")
    model_type: str = Field(..., description="图类型：usecase / class / sequence")
    usecase_name: Optional[str] = Field(
        default=None,
        description="时序图专用：指定删除特定用例的记录，不传则删除该类型全部记录",
    )


# ================================================================
# 6. PUML 逆向同步
# ================================================================

class SyncRequest(BaseModel):
    project_id: int
    module_id: Optional[int] = Field(default=None, description="模块 ID（模块模式下使用）")
    model_type: str = Field(..., example="usecase")
    puml_code: str = Field(..., example="@startuml\n:Actor: -> (UseCase)\n@enduml")
    usecase_name: Optional[str] = Field(default=None, description="时序图专用：指定同步哪个用例")


class SyncResponse(BaseModel):
    image_url: Optional[str] = Field(default=None, description="重新渲染后的预览（usecase/class 用）")
    diagrams: Optional[List[SequenceDiagramItem]] = Field(
        default=None,
        description="时序图专用：按用例拆分的多张图列表",
    )


# ================================================================
# 8. 获取已保存的 UML 数据
# ================================================================

class UMLModelItem(BaseModel):
    """单个 UML 模型记录"""
    id: int
    model_type: str
    module_id: Optional[int] = None
    usecase_name: Optional[str] = None
    puml_code: Optional[str] = None
    image_url: Optional[str] = None
    is_confirmed: bool
    created_at: Any
    updated_at: Optional[Any] = None

    model_config = {"from_attributes": True}


class GetUMLResponse(BaseModel):
    """获取指定项目下某类型 UML 数据的响应"""
    model_type: str
    records: List[UMLModelItem] = Field(description="该类型的全部记录，时序图可能有多条")


# ================================================================
# 9. 复杂项目拆分（子模块）
# ================================================================

class ProjectModuleOut(BaseModel):
    id: int
    project_id: int
    module_name: str
    description: Optional[str] = None
    core_requirements: str
    thread_id: str
    created_at: Any

    model_config = {"from_attributes": True}


class ModuleCreate(BaseModel):
    module_name: str = Field(..., example="用户管理模块")
    description: Optional[str] = Field(default=None, example="负责用户注册、登录、权限管理")
    core_requirements: str = Field(..., example="用户可注册、登录、修改密码、设置角色权限")


class ModuleUpdate(BaseModel):
    module_name: Optional[str] = Field(default=None, example="用户管理模块（修订版）")
    description: Optional[str] = Field(default=None, example="新增第三方登录支持")
    core_requirements: Optional[str] = Field(default=None, example="增加微信登录功能")


class ExportModulesRequest(BaseModel):
    module_ids: List[int] = Field(..., description="要导出的模块 ID 列表")
