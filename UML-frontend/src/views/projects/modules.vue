<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Plus, Edit, Delete, Download } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, ElTooltip } from 'element-plus'
import { getProject } from '@/api/projects'
import { getProjectModules, createProjectModule, updateProjectModule, deleteProjectModule, batchDeleteModules, exportModulesUml } from '@/api/projects'

const route = useRoute()
const router = useRouter()

const projectId = computed(() => route.params.id)

const loading = ref(false)
const project = ref(null)
const modules = ref([])
const selectedModules = ref([])

// 新增/编辑弹窗
const dialogVisible = ref(false)
const dialogTitle = ref('新增模块')
const submitting = ref(false)
const editingModule = ref(null)
const formRef = ref(null)

const form = ref({
  module_name: '',
  description: '',
  core_requirements: '',
})

const rules = {
  module_name: [{ required: true, message: '请输入模块名称', trigger: 'blur' }],
  core_requirements: [{ required: true, message: '请输入核心需求', trigger: 'blur' }],
}

// 加载项目信息
const fetchProject = async () => {
  try {
    project.value = await getProject(projectId.value)
  } catch (error) {
    console.error('获取项目信息失败:', error)
  }
}

// 加载模块列表
const fetchModules = async () => {
  loading.value = true
  try {
    modules.value = await getProjectModules(projectId.value)
  } catch (error) {
    console.error('获取模块列表失败:', error)
  } finally {
    loading.value = false
  }
}

// 返回项目列表
const goBack = () => {
  router.push('/projects')
}

// 进入模块建模工作区
const goToWorkspace = (module) => {
  router.push({
    path: '/modeling',
    query: {
      project_id: projectId.value,
      module_id: module.id,
    },
  })
}

// 打开新增弹窗
const handleOpenCreate = () => {
  editingModule.value = null
  dialogTitle.value = '新增模块'
  form.value = { module_name: '', description: '', core_requirements: '' }
  dialogVisible.value = true
}

// 打开编辑弹窗
const handleOpenEdit = (module, event) => {
  event.stopPropagation()
  editingModule.value = module
  dialogTitle.value = '编辑模块'
  form.value = {
    module_name: module.module_name,
    description: module.description || '',
    core_requirements: module.core_requirements,
  }
  dialogVisible.value = true
}

// 提交表单
const handleSubmit = async () => {
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      if (editingModule.value) {
        await updateProjectModule(editingModule.value.id, {
          module_name: form.value.module_name,
          description: form.value.description,
          core_requirements: form.value.core_requirements,
        })
        ElMessage.success('模块更新成功')
      } else {
        await createProjectModule(projectId.value, {
          module_name: form.value.module_name,
          description: form.value.description,
          core_requirements: form.value.core_requirements,
        })
        ElMessage.success('模块创建成功')
      }
      dialogVisible.value = false
      await fetchModules()
    } catch (error) {
      console.error('保存模块失败:', error)
    } finally {
      submitting.value = false
    }
  })
}

// 删除模块
const handleDelete = async (module, event) => {
  event.stopPropagation()
  try {
    await ElMessageBox.confirm(
      `确定要删除模块「${module.module_name}」吗？该模块下的所有 UML 图表将一并删除。`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await deleteProjectModule(module.id)
    ElMessage.success('删除成功')
    await fetchModules()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除模块失败:', error)
    }
  }
}

