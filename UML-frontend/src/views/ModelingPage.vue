<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { projectApi } from '@/api/projects'
import { umlApi } from '@/api/uml'
import UseCaseEditor from '@/components/uml/UseCaseEditor.vue'
import ClassEditor from '@/components/uml/ClassEditor.vue'
import SequenceEditor from '@/components/uml/SequenceEditor.vue'

const route = useRoute()
const router = useRouter()

const projectId = computed(() => route.params.id)
const project = ref(null)
const loading = ref(false)

// 当前选中的图类型
const activeTab = ref('usecase')
const tabs = [
  { key: 'usecase', label: '用例图', description: '描述系统功能与参与者' },
  { key: 'class', label: '类图', description: '描述类与类之间的关系' },
  { key: 'sequence', label: '时序图', description: '描述对象间的交互顺序' },
]

// 加载项目信息
const loadProject = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    project.value = await projectApi.getById(projectId.value)
  } catch (error) {
    ElMessage.error(error.message || '加载项目信息失败')
    router.push('/')
  } finally {
    loading.value = false
  }
}

// 返回项目列表
const goBack = () => {
  router.push('/')
}

onMounted(() => {
  loadProject()
})

// 切换 Tab 时重新加载数据
watch(activeTab, (newTab) => {
  console.log('切换到:', newTab)
})
</script>

<template>
  <div v-loading="loading" class="modeling-page">
    <!-- 顶部导航 -->
    <div class="page-header">
      <div class="header-left">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <div class="project-info" v-if="project">
          <h1>{{ project.name }}</h1>
          <p class="requirement-text">{{ project.requirement_text }}</p>
        </div>
      </div>
    </div>

    <!-- 图类型切换 -->
    <div class="diagram-tabs">
      <el-tabs v-model="activeTab" type="border-card" class="modeling-tabs">
        <el-tab-pane
          v-for="tab in tabs"
          :key="tab.key"
          :name="tab.key"
        >
          <template #label>
            <div class="tab-label">
              <span class="tab-icon">
                <svg v-if="tab.key === 'usecase'" width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <ellipse cx="12" cy="8" rx="6" ry="4" stroke="currentColor" stroke-width="2"/>
                  <line x1="4" y1="20" x2="4" y2="12" stroke="currentColor" stroke-width="2"/>
                  <line x1="4" y1="16" x2="10" y2="12" stroke="currentColor" stroke-width="2"/>
                  <line x1="4" y1="20" x2="10" y2="20" stroke="currentColor" stroke-width="2"/>
                </svg>
                <svg v-else-if="tab.key === 'class'" width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <rect x="3" y="4" width="18" height="6" stroke="currentColor" stroke-width="2"/>
                  <rect x="3" y="10" width="18" height="4" stroke="currentColor" stroke-width="2"/>
                  <rect x="3" y="14" width="18" height="6" stroke="currentColor" stroke-width="2"/>
                </svg>
                <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <line x1="6" y1="4" x2="6" y2="20" stroke="currentColor" stroke-width="2"/>
                  <line x1="18" y1="4" x2="18" y2="20" stroke="currentColor" stroke-width="2"/>
                  <line x1="6" y1="8" x2="18" y2="12" stroke="currentColor" stroke-width="2" marker-end="url(#arrow)"/>
                </svg>
              </span>
              <span>{{ tab.label }}</span>
            </div>
          </template>

          <div class="tab-content">
            <!-- 用例图编辑器 -->
            <UseCaseEditor
              v-if="tab.key === 'usecase'"
              :project-id="projectId"
              :requirement-text="project?.requirement_text"
            />

            <!-- 类图编辑器 -->
            <ClassEditor
              v-else-if="tab.key === 'class'"
              :project-id="projectId"
              :requirement-text="project?.requirement_text"
            />

            <!-- 时序图编辑器 -->
            <SequenceEditor
              v-else-if="tab.key === 'sequence'"
              :project-id="projectId"
              :requirement-text="project?.requirement_text"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<style scoped>
.modeling-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
}

.page-header {
  background: white;
  padding: 16px 24px;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.project-info {
  margin-left: 16px;
}

.project-info h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.requirement-text {
  margin: 4px 0 0 0;
  font-size: 14px;
  color: #909399;
  max-width: 600px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.diagram-tabs {
  flex: 1;
  padding: 20px;
  overflow: auto;
}

.modeling-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;
}

:deep(.el-tabs__content) {
  flex: 1;
  overflow: auto;
}

:deep(.el-tab-pane) {
  height: 100%;
}

.tab-label {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}

.tab-icon {
  display: flex;
  align-items: center;
  color: #409eff;
}

.tab-content {
  height: 100%;
  padding: 16px;
  background: white;
  border-radius: 4px;
}
</style>
