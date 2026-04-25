<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, ElLoading, ElTooltip } from 'element-plus'
import { Plus, Delete, UploadFilled, Download, Edit } from '@element-plus/icons-vue'
import { getProjects, createProject, updateProject, deleteProject, batchDeleteProjects, uploadFileToServer, extractTextFromFile, splitComplexProject, getDownloadUrl } from '@/api/projects'

const router = useRouter()

const loading = ref(false)
const projects = ref([])
const selectedProjects = ref([])
const dialogVisible = ref(false)
const editDialogVisible = ref(false)
const submitLoading = ref(false)
const editForm = ref({ id: null, name: '', description: '' })
const editSaving = ref(false)

const form = ref({
  name: '',
  description: '',
  requirement_text: '',
  is_complex: false,
  original_file_url: null,
})

// 上传文件后，后端返回的 /uploads/{uuid}.{ext}，单独记录避免被表单重置覆盖
const lastUploadedFileUrl = ref(null)

// 在 @closed 等无法使用 .value 的地方调用此函数
const resetLastUploadedFileUrl = () => { lastUploadedFileUrl.value = null }

const rules = {
  name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
  requirement_text: [{
    validator: (rule, value, callback) => {
      // 有文件上传时不做必填校验
      if (form.value.original_file_url) {
        callback()
      } else if (!value || !value.trim()) {
        callback(new Error('请输入需求描述'))
      } else {
        callback()
      }
    },
    trigger: 'blur',
  }],
}

const formRef = ref(null)

const fetchProjects = async () => {
  loading.value = true
  try {
    projects.value = await getProjects()
  } catch (error) {
    console.error('获取项目列表失败:', error)
  } finally {
    loading.value = false
  }
}

const handleCreate = async () => {
  await formRef.value.validate(async (valid) => {
    if (!valid) return

    submitLoading.value = true
    try {
      const res = await createProject(form.value)

      // 复杂项目（PDF 或手动标记为复杂），直接进入拆解流程
      if (res.is_complex && res.original_file_url) {
        const splitLoading = ElLoading.service({
          fullscreen: true,
          text: 'AI 正在阅读图文并进行架构拆分，请稍候...',
        })
        try {
          await splitComplexProject(res.id)
          splitLoading.close()
          ElMessage.success('拆解成功，正在跳转至模块管理页面...')
          dialogVisible.value = false
          form.value = { name: '', requirement_text: '', is_complex: false, original_file_url: null }
          resetLastUploadedFileUrl()
          fetchProjects()
          // 跳转到模块管理页面
          router.push(`/project/${res.id}/modules`)
        } catch (err) {
          splitLoading.close()
          ElMessage.error('拆解失败：' + (err.message || '未知错误'))
        }
      } else if (res.is_complex) {
        // 无文件上传的复杂项目（纯文本），询问是否拆解
        try {
          await ElMessageBox.confirm(
            '系统检测到该需求文档内容复杂。直接生成 UML 可能会导致图表过于拥挤混乱，是否启动【AI 智能视觉拆解】？',
            'AI 智能模块拆解建议',
            {
              confirmButtonText: '启动拆解',
              cancelButtonText: '直接使用',
              type: 'info',
            }
          )
          const splitLoading = ElLoading.service({
            fullscreen: true,
            text: 'AI 正在阅读图文并进行架构拆分，请稍候...',
          })
          try {
            await splitComplexProject(res.id)
            splitLoading.close()
            ElMessage.success('拆解成功，正在跳转至模块管理页面...')
            dialogVisible.value = false
            form.value = { name: '', requirement_text: '', is_complex: false, original_file_url: null }
            resetLastUploadedFileUrl()
            fetchProjects()
            router.push(`/project/${res.id}/modules`)
          } catch (err) {
            splitLoading.close()
            ElMessage.error('拆解失败：' + (err.message || '未知错误'))
          }
        } catch (cancelAction) {
          ElMessage.info('已切换为直接使用模式')
          dialogVisible.value = false
          form.value = { name: '', requirement_text: '', is_complex: false, original_file_url: null }
          resetLastUploadedFileUrl()
          fetchProjects()
        }
      } else {
        // 简单项目，直接成功
        ElMessage.success('创建成功')
        dialogVisible.value = false
        form.value = { name: '', requirement_text: '', is_complex: false, original_file_url: null }
        resetLastUploadedFileUrl()
        fetchProjects()
      }
    } catch (error) {
      console.error('创建项目失败:', error)
    } finally {
      submitLoading.value = false
    }
  })
}

const handleDelete = async (project) => {
  try {
    await ElMessageBox.confirm(
      '确定要删除该项目及其所有 UML 图表吗？',
      '删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    await deleteProject(project.id)
    ElMessage.success('删除成功')
    fetchProjects()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除项目失败:', error)
    }
  }
}

