import request, { requestBlob } from '../utils/request'

export const getProjects = () => {
  return request.get('/projects')
}

export const getProject = async (id) => {
  const allProjects = await getProjects()
  const project = allProjects.find(p => p.id === parseInt(id))
  if (project) return project
  throw new Error('项目不存在')
}

export const createProject = (data) => {
  return request.post('/projects', data)
}

export const deleteProject = (id) => {
  return request.delete(`/projects/${id}`)
}

export const updateProject = (id, data) => {
  return request.patch(`/projects/${id}`, data)
}

export const batchDeleteProjects = (ids) => {
  return request.post('/projects/batch-delete', { ids })
}

export const extractTextFromFile = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/utils/extract-text', formData)
}

export const uploadFileToServer = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/utils/upload-file', formData)
}

export const splitComplexProject = (projectId) => {
  return request.post(`/projects/${projectId}/split`)
}

export const getDownloadUrl = (projectId) => {
  return request.get(`/projects/${projectId}/download-url`)
}

export const getProjectModules = (projectId) => {
  return request.get(`/projects/${projectId}/modules`)
}

export const createProjectModule = (projectId, data) => {
  return request.post(`/projects/${projectId}/modules`, data)
}

export const updateProjectModule = (moduleId, data) => {
  return request.put(`/projects/modules/${moduleId}`, data)
}

export const deleteProjectModule = (moduleId) => {
  return request.delete(`/projects/modules/${moduleId}`)
}

export const batchDeleteModules = (projectId, moduleIds) => {
  return request.post(`/projects/${projectId}/modules/batch-delete`, { ids: moduleIds })
}

export const exportModulesUml = (projectId, moduleIds) => {
  return requestBlob.post(`/projects/${projectId}/export-modules`, { module_ids: moduleIds })
}
