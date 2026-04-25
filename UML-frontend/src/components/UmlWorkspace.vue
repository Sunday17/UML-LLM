<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { VueMonacoEditor } from '@guolao/vue-monaco-editor'
import { Delete, Edit } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getProject, getProjectModules, updateProjectModule } from '@/api/projects'
import { getSequenceOptions, getSavedUML, extractEntities, generateDiagram, syncCode, deleteUmlRecord } from '@/api/uml'
import { downloadImageUrl } from '@/utils/download'

const route = useRoute()

const props = defineProps({
  modelType: {
    type: String,
    required: true,
  },
  projectId: {
    type: [Number, String],
    required: true,
  },
  moduleId: {
    type: [Number, String],
    default: null,
  },
  // 是否在 UmlWorkspace 内部显示模块编辑头部（detail.vue 已接管编辑，此处可隐藏）
  showModuleHeader: {
    type: Boolean,
    default: true,
  },
  // 用于文件名的显示名称（项目名-模块名），由 detail.vue 传入
  displayName: {
    type: String,
    default: '',
  },
})

// 模块模式下：优先从 props 读取，其次从 query 参数读取（来自 /project/module 路由）
const effectiveModuleId = computed(() => {
  if (props.moduleId != null) return String(props.moduleId)
  return route.query.module_id ? String(route.query.module_id) : null
})

// 兼容 /project/module?modelType=xxx&module_id=xxx&project_id=xxx 模式
const effectiveModelType = computed(() => {
  const propVal = props.modelType
  if (propVal !== undefined && propVal !== null) return propVal
  return route.query.modelType || 'usecase'
})

const effectiveProjectId = computed(() => {
  const propVal = props.projectId
  if (propVal != null) return String(propVal)
  return route.query.project_id ? String(route.query.project_id) : null
})

// 项目名称（用于图片命名）
const projectName = ref('')

// ==================== 状态定义 ====================
// status: idle | viewing | editing | selecting | extracting | confirming | generating | success
const status = ref('idle')
const threadId = ref(null)
const prevStatusBeforeSelecting = ref(null) // 选择模式前的状态（用于取消时恢复)
const extractedData = ref(null)
const pumlCode = ref('')
const imageUrl = ref('')
const loading = ref(false)
const deleteLoading = ref(false)

// 用于确认阶段编辑的表单数据（已弃用，改用表格编辑）
// const editableData = ref('')

// 时序图专用状态
const sequenceOptions = ref([])
const selectedUsecases = ref([])
const isSequence = computed(() => effectiveModelType.value === 'sequence')

// 已保存的记录（查看模式用）
const savedRecords = ref([])
// 当前选中的时序图记录（卡片点击后）
const selectedRecord = ref(null)

// 批量删除选择状态
const batchDeleteMode = ref(false)
const batchSelectedIds = ref([])

// ==================== 模块信息编辑 ====================
const isModuleMode = computed(() => effectiveModuleId.value !== null)
const moduleEditing = ref(false)
const moduleForm = ref({
  name: '',
  description: '',
  core_requirements: '',
})
const moduleLoading = ref(false)

// ==================== 确认环节表格数据 ====================
// 用于用例图/类图的可视化表格编辑
const actorsTableData = ref([])     // 参与者表格数据 [{ name: '...' }]
const usecasesTableData = ref([])   // 用例表格数据 [{ name: '...' }]
const classesTableData = ref([])     // 类表格数据 [{ name: '...', attributes: '...', methods: '...' }]
const useCaseMapping = ref([])       // 用例图关联表 [{ actor: '...', usecases: ['...'] }]
const newUsecases = ref({})          // 用例图每行的待添加用例输入 [{ rowIdx: '' }]
const prevStatusBeforeConfirm = ref(null)  // 保存进入确认环节前的状态

// ==================== 计算属性 ====================
const isExtracting = computed(() => status.value === 'extracting')
const isConfirming = computed(() => status.value === 'confirming')
const isGenerating = computed(() => status.value === 'generating')
const isSuccess = computed(() => status.value === 'success')
const isSelecting = computed(() => status.value === 'selecting')
const isViewing = computed(() => status.value === 'viewing')
const isEditing = computed(() => status.value === 'editing')
const isModuleLoading = computed(() => moduleLoading.value)

// 已生成的用例名集合（用于在选择页面区分标注）
const generatedUsecaseNames = computed(() => new Set(savedRecords.value.map(r => r.usecase_name)))

const selectAll = computed({
  get: () => batchSelectedIds.value.length === savedRecords.value.length && savedRecords.value.length > 0,
  set: (val) => {
    if (val) {
      batchSelectedIds.value = savedRecords.value.map(r => r.usecase_name)
    } else {
      batchSelectedIds.value = []
    }
  },
})

const isIndeterminate = computed(() => {
  return batchSelectedIds.value.length > 0 && batchSelectedIds.value.length < savedRecords.value.length
})

const toggleRecordSelection = (usecaseName) => {
  const idx = batchSelectedIds.value.indexOf(usecaseName)
  if (idx === -1) {
    batchSelectedIds.value.push(usecaseName)
  } else {
    batchSelectedIds.value.splice(idx, 1)
  }
}

const handleSelectAll = (val) => {
  selectAll.value = val
}

// ==================== 批量删除 ====================
const toggleBatchDeleteMode = () => {
  batchDeleteMode.value = !batchDeleteMode.value
  if (!batchDeleteMode.value) {
    batchSelectedIds.value = []
  }
}

