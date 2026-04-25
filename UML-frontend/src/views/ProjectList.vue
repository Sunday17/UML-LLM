<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { projectApi } from '@/api/projects'

const router = useRouter()
const projects = ref([])
const loading = ref(false)

// 加载项目列表
const loadProjects = async () => {
  loading.value = true
  try {
    projects.value = await projectApi.list()
  } catch (error) {
    ElMessage.error(error.message || '加载项目列表失败')
  } finally {
    loading.value = false
  }
}

// 打开新建项目对话框
const showCreateDialog = ref(false)
const createForm = ref({
  name: '',
  requirement_text: '',
})
const createLoading = ref(false)

const openCreateDialog = () => {
  createForm.value = {
    name: '',
    requirement_text: '',
  }
  showCreateDialog.value = true
}

// 创建项目
const handleCreate = async () => {
  if (!createForm.value.name.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  if (!createForm.value.requirement_text.trim()) {
    ElMessage.warning('请输入需求文本')
    return
  }

  createLoading.value = true
  try {
    const project = await projectApi.create(createForm.value)
    ElMessage.success('项目创建成功')
    showCreateDialog.value = false
    router.push(`/projects/${project.id}`)
  } catch (error) {
    ElMessage.error(error.message || '创建项目失败')
  } finally {
    createLoading.value = false
  }
}

// 删除项目
const handleDelete = async (project) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除项目「${project.name}」吗？此操作不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    await projectApi.delete(project.id)
    ElMessage.success('删除成功')
    loadProjects()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.message || '删除失败')
    }
  }
}

// 进入项目详情
const goToProject = (project) => {
  router.push(`/projects/${project.id}`)
}

onMounted(() => {
  loadProjects()
})
</script>

<template>
  <div class="project-list">
    <div class="header">
      <h2>我的项目</h2>
      <el-button type="primary" @click="openCreateDialog">
        新建项目
      </el-button>
    </div>

    <div v-loading="loading" class="projects-container">
      <div v-if="projects.length === 0 && !loading" class="empty-state">
        <el-empty description="暂无项目，点击" :image-size="120">
          <el-button type="primary" @click="openCreateDialog">新建项目</el-button>
        </el-empty>
      </div>

      <div v-else class="projects-grid">
        <el-card
          v-for="project in projects"
          :key="project.id"
          class="project-card"
          shadow="hover"
          @click="goToProject(project)"
        >
          <div class="project-content">
            <h3 class="project-name">{{ project.name }}</h3>
            <p class="project-desc">{{ project.requirement_text }}</p>
          </div>
          <div class="project-footer">
            <span class="project-date">{{ new Date(project.created_at).toLocaleDateString() }}</span>
            <el-button
              type="danger"
              size="small"
              text
              @click.stop="handleDelete(project)"
            >
              删除
            </el-button>
          </div>
        </el-card>
      </div>
    </div>

    <!-- 新建项目对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      title="新建项目"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="项目名称">
          <el-input
            v-model="createForm.name"
            placeholder="例如：图书管理系统"
            maxlength="100"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="需求文本">
          <el-input
            v-model="createForm.requirement_text"
            type="textarea"
            :rows="6"
            placeholder="请描述系统的功能需求..."
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="createLoading" @click="handleCreate">
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.project-list {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
}

.projects-container {
  min-height: 400px;
}

.empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 60px 0;
}

.projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
}

.project-card {
  cursor: pointer;
  transition: all 0.3s;
}

.project-card:hover {
  transform: translateY(-4px);
}

.project-content {
  margin-bottom: 12px;
}

.project-name {
  margin: 0 0 8px 0;
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.project-desc {
  margin: 0;
  font-size: 14px;
  color: #909399;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.6;
}

.project-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

.project-date {
  font-size: 12px;
  color: #c0c4cc;
}
</style>