// 批量删除模块
const handleBatchDelete = async () => {
  if (selectedModules.value.length === 0) {
    ElMessage.warning('请先选择要删除的模块')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedModules.value.length} 个模块吗？这些模块下的所有 UML 图表将一并删除。`,
      '批量删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    loading.value = true
    const ids = selectedModules.value.map(m => m.id)
    await batchDeleteModules(projectId.value, ids)
    ElMessage.success(`成功删除 ${ids.length} 个模块`)
    selectedModules.value = []
    await fetchModules()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('批量删除模块失败:', error)
    }
  } finally {
    loading.value = false
  }
}

// 批量导出 UML
const handleBatchExport = async () => {
  if (selectedModules.value.length === 0) {
    ElMessage.warning('请先选择要导出的模块')
    return
  }
  try {
    const ids = selectedModules.value.map(m => m.id)
    const res = await exportModulesUml(projectId.value, ids)
    const blob = res.data
    // 从 Content-Disposition 取服务器返回的正确文件名，否则降级用项目名
    const disposition = res.headers['content-disposition'] || ''
    // 支持 RFC 5987 格式: filename*=UTF-8''%E5%93%81%E9%A1%B9%E5%90%8D_UML%E5%9B%BE.zip
    const match = disposition.match(/filename\*=(?:UTF-8''|\*)'?([^;\r\n']+)/i)
    const zipName = match ? decodeURIComponent(match[1]) : `${project.value?.name || 'project_' + projectId.value}_UML图.zip`
    const url = window.URL.createObjectURL(new Blob([blob]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', zipName)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success(`成功导出 ${selectedModules.value.length} 个模块的 UML`)
  } catch (error) {
    console.error('导出失败:', error)
  }
}

// 格式化日期
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

// 复选框切换
const toggleSelection = (module, checked) => {
  if (checked) {
    if (!selectedModules.value.some(m => m.id === module.id)) {
      selectedModules.value.push(module)
    }
  } else {
    selectedModules.value = selectedModules.value.filter(m => m.id !== module.id)
  }
}

const isSelected = (module) => selectedModules.value.some(m => m.id === module.id)

onMounted(() => {
  fetchProject()
  fetchModules()
})
</script>

<template>
  <div class="modules-page" v-loading="loading">
    <!-- 顶部 Header -->
    <header class="modules-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" circle @click="goBack" />
        <h1 class="page-title">{{ project?.name || '模块管理' }}</h1>
      </div>
    </header>

    <!-- 操作区 -->
    <div class="action-bar">
      <div class="action-left">
        <el-button type="primary" :icon="Plus" @click="handleOpenCreate">
          新增模块
        </el-button>
      </div>
      <div class="action-right">
        <el-button
          type="danger"
          :icon="Delete"
          :disabled="selectedModules.length === 0"
          @click="handleBatchDelete"
        >
          批量删除{{ selectedModules.length > 0 ? ` (${selectedModules.length})` : '' }}
        </el-button>
        <el-button
          type="success"
          :icon="Download"
          :disabled="selectedModules.length === 0"
          @click="handleBatchExport"
        >
          打包导出所选 UML{{ selectedModules.length > 0 ? ` (${selectedModules.length})` : '' }}
        </el-button>
      </div>
    </div>

    <!-- 模块卡片网格 -->
    <div class="modules-content" v-if="modules.length > 0">
      <el-row :gutter="20">
        <el-col
          v-for="module in modules"
          :key="module.id"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
        >
          <el-card
            class="module-card"
            shadow="hover"
            @click="goToWorkspace(module)"
          >
            <template #header>
              <div class="card-header">
                <div class="card-header-left">
                  <el-checkbox
                    :model-value="isSelected(module)"
                    @click.stop
                    @change="(val) => toggleSelection(module, val)"
                  />
                  <el-tooltip :content="module.module_name" placement="top" :disabled="module.module_name.length <= 5">
                    <span class="module-name">{{ module.module_name }}</span>
                  </el-tooltip>
                </div>
                <div class="card-actions">
                  <el-button
                    type="primary"
                    :icon="Edit"
                    circle
                    size="small"
                    @click="(e) => handleOpenEdit(module, e)"
                  />
                  <el-button
                    type="danger"
                    :icon="Delete"
                    circle
                    size="small"
                    @click="(e) => handleDelete(module, e)"
                  />
                </div>
              </div>
            </template>

            <div class="card-body">
              <p v-if="module.description" class="module-desc">
                {{ module.description }}
              </p>
              <p v-else class="module-desc empty">暂无描述</p>
            </div>

            <div class="card-footer">
              <span class="create-date">创建于 {{ formatDate(module.created_at) }}</span>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 空状态 -->
    <el-empty
      v-else-if="!loading"
      description="暂无子模块，点击上方按钮新增"
    />

    <!-- 新增/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="100px"
      >
        <el-form-item label="模块名称" prop="module_name">
          <el-input
            v-model="form.module_name"
            placeholder="请输入模块名称，如：用户管理模块"
            maxlength="100"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="模块描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="请简要描述模块职责（可选）"
            maxlength="500"
          />
        </el-form-item>
        <el-form-item label="核心需求" prop="core_requirements">
          <el-input
            v-model="form.core_requirements"
            type="textarea"
            :rows="5"
            placeholder="请详细描述该模块的核心需求，这是 AI 生成 UML 的关键依据"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.modules-page {
  min-height: 100vh;
  background: #f5f7fa;
}

.modules-header {
  background: #fff;
  padding: 16px 32px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.page-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.action-bar {
  padding: 20px 32px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.action-left,
.action-right {
  display: flex;
  gap: 12px;
}

.modules-content {
  padding: 20px 32px;
}

.module-card {
  margin-bottom: 20px;
  cursor: pointer;
  transition: all 0.3s;
}

.module-card:hover {
  transform: translateY(-4px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.card-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.module-name {
  font-weight: 600;
  font-size: 15px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.card-actions {
  display: flex;
  gap: 4px;
}

.card-body {
  min-height: 70px;
}

.module-desc {
  margin: 0 0 12px;
  font-size: 14px;
  color: #606266;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.module-desc.empty {
  color: #c0c4cc;
  font-style: italic;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

.create-date {
  font-size: 12px;
  color: #909399;
}
</style>
