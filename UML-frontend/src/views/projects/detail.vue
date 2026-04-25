<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import JSZip from 'jszip'
import { saveAs } from 'file-saver'
import { getProject, updateProject, getProjectModules, updateProjectModule } from '@/api/projects'
import { getAllUmlAssets } from '@/api/uml'
import UmlWorkspace from '@/components/UmlWorkspace.vue'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const project = ref(null)

// 当前模块信息（module 模式）
const currentModule = ref(null)
const isModuleMode = computed(() => !!route.query.module_id)

// 模块编辑相关
const moduleEditing = ref(false)
const moduleForm = ref({
  name: '',
  description: '',
  requirement_text: '',
})
const moduleSaving = ref(false)

// 批量导出
const exportLoading = ref(false)
const exportDialogVisible = ref(false)
const exportItems = ref([])
const selectedExportItems = ref([])

// 全选状态
const exportSelectAll = computed({
  get: () => exportItems.value.length > 0 && selectedExportItems.value.length === exportItems.value.length,
  set: (val) => {
    if (val) {
      selectedExportItems.value = [...exportItems.value]
    } else {
      selectedExportItems.value = []
    }
  },
})

// 当前上下文 ID（从 route params 和 query params 双向兼容）
const effectiveProjectId = computed(() => route.params.id || route.query.project_id)
const effectiveModuleId = computed(() => route.query.module_id || null)

// 用于前端文件名和图表标题的显示名称（项目名-模块名）
const displayName = computed(() => {
  const proj = project.value?.name || ''
  const mod = currentModule.value?.module_name || ''
  if (proj && mod) return `${proj}-${mod}`
  return proj
})

// 获取项目信息
const fetchProject = async () => {
  loading.value = true
  try {
    project.value = await getProject(effectiveProjectId.value)
    // 初始化表单
    moduleForm.value = {
      name: project.value.name || '',
      description: project.value.description || '',
      requirement_text: project.value.requirement_text || '',
    }
  } catch (error) {
    console.error('获取项目详情失败:', error)
    ElMessage.error('获取项目详情失败')
  } finally {
    loading.value = false
  }
}

// 获取模块信息
const fetchModule = async () => {
  try {
    const modules = await getProjectModules(effectiveProjectId.value)
    const module = modules.find(m => String(m.id) === String(effectiveModuleId.value))
    if (module) {
      currentModule.value = module
      moduleForm.value = {
        name: module.module_name || '',
        description: module.description || '',
        requirement_text: module.core_requirements || '',
      }
    }
  } catch (error) {
    console.error('获取模块信息失败:', error)
  }
}

// 进入编辑模式
const handleEdit = () => {
  moduleEditing.value = true
}

// 取消编辑
const handleCancelEdit = () => {
  moduleEditing.value = false
  // 恢复原始值
  if (isModuleMode.value && currentModule.value) {
    moduleForm.value = {
      name: currentModule.value.module_name || '',
      description: currentModule.value.description || '',
      requirement_text: currentModule.value.core_requirements || '',
    }
  } else {
    moduleForm.value = {
      name: project.value?.name || '',
      description: project.value?.description || '',
      requirement_text: project.value?.requirement_text || '',
    }
  }
}

// 保存更改
const handleSave = async () => {
  if (!moduleForm.value.name.trim()) {
    ElMessage.warning('请输入名称')
    return
  }
  if (!moduleForm.value.requirement_text.trim()) {
    ElMessage.warning('请输入需求内容')
    return
  }
  moduleSaving.value = true
  try {
    if (isModuleMode.value) {
      await updateProjectModule(effectiveModuleId.value, {
        module_name: moduleForm.value.name.trim(),
        description: moduleForm.value.description.trim(),
        core_requirements: moduleForm.value.requirement_text.trim(),
      })
      // 更新本地缓存
      if (currentModule.value) {
        currentModule.value.module_name = moduleForm.value.name.trim()
        currentModule.value.description = moduleForm.value.description.trim()
        currentModule.value.core_requirements = moduleForm.value.requirement_text.trim()
      }
      ElMessage.success('模块信息已更新')
    } else {
      await updateProject(effectiveProjectId.value, {
        name: moduleForm.value.name.trim(),
        description: moduleForm.value.description.trim(),
        requirement_text: moduleForm.value.requirement_text.trim(),
      })
      // 更新本地缓存
      if (project.value) {
        project.value.name = moduleForm.value.name.trim()
        project.value.description = moduleForm.value.description.trim()
        project.value.requirement_text = moduleForm.value.requirement_text.trim()
      }
      ElMessage.success('项目信息已更新')
    }
    moduleEditing.value = false
  } catch (error) {
    console.error('保存失败:', error)
    ElMessage.error('保存失败')
  } finally {
    moduleSaving.value = false
  }
}