// 打开编辑弹窗
const openEditDialog = (project) => {
  editForm.value = { id: project.id, name: project.name, description: project.description || '' }
  editDialogVisible.value = true
}

// 保存编辑
const handleEditSave = async () => {
  if (!editForm.value.name.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  editSaving.value = true
  try {
    await updateProject(editForm.value.id, {
      name: editForm.value.name.trim(),
      description: editForm.value.description.trim(),
    })
    ElMessage.success('更新成功')
    editDialogVisible.value = false
    fetchProjects()
  } catch (error) {
    console.error('更新项目失败:', error)
    ElMessage.error('更新失败')
  } finally {
    editSaving.value = false
  }
}

const handleBatchDelete = async () => {
  if (selectedProjects.value.length === 0) {
    ElMessage.warning('请先选择要删除的项目')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedProjects.value.length} 个项目及其所有 UML 图表吗？`,
      '批量删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    const ids = selectedProjects.value.map(p => p.id)
    await batchDeleteProjects(ids)
    ElMessage.success('批量删除成功')
    selectedProjects.value = []
    fetchProjects()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('批量删除失败:', error)
    }
  }
}

const handleSelectionChange = (selection) => {
  selectedProjects.value = selection
}

const goToDetail = (project) => {
  if (project.is_complex) {
    router.push(`/project/${project.id}/modules`)
  } else {
    router.push(`/project/${project.id}`)
  }
}

const handleDownload = async (project, event) => {
  event.stopPropagation()
  if (!project.original_file_url) {
    ElMessage.warning('该项目没有上传文件')
    return
  }
  try {
    const res = await getDownloadUrl(project.id)
    const link = document.createElement('a')
    link.href = res.download_url
    link.target = '_blank'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  } catch (error) {
    ElMessage.error('下载失败：' + (error.message || '未知错误'))
  }
}

const formatDate = (dateString) => {
  const date = new Date(dateString)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

const handleFileChange = async (uploadFile) => {
  const rawFile = uploadFile.raw
  if (!rawFile) return

  const loadInstance = ElLoading.service({ text: '正在上传文档...' })
  try {
    const ext = rawFile.name.split('.').pop().toLowerCase()

    // TXT：调用 extract-text 接口提取文本并检测复杂度
    if (ext === 'txt') {
      const res = await extractTextFromFile(rawFile)
      loadInstance.close()

      if (res.is_complex) {
        try {
          await ElMessageBox.confirm(
            `检测到文本长度 ${res.text.length} 字，超过 1000 字阈值。建议拆分为多个子模块后逐个生成 UML，是否继续？`,
            '文本较长，建议拆分',
            {
              confirmButtonText: '确定',
              cancelButtonText: '取消',
              type: 'warning',
            }
          )
          // 用户点击确定：回填文本 + 标记复杂
          form.value.requirement_text = res.text
          form.value.original_file_url = res.file_url
          form.value.is_complex = true
          lastUploadedFileUrl.value = res.file_url
        } catch (cancelAction) {
          // 用户点击取消：仅回填文本，不标记复杂
          form.value.requirement_text = res.text
          form.value.original_file_url = res.file_url
          lastUploadedFileUrl.value = res.file_url
          ElMessage.info('已回填文本，您可手动调整后继续')
        }
      } else {
        // 文本长度正常
        form.value.requirement_text = res.text
        form.value.original_file_url = res.file_url
        lastUploadedFileUrl.value = res.file_url
        ElMessage.success('上传成功，文本已回填')
      }
      return
    }

    // PDF：调用 upload 接口，上传后直接进入拆解流程
    if (ext === 'pdf') {
      const res = await uploadFileToServer(rawFile)
      loadInstance.close()
      form.value.original_file_url = res.file_url
      form.value.is_complex = true
      form.value.requirement_text = '【由AI通过文件自动解析】'
      ElMessage.info('文件已上传，将直接进行 AI 智能模块拆解')
      return
    }

    // 其他格式已在 accept 限制，理论上不会走到这里
    loadInstance.close()
    ElMessage.warning('暂不支持该文件格式，仅支持 txt 和 pdf')
  } catch (error) {
    loadInstance.close()
    ElMessage.error('文件处理失败：' + (error.message || '未知错误'))
    console.error('文件处理失败:', error)
  }
}

onMounted(() => {
  fetchProjects()
})
</script>

<template>
  <div class="projects-page">
    <!-- 顶部 Header -->
    <header class="header">
      <h1>UML 智能建模平台</h1>
    </header>

    <!-- 内容区 -->
    <main class="main-content" v-loading="loading">
      <!-- 操作区 -->
      <div class="action-bar">
        <div class="action-left">
          <el-button type="primary" :icon="Plus" @click="dialogVisible = true">
            新建项目
          </el-button>
          <el-button
            type="danger"
            :icon="Delete"
            :disabled="selectedProjects.length === 0"
            @click="handleBatchDelete"
          >
            批量删除{{ selectedProjects.length > 0 ? ` (${selectedProjects.length})` : '' }}
          </el-button>
        </div>
      </div>

      <!-- 卡片网格 -->
      <el-row :gutter="20" v-if="projects.length > 0">
        <el-col
          v-for="project in projects"
          :key="project.id"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
        >
          <el-card class="project-card" shadow="hover" @click="goToDetail(project)">
            <template #header>
              <div class="card-header">
                <div class="card-header-left">
                  <el-checkbox
                    :model-value="selectedProjects.some(p => p.id === project.id)"
                    @click.stop
                    @change="(val) => {
                      if (val) {
                        if (!selectedProjects.some(p => p.id === project.id)) {
                          selectedProjects.push(project)
                        }
                      } else {
                        selectedProjects = selectedProjects.filter(p => p.id !== project.id)
                      }
                    }"
                  />
                  <el-tooltip :content="project.name" placement="top" :disabled="project.name.length <= 5">
                    <span class="project-name">{{ project.name }}</span>
                  </el-tooltip>
                </div>
                <div class="card-actions">
                  <el-button
                    v-if="project.original_file_url"
                    type="primary"
                    :icon="Download"
                    circle
                    size="small"
                    @click.stop="handleDownload(project, $event)"
                  />
                  <el-button
                    type="info"
                    :icon="Edit"
                    circle
                    size="small"
                    @click.stop="openEditDialog(project)"
                  />
                  <el-button
                    type="danger"
                    :icon="Delete"
                    circle
                    size="small"
                    @click.stop="handleDelete(project)"
                  />
                </div>
              </div>
            </template>
            <div class="card-body">
              <p v-if="project.description" class="project-description">{{ project.description }}</p>
            </div>
            <div class="card-footer">
              <span class="create-date">创建于: {{ formatDate(project.created_at) }}</span>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 空状态 -->
      <el-empty
        v-else-if="!loading"
        description="暂无项目，点击上方按钮创建"
      />
    </main>

    <!-- 新建项目弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      title="新建项目"
      width="680px"
      :close-on-click-modal="false"
      @closed="form = { name: '', description: '', requirement_text: '', is_complex: false, original_file_url: null }; resetLastUploadedFileUrl()"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="100px"
      >
        <el-form-item label="项目名称" prop="name">
          <el-input
            v-model="form.name"
            placeholder="请输入项目名称"
            maxlength="100"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="项目描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            placeholder="请简要描述项目（可选）"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="上传文档">
          <el-upload
            drag
            accept=".txt,.pdf"
            :auto-upload="false"
            :show-file-list="false"
            @change="handleFileChange"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">将 txt/pdf 文件拖到此处，或点击上传自动解析</div>
          </el-upload>
        </el-form-item>
        <el-form-item label="需求描述" prop="requirement_text">
          <el-input
            v-model="form.requirement_text"
            type="textarea"
            :rows="6"
            placeholder="请详细描述系统需求..."
            maxlength="2000"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="handleCreate">
          确定
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑项目弹窗 -->
    <el-dialog
      v-model="editDialogVisible"
      title="编辑项目"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form label-width="80px">
        <el-form-item label="项目名称" required>
          <el-input
            v-model="editForm.name"
            placeholder="请输入项目名称"
            maxlength="100"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="项目描述">
          <el-input
            v-model="editForm.description"
            type="textarea"
            :rows="3"
            placeholder="请简要描述项目（可选）"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="handleEditSave">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.projects-page {
  min-height: 100vh;
}

.header {
  background: white;
  padding: 20px 32px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.header h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}

.main-content {
  padding: 24px 32px;
  min-height: calc(100vh - 80px);
}

.action-bar {
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.action-left {
  display: flex;
  gap: 12px;
}

.project-card {
  margin-bottom: 20px;
  cursor: pointer;
  transition: all 0.3s;
}

.project-card:hover {
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

.card-actions {
  display: flex;
  gap: 0px;
}

.project-name {
  font-weight: 600;
  font-size: 16px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.card-body {
  min-height: 70px;
}

.project-description {
  margin: 0 0 5px 0;
  font-size: 14px;
  color: #303133;
  font-weight: 500;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}

.requirement-text {
  margin: 0;
  font-size: 14px;
  color: #606266;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}

.card-footer {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

.create-date {
  font-size: 12px;
  color: #909399;
}

:deep(.el-upload-dragger) {
  padding: 10px 0;
}

.el-upload__text {
  font-size: 12px;
  padding-left: 10px;
  padding-right:10px;
}
</style>