const handleBatchDelete = async () => {
  if (batchSelectedIds.value.length === 0) {
    ElMessage.warning('请先选择要删除的时序图')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${batchSelectedIds.value.length} 张时序图吗？此操作不可恢复。`,
      '批量删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    deleteLoading.value = true
    for (const usecaseName of batchSelectedIds.value) {
      await deleteUmlRecord({
        project_id: effectiveProjectId.value,
        ...(effectiveModuleId.value ? { module_id: Number(effectiveModuleId.value) } : {}),
        model_type: 'sequence',
        usecase_name: usecaseName,
      })
    }
    ElMessage.success(`成功删除 ${batchSelectedIds.value.length} 张时序图`)
    batchDeleteMode.value = false
    batchSelectedIds.value = []
    await loadSavedData()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('批量删除失败:', error)
      ElMessage.error('批量删除失败')
    }
  } finally {
    deleteLoading.value = false
  }
}

// ==================== 生命周期 ====================

onMounted(async () => {
  await loadSavedData()
})

// ==================== 核心业务函数 ====================

// 获取项目信息（包含需求文本）
const fetchProjectData = async () => {
  try {
    const project = await getProject(effectiveProjectId.value)
    projectName.value = project.name || ''
    return project.requirement_text || ''
  } catch (error) {
    console.error('获取项目信息失败:', error)
    return ''
  }
}

// 获取模块信息（包含核心需求）
const fetchModuleData = async () => {
  try {
    const modules = await getProjectModules(effectiveProjectId.value)
    const module = modules.find(m => String(m.id) === effectiveModuleId.value)
    if (module) {
      projectName.value = module.module_name || ''
      moduleForm.value = {
        name: module.module_name || '',
        description: module.description || '',
        core_requirements: module.core_requirements || '',
      }
      return module.core_requirements || ''
    }
    return ''
  } catch (error) {
    console.error('获取模块信息失败:', error)
    return ''
  }
}

// 保存模块信息
const handleSaveModule = async () => {
  if (!moduleForm.value.name.trim()) {
    ElMessage.warning('请输入模块名称')
    return
  }
  if (!moduleForm.value.core_requirements.trim()) {
    ElMessage.warning('请输入核心需求')
    return
  }
  moduleLoading.value = true
  try {
    await updateProjectModule(effectiveModuleId.value, {
      module_name: moduleForm.value.name.trim(),
      description: moduleForm.value.description.trim(),
      core_requirements: moduleForm.value.core_requirements.trim(),
    })
    ElMessage.success('更新成功')
    moduleEditing.value = false
    await fetchModuleData()
  } catch (error) {
    console.error('保存模块失败:', error)
    ElMessage.error('保存失败')
  } finally {
    moduleLoading.value = false
  }
}

// 进入模块编辑模式
const handleEditModule = async () => {
  await fetchModuleData()
  moduleEditing.value = true
}

// 取消模块编辑
const handleCancelModuleEdit = () => {
  moduleEditing.value = false
}

// 加载已保存的 UML 数据
// forceStatus: 可选，强制将 status 设置为指定值（如刷新列表后保持编辑态）
const loadSavedData = async (forceStatus) => {
  loading.value = true
  // 模块模式下：获取模块信息
  if (isModuleMode.value) {
    await fetchModuleData()
  }
  try {
    const res = await getSavedUML(effectiveModelType.value, effectiveProjectId.value, effectiveModuleId.value || undefined)
    savedRecords.value = res.records || []

    if (savedRecords.value.length > 0) {
      if (isSequence.value) {
        status.value = 'viewing'
      } else {
        const record = savedRecords.value[0]
        pumlCode.value = record.puml_code || ''
        imageUrl.value = record.image_url || ''
        selectedRecord.value = record
        status.value = 'viewing'
      }
    } else {
      status.value = 'idle'
    }

    // 强制覆盖状态（用于刷新列表后保持编辑态）
    if (forceStatus) {
      status.value = forceStatus
    }
  } catch (error) {
    console.error('加载已保存数据失败:', error)
    status.value = 'idle'
  } finally {
    loading.value = false
  }
}

// 删除当前图表（用例图/类图）
const handleDeleteCurrent = async () => {
  try {
    await ElMessageBox.confirm(
      '确定要删除当前图表吗？此操作不可恢复。',
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    loading.value = true
    await deleteUmlRecord({
      project_id: effectiveProjectId.value,
      ...(effectiveModuleId.value ? { module_id: Number(effectiveModuleId.value) } : {}),
      model_type: effectiveModelType.value,
    })
    ElMessage.success('删除成功')
    await loadSavedData()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除失败:', error)
    }
  } finally {
    loading.value = false
  }
}

// 获取时序图可用的用例选项
const handleOpenSequenceSelector = async () => {
  // 进入选择模式前保存当前状态（用于取消时恢复）
  prevStatusBeforeSelecting.value = status.value

  loading.value = true
  try {
    const res = await getSequenceOptions(effectiveProjectId.value)
    sequenceOptions.value = res.options || []

    if (sequenceOptions.value.length === 0) {
      ElMessage.warning('未找到可用的用例，请先生成用例图')
      prevStatusBeforeSelecting.value = null
      return
    }

    selectedUsecases.value = [...sequenceOptions.value]
    status.value = 'selecting'
  } catch (error) {
    prevStatusBeforeSelecting.value = null
    const detail = error.response?.data?.detail
    if (detail) {
      ElMessage.error(detail)
    } else {
      ElMessage.error('获取可用用例失败')
    }
    console.error('获取时序图选项失败:', error)
  } finally {
    loading.value = false
  }
}

// 取消选择用例，返回之前的状态
const handleCancelSelection = () => {
  // 恢复到选择模式之前的状态
  if (prevStatusBeforeSelecting.value) {
    status.value = prevStatusBeforeSelecting.value
    prevStatusBeforeSelecting.value = null
  } else {
    // 兜底：如果没有保存的状态，重新加载数据
    loadSavedData()
  }
}

// 点击时序图卡片，进入编辑模式
const handleSelectSequence = (record) => {
  selectedRecord.value = record
  pumlCode.value = record.puml_code || ''
  imageUrl.value = record.image_url || ''
  threadId.value = null // 时序图不需要 thread_id
  status.value = 'editing'
}

// 从查看模式进入编辑模式
const handleEdit = () => {
  if (selectedRecord.value) {
    pumlCode.value = selectedRecord.value.puml_code || ''
    imageUrl.value = selectedRecord.value.image_url || ''
  }
  status.value = 'editing'
}

// 提取实体
const handleExtract = async () => {
  if (isSequence.value && selectedUsecases.value.length === 0) {
    ElMessage.warning('请至少选择一个用例')
    return
  }

  if (status.value === 'editing' || status.value === 'success') {
    try {
      await ElMessageBox.confirm(
        '重新提取将覆盖当前图表，是否继续？',
        '警告',
        {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning',
        }
      )
    } catch {
      return
    }
  }

  loading.value = true
  status.value = 'extracting'

  try {
    // 模块模式下获取模块的核心需求，否则获取项目的需求文本
    const requirementText = isModuleMode.value
      ? await fetchModuleData()
      : await fetchProjectData()
    if (!requirementText) {
      throw new Error(isModuleMode.value ? '模块核心需求为空，请先编辑模块信息' : '项目需求文本为空，请先在项目设置中添加需求')
    }

    const payload = {
      project_id: effectiveProjectId.value,
      ...(effectiveModuleId.value ? { module_id: Number(effectiveModuleId.value) } : {}),
    }

    if (isSequence.value) {
      payload.selected_usecases = selectedUsecases.value
    }

    const res = await extractEntities(effectiveModelType.value, payload)

      // 时序图：直接生成完成，显示卡片列表
    if (isSequence.value && res.diagrams) {
      await loadSavedData('viewing')
      selectedRecord.value = null
      pumlCode.value = ''
      imageUrl.value = ''
      ElMessage.success(`时序图生成成功，共 ${res.diagrams.length} 个用例`)
      return
    }

    // 用例图/类图：进入确认页面
    threadId.value = res.thread_id
    extractedData.value = res.extracted_data

    // 将字符串数组转换为对象数组，适配表格编辑
    if (effectiveModelType.value === 'class') {
      // 类图数据格式：{ classes: [{ name, attributes, methods }, ...] }
      classesTableData.value = (res.extracted_data.classes || []).map(c => ({
        name: typeof c === 'string' ? c : (c.name || ''),
        attributes: typeof c === 'object' ? (c.attributes || []).join(', ') : '',
        methods: typeof c === 'object' ? (c.methods || []).join(', ') : '',
      }))
    } else if (effectiveModelType.value === 'usecase') {
      // 用例图：从 res.extracted_data.entities 构建关联表
      useCaseMapping.value = Object.entries(res.extracted_data?.entities || {}).map(([actor, ucs]) => ({
        actor,
        usecases: [...(ucs || [])],
      }))
      newUsecases.value = {}
    }

    // 保存进入确认环节前的状态（用于取消时恢复）
    prevStatusBeforeConfirm.value = selectedRecord.value ? 'viewing' : 'idle'
    status.value = 'confirming'
    ElMessage.success('实体提取成功，请确认提取结果')
  } catch (error) {
    const prevStatus = threadId.value ? 'confirming' : 'idle'
    status.value = prevStatus
    const detail = error.response?.data?.detail
    if (detail) {
      ElMessage.error(detail)
    } else {
      ElMessage.error('提取失败')
    }
    console.error('提取失败:', error)
  } finally {
    loading.value = false
  }
}

// ==================== 确认环节表格操作 ====================
// 添加参与者
const addActor = () => {
  // 检查是否已有空行
  const hasEmpty = actorsTableData.value.some(a => !a.name.trim())
  if (hasEmpty) {
    ElMessage.warning('请先填写已有的空行，再添加新项')
    return
  }
  actorsTableData.value.push({ name: '' })
}

// 删除参与者
const removeActor = (index) => {
  actorsTableData.value.splice(index, 1)
}

// 添加用例
const addUsecase = () => {
  // 检查是否已有空行
  const hasEmpty = usecasesTableData.value.some(u => !u.name.trim())
  if (hasEmpty) {
    ElMessage.warning('请先填写已有的空行，再添加新项')
    return
  }
  usecasesTableData.value.push({ name: '' })
}

// 删除用例
const removeUsecase = (index) => {
  usecasesTableData.value.splice(index, 1)
}

// 添加关联行（检查空行后再添加）
const addMapping = () => {
  const hasEmpty = useCaseMapping.value.some(row => !row.actor.trim())
  if (hasEmpty) {
    ElMessage.warning('请先填写已有的空行，再添加新项')
    return
  }
  useCaseMapping.value.push({ actor: '', usecases: [] })
  newUsecases.value[useCaseMapping.value.length - 1] = ''
}

// 向指定行添加用例
const addUsecaseToMapping = (rowIdx) => {
  const name = (newUsecases.value[rowIdx] || '').trim()
  if (!name) {
    ElMessage.warning('请输入用例名称')
    return
  }
  useCaseMapping.value[rowIdx].usecases.push(name)
  newUsecases.value[rowIdx] = ''
}

// 从指定行删除用例
const removeUsecaseFromMapping = (rowIdx, ucIdx) => {
  useCaseMapping.value[rowIdx].usecases.splice(ucIdx, 1)
}

// 添加类
const addClass = () => {
  // 检查是否已有空行（类名不能为空）
  const hasEmpty = classesTableData.value.some(c => !c.name.trim())
  if (hasEmpty) {
    ElMessage.warning('请先填写已有的空行，再添加新项')
    return
  }
  classesTableData.value.push({ name: '', attributes: '', methods: '' })
}

// 删除类
const removeClass = (index) => {
  classesTableData.value.splice(index, 1)
}

// 取消确认，返回之前的状态
const handleCancelConfirm = () => {
  const prevStatus = prevStatusBeforeConfirm.value || 'idle'
  status.value = prevStatus
  prevStatusBeforeConfirm.value = null
}

// 确认并生成图表
const handleGenerate = async () => {
  // 从表格数据构建 confirmedData
  let confirmedData

  if (effectiveModelType.value === 'class') {
    // 类图：检查类名不能为空
    if (classesTableData.value.length === 0) {
      ElMessage.warning('请添加至少一个类')
      return
    }
    const emptyClass = classesTableData.value.find(c => !c.name.trim())
    if (emptyClass) {
      ElMessage.warning('类名不能为空')
      return
    }
    confirmedData = {
      classes: classesTableData.value.map(c => ({
        name: c.name.trim(),
        attributes: [],
        methods: [],
      })),
    }
  } else {
    // 用例图：从 useCaseMapping 构造 confirmed_data
    if (useCaseMapping.value.length === 0) {
      ElMessage.warning('请添加至少一个参与者')
      return
    }
    const emptyRow = useCaseMapping.value.find(row => !row.actor.trim())
    if (emptyRow) {
      ElMessage.warning('参与者名称不能为空')
      return
    }
    // 将关联表还原为 entities 对象 + 聚合 actors 和 usecases
    const entities = {}
    const allActors = []
    const allUsecases = new Set()
    for (const row of useCaseMapping.value) {
      const actorName = row.actor.trim()
      allActors.push(actorName)
      entities[actorName] = row.usecases.filter(u => u.trim()).map(u => u.trim())
      row.usecases.forEach(u => { if (u.trim()) allUsecases.add(u.trim()) })
    }
    confirmedData = {
      entities,
      actors: [...new Set(allActors)],
      usecases: [...allUsecases],
    }
  }

  loading.value = true
  status.value = 'generating'

  try {
    const res = await generateDiagram(effectiveModelType.value, {
      project_id: effectiveProjectId.value,
      ...(effectiveModuleId.value ? { module_id: Number(effectiveModuleId.value) } : {}),
      thread_id: threadId.value,
      confirmed_data: confirmedData,
    })

    // 时序图返回 diagrams 数组
    if (isSequence.value && res.diagrams && res.diagrams.length > 0) {
      const firstDiagram = res.diagrams[0]
      pumlCode.value = firstDiagram.puml_code || ''
      imageUrl.value = firstDiagram.image_url || ''
      selectedRecord.value = null // 清空选中记录，刷新后重新获取
    } else {
      pumlCode.value = res.puml_code || ''
      imageUrl.value = res.image_url || ''
    }

    status.value = 'editing'
    ElMessage.success('图表生成成功')
    // 刷新列表但锁定编辑态
    await loadSavedData('editing')
  } catch (error) {
    status.value = 'confirming'
    const detail = error.response?.data?.detail
    if (detail) {
      ElMessage.error(detail)
    } else {
      ElMessage.error('生成失败')
    }
    console.error('生成失败:', error)
  } finally {
    loading.value = false
  }
}

// 同步代码渲染
const handleSyncCodeRender = async () => {
  if (!pumlCode.value) {
    ElMessage.warning('请先输入 PlantUML 代码')
    return
  }

  loading.value = true

  try {
    const res = await syncCode({
      project_id: effectiveProjectId.value,
      ...(effectiveModuleId.value ? { module_id: Number(effectiveModuleId.value) } : {}),
      model_type: effectiveModelType.value,
      puml_code: pumlCode.value,
      usecase_name: isSequence.value ? selectedRecord.value?.usecase_name : undefined,
    })

    if (isSequence.value && res.diagrams && res.diagrams.length > 0) {
      const firstDiagram = res.diagrams[0]
      pumlCode.value = firstDiagram.puml_code || pumlCode.value
      imageUrl.value = firstDiagram.image_url || imageUrl.value
    } else {
      imageUrl.value = res.image_url || imageUrl.value
    }

    ElMessage.success('同步渲染成功')
    // 留在编辑页面，刷新列表并锁定编辑态
    await loadSavedData('editing')
  } catch (error) {
    console.error('同步失败:', error)
  } finally {
    loading.value = false
  }
}

// 重新生成单个时序图（基于已有用例数据重新执行 LLM 提取）
const handleRegenerateSequence = async () => {
  if (!selectedRecord.value?.usecase_name) {
    ElMessage.warning('请先选择一个时序图')
    return
  }

  loading.value = true
  try {
    // 调用 extract 接口，只传入单个用例，会重新执行完整的大模型提取流程
    const res = await extractEntities('sequence', {
      project_id: effectiveProjectId.value,
      ...(effectiveModuleId.value ? { module_id: Number(effectiveModuleId.value) } : {}),
      selected_usecases: [selectedRecord.value.usecase_name],
    })

    if (res.diagrams && res.diagrams.length > 0) {
      const diagram = res.diagrams[0]
      pumlCode.value = diagram.puml_code || ''
      imageUrl.value = diagram.image_url || ''
      ElMessage.success('重新生成成功')
      // 留在编辑页面，刷新列表并锁定编辑态
      await loadSavedData('editing')
    } else {
      ElMessage.warning('重新生成未返回有效数据')
    }
  } catch (error) {
    const detail = error.response?.data?.detail
    ElMessage.error(detail || '重新生成失败')
    console.error('重新生成失败:', error)
  } finally {
    loading.value = false
  }
}

// 下载图片
const handleDownloadImage = async () => {
  if (!imageUrl.value) {
    ElMessage.warning('暂无图片可下载')
    return
  }
  // 优先使用从父组件传入的 displayName（项目名-模块名），否则降级到项目名
  const name = props.displayName || projectName.value || effectiveProjectId.value
  let filename
  if (isSequence.value) {
    const usecaseName = selectedRecord.value?.usecase_name || '未命名'
    filename = `${name}-${usecaseName}-时序图.png`
  } else if (effectiveModelType.value === 'usecase') {
    filename = `${name}-用例图.png`
  } else if (effectiveModelType.value === 'class') {
    filename = `${name}-类图.png`
  } else {
    filename = `${effectiveModelType.value}_${effectiveProjectId.value}.png`
  }
  await downloadImageUrl(imageUrl.value, filename)
}

// 返回查看模式
const handleBackToView = () => {
  selectedRecord.value = null
  loadSavedData()
}

// 格式化时间
const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ==================== Monaco 配置 ====================
const monacoOptions = {
  language: 'plaintext',
  theme: 'vs-dark',
  readOnly: false,
  minimap: { enabled: false },
  lineNumbers: 'on',
  scrollBeyondLastLine: false,
  automaticLayout: true,
  fontSize: 14,
  padding: { top: 16, bottom: 16 },
  wordWrap: 'on',
}
</script>

<template>
  <div class="uml-workspace" v-loading="loading || moduleLoading" element-loading-text="处理中...">
    <!-- ========== 模块模式：顶部编辑区域（可由父组件通过 showModuleHeader=false 隐藏） ========== -->
    <div v-if="isModuleMode && showModuleHeader" class="module-header">
      <!-- 模块信息展示（默认状态） -->
      <div v-if="!moduleEditing" class="module-info">
        <div class="module-info-left">
          <h2 class="module-title">{{ moduleForm.name || '未命名模块' }}</h2>
          <p v-if="moduleForm.description" class="module-desc">{{ moduleForm.description }}</p>
          <div class="module-requirements-block">
            <span class="requirements-label">核心需求</span>
            <div class="requirements-text" style="text-align: left">{{ moduleForm.core_requirements || '暂无核心需求' }}</div>
          </div>
          <div class="module-info-actions">
            <el-button type="primary" plain size="small" :icon="Edit" @click="handleEditModule">
              编辑信息
            </el-button>
          </div>
        </div>
      </div>

      <!-- 模块信息编辑（编辑状态） -->
      <div v-else class="module-edit">
        <el-form :model="moduleForm" label-width="90px" class="module-form">
          <el-form-item label="模块名称" required>
            <el-input v-model="moduleForm.name" placeholder="请输入模块名称" maxlength="100" show-word-limit />
          </el-form-item>
          <el-form-item label="模块描述">
            <el-input
              v-model="moduleForm.description"
              type="textarea"
              :rows="2"
              placeholder="请简要描述模块职责（可选）"
              maxlength="500"
            />
          </el-form-item>
          <el-form-item label="核心需求" required>
            <el-input
              v-model="moduleForm.core_requirements"
              type="textarea"
              :rows="4"
              placeholder="请详细描述该模块的核心需求，这是 AI 生成 UML 的关键依据"
            />
          </el-form-item>
        </el-form>
        <div class="module-edit-actions">
          <el-button @click="handleCancelModuleEdit">取消</el-button>
          <el-button type="primary" @click="handleSaveModule">
            保存更改
          </el-button>
        </div>
      </div>
    </div>

    <!-- ========== 模式1: 空闲（无数据） ========== -->
    <div v-if="status === 'idle'" class="idle-container">
      <div class="idle-content">
        <el-empty :description="isSequence ? '请先选择要生成时序图的用例' : '还没有提取任何 UML 数据'">
          <el-button
            v-if="isSequence"
            type="primary"
            size="large"
            @click="handleOpenSequenceSelector"
          >
            📋 选择用例生成时序图
          </el-button>
          <el-button
            v-else
            type="primary"
            size="large"
            @click="handleExtract"
          >
            🤖 一键提取
          </el-button>
        </el-empty>
      </div>
    </div>

    <!-- ========== 模式2: 查看模式（只读展示） ========== -->
    <div v-else-if="isViewing && savedRecords.length > 0" class="view-container">
      <div class="view-header">
        <el-button-group v-if="!batchDeleteMode">
          <el-button @click="isSequence ? handleOpenSequenceSelector() : handleExtract()">
            {{ isSequence ? '📋 新增时序图' : '🔄 重新提取' }}
          </el-button>
          <el-button v-if="isSequence" type="warning" @click="toggleBatchDeleteMode">
            🗑️ 批量删除
          </el-button>
          <el-button v-if="!isSequence" type="primary" @click="handleEdit">
            ✏️ 编辑图表
          </el-button>
          <el-button v-if="!isSequence" type="danger" @click="handleDeleteCurrent">
            删除
          </el-button>
        </el-button-group>
        <div v-else class="batch-actions">
          <el-checkbox
            v-model="selectAll"
            :indeterminate="isIndeterminate"
            @change="handleSelectAll"
            class="batch-select-all"
          >
            全选 ({{ batchSelectedIds.length }}/{{ savedRecords.length }})
          </el-checkbox>
          <el-button type="danger" :loading="deleteLoading" @click="handleBatchDelete">
            🗑️ 删除选中 ({{ batchSelectedIds.length }})
          </el-button>
          <el-button @click="toggleBatchDeleteMode">取消</el-button>
        </div>
      </div>

      <!-- 时序图卡片列表 -->
      <div v-if="isSequence" class="sequence-cards">
        <el-card
          v-for="record in savedRecords"
          :key="record.id"
          class="sequence-card"
          :class="{ 'is-selected': batchSelectedIds.includes(record.usecase_name) }"
          shadow="hover"
          @click="batchDeleteMode ? toggleRecordSelection(record.usecase_name) : handleSelectSequence(record)"
        >
          <div class="card-image">
            <el-image
              v-if="record.image_url"
              :src="record.image_url"
              fit="contain"
              class="preview-image"
            />
            <div v-else class="no-image">暂无图片</div>
          </div>
          <div class="card-info">
            <h4>{{ record.usecase_name || '未命名' }}</h4>
            <p class="card-meta">
              <span>创建: {{ formatDate(record.created_at) }}</span>
              <span v-if="record.updated_at">修改: {{ formatDate(record.updated_at) }}</span>
            </p>
          </div>
        </el-card>
      </div>

      <!-- 用例图/类图单图展示 -->
      <div v-else class="single-image-view">
        <el-image
          v-if="savedRecords[0]?.image_url"
          :src="savedRecords[0].image_url"
          :preview-src-list="[savedRecords[0].image_url]"
          fit="contain"
          class="main-image"
        />
        <div class="image-meta">
          <span>创建: {{ formatDate(savedRecords[0]?.created_at) }}</span>
          <span v-if="savedRecords[0]?.updated_at">修改: {{ formatDate(savedRecords[0]?.updated_at) }}</span>
        </div>
      </div>
    </div>

    <!-- ========== 模式3: 选择时序图用例 ========== -->
    <div v-else-if="status === 'selecting'" class="select-container">
      <div class="select-header">
        <h3>选择要生成时序图的用例</h3>
        <p class="tips">请从以下用例中选择（可多选），将基于用例图中的参与者关系生成时序图</p>
      </div>

      <div class="select-content">
        <el-checkbox-group v-model="selectedUsecases" class="usecase-checkboxes">
          <el-checkbox
            v-for="usecase in sequenceOptions"
            :key="usecase"
            :value="usecase"
            border
            size="large"
            :class="['usecase-checkbox', { 'is-generated': generatedUsecaseNames.has(usecase) }]"
          >
            {{ usecase }}
            <el-tag v-if="generatedUsecaseNames.has(usecase)" type="success" size="small" effect="plain" class="generated-tag">
              已生成
            </el-tag>
          </el-checkbox>
        </el-checkbox-group>
      </div>

      <div class="select-footer">
        <el-button size="large" @click="handleCancelSelection">
          取消
        </el-button>
        <el-button
          type="primary"
          size="large"
          :disabled="selectedUsecases.length === 0"
          @click="handleExtract"
        >
          确认并生成 ({{ selectedUsecases.length }} 个用例)
        </el-button>
      </div>
    </div>

    <!-- ========== 模式4: 待确认 ========== -->
    <div v-else-if="status === 'confirming'" class="confirm-container">
      <div class="confirm-header">
        <h3>请确认大模型提取的实体</h3>
        <p class="tips">可直接在表格中编辑，也可以添加或删除条目</p>
      </div>

      <!-- 类图：单表格展示 -->
      <div v-if="effectiveModelType === 'class'" class="confirm-tables">
        <el-card class="confirm-table-card" style="height: 100%">
          <template #header>
            <div class="card-header">
              <span>类列表</span>
            </div>
          </template>
          <div class="confirm-table-scroll">
            <el-table :data="classesTableData" max-height="350" border stripe>
              <el-table-column label="类名" prop="name">
                <template #default="{ row, $index }">
                  <el-input v-model="row.name" placeholder="请输入类名" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="70" align="center">
                <template #default="{ $index }">
                  <el-button type="danger" :icon="Delete" circle @click="removeClass($index)" />
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="add-row">
            <el-button type="primary" plain @click="addClass">+ 添加类</el-button>
          </div>
          <el-empty v-if="classesTableData.length === 0" description="暂无类，请添加至少一个类" />
        </el-card>
      </div>

      <!-- 用例图：关联关系表 -->
      <div v-else class="confirm-tables">
        <el-card class="confirm-table-card" style="height: 100%">
          <template #header>
            <div class="card-header">
              <span>参与者-用例关联表</span>
            </div>
          </template>
          <div class="confirm-table-scroll">
            <el-table :data="useCaseMapping" max-height="500" border stripe>
              <el-table-column label="参与者" width="200">
                <template #default="{ row }">
                  <el-input v-model="row.actor" placeholder="请输入参与者名称" />
                </template>
              </el-table-column>
              <el-table-column label="关联用例">
                <template #default="{ row, $index: rowIdx }">
                  <!-- 用例列表 + 新增输入框 -->
                  <div class="usecase-list">
                    <div
                      v-for="(usecase, ucIdx) in row.usecases"
                      :key="ucIdx"
                      class="usecase-item"
                    >
                      <el-input
                        v-model="row.usecases[ucIdx]"
                        size="small"
                        placeholder="用例名称"
                        style="flex: 1"
                      />
                      <el-button
                        type="danger"
                        :icon="Delete"
                        size="small"
                        circle
                        @click="removeUsecaseFromMapping(rowIdx, ucIdx)"
                      />
                    </div>
                    <!-- 新增用例输入框 -->
                    <div class="usecase-item add-usecase-item">
                      <el-input
                        v-model="newUsecases[rowIdx]"
                        size="small"
                        placeholder="输入用例名称后点击添加"
                        @keyup.enter="addUsecaseToMapping(rowIdx)"
                        style="flex: 1"
                      />
                      <el-button
                        type="primary"
                        size="small"
                        @click="addUsecaseToMapping(rowIdx)"
                      >
                        添加
                      </el-button>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80" align="center">
                <template #default="{ $index }">
                  <el-button type="danger" :icon="Delete" circle @click="useCaseMapping.splice($index, 1)" />
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="add-row">
            <el-button
              type="primary"
              plain
              style="width: 100%; border-style: dashed"
              @click="addMapping"
            >
              + 添加参与者
            </el-button>
          </div>
          <el-empty v-if="useCaseMapping.length === 0" description="暂无参与者，请添加至少一个参与者" />
        </el-card>
      </div>

      <div class="confirm-footer">
        <el-button size="large" @click="handleCancelConfirm">
          取消
        </el-button>
        <el-button size="large" @click="handleExtract">
          重新提取
        </el-button>
        <el-button
          type="primary"
          size="large"
          :loading="loading"
          @click="handleGenerate"
        >
          ✅ 确认无误，生成图表
        </el-button>
      </div>
    </div>

    <!-- ========== 模式5: 编辑模式（PlantUML 编辑器） ========== -->
    <div v-else-if="isEditing" class="editor-container">
      <div class="editor-header">
        <div class="header-left">
          <el-button @click="handleBackToView" v-if="isSequence">
            ← 返回列表
          </el-button>
          <span v-if="selectedRecord?.usecase_name" class="current-usecase">
            当前用例: {{ selectedRecord.usecase_name }}
          </span>
        </div>
        <el-button-group>
          <el-button v-if="isSequence" @click="handleRegenerateSequence">🔄 重新生成</el-button>
          <el-button @click="handleSyncCodeRender">🔄 同步代码渲染</el-button>
          <el-button @click="handleDownloadImage">📥 下载图片</el-button>
        </el-button-group>
      </div>

      <div class="workspace-content">
        <div class="workspace-left">
          <VueMonacoEditor
            v-model:value="pumlCode"
            :options="monacoOptions"
            height="100%"
            class="monaco-editor"
          />
        </div>

        <div class="workspace-right">
          <el-image
            v-if="imageUrl"
            :src="imageUrl"
            :preview-src-list="[imageUrl]"
            fit="contain"
            class="uml-image"
            :preview-teleported="true"
          />
          <div v-else class="image-placeholder">
            <el-empty description="暂无生成的 UML 图表，请点击「同步代码渲染」按钮">
              <el-button type="primary" @click="handleSyncCodeRender">
                🔄 同步代码渲染
              </el-button>
            </el-empty>
          </div>
        </div>
      </div>

      <div class="editor-footer">
        <el-button @click="handleBackToView">返回查看模式</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.uml-workspace {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 180px);
  min-height: 400px;
  position: relative;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.uml-workspace::-webkit-scrollbar {
  display: none;
}

/* ===== 空闲状态 ===== */
.idle-container {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.idle-content {
  text-align: center;
}

/* ===== 查看模式 ===== */
.view-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 10px;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.view-container::-webkit-scrollbar {
  display: none;
}

.view-header {
  display: flex;
  justify-content: center;
  align-items: center;
  margin-bottom: 12px;
}

.view-header h3 {
  margin: 0;
  color: #303133;
}

.batch-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.batch-select-all {
  margin-right: 4px;
}

/* 时序图卡片 */
.sequence-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  grid-auto-rows: auto;
  gap: 12px;
  padding: 4px;
  overflow: visible;
}

.sequence-card {
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.sequence-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.1);
}

.sequence-card.is-selected {
  border: 2px solid #f56c6c;
  box-shadow: 0 0 0 3px rgba(245, 108, 108, 0.15);
}

.card-image {
  height: 150px;
  width: 100%;
  background-color: #fafbfc;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.card-image .el-image {
  width: 100%;
  height: 100%;
  display: block;
}

.no-image {
  color: #909399;
  font-size: 14px;
}

.card-info {
  padding: 10px 14px;
  background-color: #fff;
}

.card-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-meta {
  margin: 4px 0 0 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: #909399;
}

/* 单图展示 */
.single-image-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  border-radius: 8px;
}

.main-image {
  flex: 1;
  min-height: 0;
}

.image-meta {
  padding: 10px 14px;
  display: flex;
  gap: 20px;
  font-size: 12px;
  color: #909399;
  border-top: 1px solid #ebeef5;
}

/* ===== 选择用例状态 ===== */
.select-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 10px;
  gap: 10px;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.select-container::-webkit-scrollbar {
  display: none;
}

.select-header {
  text-align: center;
}

.select-header h3 {
  margin: 0 0 8px;
  color: #303133;
}

.select-header .tips {
  margin: 0;
  color: #909399;
  font-size: 13px;
}

.select-content {
  flex: 1;
  overflow: auto;
  padding: 12px;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.select-content::-webkit-scrollbar {
  display: none;
}

.usecase-checkboxes {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.usecase-checkbox {
  margin: 0 !important;
}

.usecase-checkbox.is-generated {
  background-color: #f0f9eb;
  border-color: #c2e7b0;
}

.generated-tag {
  margin-left: 6px;
}

.select-footer {
  display: flex;
  justify-content: center;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
}

/* ===== 待确认状态 ===== */
.confirm-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 10px;
  gap: 10px;
  overflow: auto;
  min-height: 350px;
}
.confirm-container::-webkit-scrollbar {
  display: none;
}

.confirm-header {
  text-align: center;
}

.confirm-header h3 {
  margin: 0 0 8px;
  color: #303133;
}

.confirm-header .tips {
  margin: 0;
  color: #909399;
  font-size: 13px;
}

.confirm-tables {
  flex: 1;
  min-height: 300px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.confirm-table-card {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.confirm-table-card :deep(.el-card__header) {
  flex-shrink: 0;
  padding: 12px 16px;
  border-bottom: 1px solid #e4e7ed;
}

.confirm-table-card :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}

/* 表格滚动容器 */
.confirm-table-scroll {
  flex: 1;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.confirm-table-scroll::-webkit-scrollbar {
  display: none;
}

/* 隐藏表格内部滚动条 */
.confirm-table-card :deep(.el-table__body-wrapper) {
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.confirm-table-card :deep(.el-table__body-wrapper::-webkit-scrollbar) {
  display: none;
}

.add-row {
  flex-shrink: 0;
  padding: 10px 0;
  text-align: center;
  border-top: 1px solid #ebeef5;
  background: #fff;
}

.usecase-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.usecase-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.add-usecase-item {
  padding-top: 4px;
  border-top: 1px dashed #dcdfe6;
}

.confirm-footer {
  display: flex;
  justify-content: center;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

/* ===== 编辑模式 ===== */
.editor-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.editor-container::-webkit-scrollbar {
  display: none;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.current-usecase {
  font-weight: 600;
  color: #409eff;
}

.workspace-content {
  flex: 1;
  display: flex;
  gap: 10px;
  padding: 10px;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.workspace-content::-webkit-scrollbar {
  display: none;
}

.workspace-left {
  flex: 0 0 40%;
  min-width: 0;
  border-radius: 8px;
  overflow: hidden;
}

.monaco-editor {
  height: 100%;
  border-radius: 8px;
}

.workspace-right {
  flex: 0 0 55%;
  min-width: 0;
  background: #fff;
  border-radius: 8px;
  overflow: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.workspace-right::-webkit-scrollbar {
  display: none;
}

.uml-image {
  width: 100%;
  height: 100%;
}

.image-placeholder {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-image:
    linear-gradient(90deg, #f0f0f0 1px, transparent 1px),
    linear-gradient(#f0f0f0 1px, transparent 1px);
  background-size: 20px 20px;
}

.editor-footer {
  padding: 10px 14px;
  background: #fff;
  border-top: 1px solid #ebeef5;
  display: flex;
  justify-content: center;
}

/* ===== 模块编辑头部 ===== */
.module-header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 20px 24px;
  flex-shrink: 0;
  letter-spacing: 0.5px;
}

.module-info {
  max-width: 800px;
}

.module-info-left {
  flex: 1;
  min-width: 0;
}

.module-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  letter-spacing: 1px;
  line-height: 1.3;
}

.module-desc {
  margin: 0 0 16px;
  font-size: 14px;
  color: #909399;
  line-height: 1.6;
}

.module-requirements-block {
  margin-bottom: 16px;
}

.requirements-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #909399;
  margin-bottom: 8px;
  letter-spacing: 0.5px;
}

.requirements-text {
  background: #f8f9fa;
  border: 1px solid #e8eaed;
  border-radius: 8px;
  padding: 16px 20px;
  font-size: 14px;
  color: #303133;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
  text-align: left;
}

.module-info-actions {
  text-align: center;
}

.module-edit {
  max-width: 700px;
}

.module-form {
  margin-bottom: 16px;
}

.module-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