// 打开导出弹窗
const handleOpenExport = async () => {
  exportDialogVisible.value = true
  selectedExportItems.value = []
  try {
    const res = await getAllUmlAssets(effectiveProjectId.value, effectiveModuleId.value || undefined)
    const items = []
    const displayName = isModuleMode.value
      ? (currentModule.value?.module_name || project.value?.name || '项目')
      : (project.value?.name || '项目')

    if (res.usecase?.image_url && res.usecase?.is_confirmed) {
      items.push({ type: 'usecase', label: '用例图', filename: `${displayName}-用例图.png`, url: res.usecase.image_url })
    }
    if (res.class?.image_url && res.class?.is_confirmed) {
      items.push({ type: 'class', label: '类图', filename: `${displayName}-类图.png`, url: res.class.image_url })
    }
    if (res.sequence && res.sequence.length > 0) {
      res.sequence.forEach(seq => {
        if (seq.image_url) {
          items.push({
            type: 'sequence',
            label: `时序图 - ${seq.usecase_name}`,
            filename: `${displayName}-${seq.usecase_name}-时序图.png`,
            url: seq.image_url,
          })
        }
      })
    }

    exportItems.value = items
  } catch (error) {
    console.error('获取资产列表失败:', error)
    ElMessage.error('获取资产列表失败')
  }
}

// 批量打包下载
const handleBatchExport = async () => {
  if (selectedExportItems.value.length === 0) {
    ElMessage.warning('请至少选择一张图表')
    return
  }

  exportLoading.value = true
  const zip = new JSZip()

  try {
    const fetchImage = (url) => fetch(url).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.blob()
    })

    const fetches = selectedExportItems.value.map(item => {
      return fetchImage(item.url).then(blob => {
        // 时序图放在 "时序图" 子文件夹中，其他图直接放在根目录
        if (item.type === 'sequence') {
          zip.folder('时序图').file(item.filename, blob)
        } else {
          zip.file(item.filename, blob)
        }
      }).catch(err => {
        console.warn(`[batch export] 图片获取失败 (${item.label}):`, err.message)
        return null
      })
    })

    const results = await Promise.all(fetches)
    if (results.every(r => r === null)) {
      ElMessage.error('所有图片获取失败，请检查网络后重试')
      return
    }

    const zipBlob = await zip.generateAsync({ type: 'blob' })
    const zipName = `${isModuleMode.value ? (currentModule.value?.module_name || '模块') : (project.value?.name || '项目')}_UML图.zip`
    saveAs(zipBlob, zipName)
    ElMessage.success(`导出成功，共打包 ${selectedExportItems.value.length} 张图表`)
    exportDialogVisible.value = false
  } catch (error) {
    console.error('批量导出失败:', error)
    ElMessage.error('批量导出失败，请重试')
  } finally {
    exportLoading.value = false
  }
}

const goBack = () => {
  if (isModuleMode.value) {
    router.push(`/project/${effectiveProjectId.value}/modules`)
  } else {
    router.push('/projects')
  }
}

onMounted(async () => {
  await fetchProject()
  if (isModuleMode.value) {
    await fetchModule()
  }
})
</script>

<template>
  <div class="project-detail" v-loading="loading">
    <el-container>
      <el-header class="detail-header">
        <div class="header-content">
          <el-button
            :icon="ArrowLeft"
            circle
            @click="goBack"
            class="back-btn"
          />
          <h1 class="project-name">
            {{ isModuleMode ? (currentModule?.module_name || '模块工作区') : (project?.name || '加载中...') }}
          </h1>
        </div>
        <el-button
          v-if="project || currentModule"
          type="success"
          @click="handleOpenExport"
          class="export-btn"
        >
          📦 一键导出
        </el-button>
      </el-header>

      <el-main class="detail-main">
        <el-tabs>
          <el-tab-pane label="需求详情">
            <el-card class="requirement-card">
              <!-- 编辑状态 -->
              <div v-if="moduleEditing" class="requirement-edit">
                <el-form label-width="90px" class="edit-form">
                  <el-form-item label="名称" required>
                    <el-input
                      v-model="moduleForm.name"
                      :placeholder="isModuleMode ? '请输入模块名称' : '请输入项目名称'"
                      maxlength="100"
                      show-word-limit
                    />
                  </el-form-item>
                  <el-form-item v-if="!isModuleMode" label="项目描述">
                    <el-input
                      v-model="moduleForm.description"
                      type="textarea"
                      :rows="2"
                      placeholder="请简要描述项目（可选）"
                      maxlength="200"
                      show-word-limit
                    />
                  </el-form-item>
                  <el-form-item v-if="isModuleMode" label="模块描述">
                    <el-input
                      v-model="moduleForm.description"
                      type="textarea"
                      :rows="2"
                      placeholder="请简要描述模块职责（可选）"
                      maxlength="500"
                    />
                  </el-form-item>
                  <el-form-item :label="isModuleMode ? '核心需求' : '需求文本'" required>
                    <el-input
                      v-model="moduleForm.requirement_text"
                      type="textarea"
                      :rows="15"
                      :placeholder="isModuleMode ? '请详细描述该模块的核心需求，这是 AI 生成 UML 的关键依据' : '请输入项目需求文本'"
                    />
                  </el-form-item>
                </el-form>
                <div class="edit-actions">
                  <el-button @click="handleCancelEdit">取消</el-button>
                  <el-button type="primary" :loading="moduleSaving" @click="handleSave">
                    保存更改
                  </el-button>
                </div>
              </div>

              <!-- 只读状态 -->
              <div v-else class="requirement-view">
                <div class="view-header">
                  <div class="view-name">
                    <h2>{{ isModuleMode ? (currentModule?.module_name || project?.name) : project?.name }}</h2>
                    <p v-if="isModuleMode && currentModule?.description" class="view-desc">
                      {{ currentModule.description }}
                    </p>
                  </div>
                </div>
                <div class="view-divider" />
                <div class="view-label">
                  {{ isModuleMode ? '核心需求' : '需求文本' }}
                </div>
                <pre class="requirement-text">{{ (isModuleMode ? currentModule?.core_requirements : project?.requirement_text) || '' }}</pre>
                <div class="requirement-actions">
                  <el-button type="primary" plain size="small" @click="handleEdit">
                    ✏️ 编辑信息
                  </el-button>
                </div>
              </div>
            </el-card>
          </el-tab-pane>

          <el-tab-pane label="用例图">
            <UmlWorkspace
              v-if="project"
              model-type="usecase"
              :project-id="effectiveProjectId"
              :module-id="effectiveModuleId || undefined"
              :show-module-header="false"
              :display-name="displayName"
            />
          </el-tab-pane>

          <el-tab-pane label="类图">
            <UmlWorkspace
              v-if="project"
              model-type="class"
              :project-id="effectiveProjectId"
              :module-id="effectiveModuleId || undefined"
              :show-module-header="false"
              :display-name="displayName"
            />
          </el-tab-pane>

          <el-tab-pane label="时序图">
            <UmlWorkspace
              v-if="project"
              model-type="sequence"
              :project-id="effectiveProjectId"
              :module-id="effectiveModuleId || undefined"
              :show-module-header="false"
              :display-name="displayName"
            />
          </el-tab-pane>
        </el-tabs>
      </el-main>
    </el-container>

    <!-- 批量导出弹窗 -->
    <el-dialog
      v-model="exportDialogVisible"
      title="导出 UML 图"
      width="500px"
      :close-on-click-modal="false"
    >
      <template v-if="exportItems.length === 0">
        <el-empty description="暂无可导出的图表资产" />
      </template>
      <template v-else>
        <el-checkbox-group v-model="selectedExportItems" class="export-checkboxes">
          <el-checkbox
            v-for="item in exportItems"
            :key="item.type + item.filename"
            :value="item"
            border
            class="export-checkbox"
          >
            {{ item.label }}
          </el-checkbox>
        </el-checkbox-group>
      </template>
      <template #footer>
        <div class="export-footer">
          <div class="export-footer-left">
            <el-button @click="exportDialogVisible = false">取消</el-button>
            <el-button
              type="primary"
              plain
              @click="exportSelectAll = true"
              :disabled="selectedExportItems.length === exportItems.length"
            >
              全选
            </el-button>
          </div>
          <el-button
            type="success"
            :loading="exportLoading"
            :disabled="selectedExportItems.length === 0"
            @click="handleBatchExport"
          >
            打包下载 ({{ selectedExportItems.length }})
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.project-detail {
  min-height: 100vh;
  background: #f5f7fa;
}

.detail-header {
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
}

.header-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.back-btn {
  flex-shrink: 0;
}

.project-name {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.detail-main {
  padding: 24px 32px;
}

.requirement-card {
  max-width: 1200px;
}

/* ===== 需求详情 - 只读视图 ===== */
.view-header {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  gap: 20px;
}

.view-name h2 {
  margin: 0 0 6px;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.view-desc {
  margin: 0;
  font-size: 14px;
  color: #606266;
  line-height: 1.5;
}

.view-divider {
  height: 1px;
  background: #ebeef5;
  margin: 16px 0;
}

.view-label {
  font-size: 13px;
  font-weight: 500;
  color: #909399;
  margin-bottom: 8px;
}

.requirement-text {
  margin: 0 0 16px;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.8;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-word;
  text-align: left;
}

.requirement-actions {
  text-align: center;
}

/* ===== 需求详情 - 编辑视图 ===== */
.edit-form {
  max-width: 700px;
}

.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
}

/* ===== 导出弹窗 ===== */
.export-btn {
  flex-shrink: 0;
}

.export-checkboxes {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.export-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.export-footer-left {
  display: flex;
  gap: 8px;
}

.export-checkbox {
  margin: 0 !important;
}
</style>
