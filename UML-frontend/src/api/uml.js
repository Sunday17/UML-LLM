import request from '../utils/request'

/**
 * 获取时序图可用的用例选项
 * @param {number} projectId - 项目ID
 * @returns {Promise} - 返回 { project_id, options: [] }
 */
export const getSequenceOptions = (projectId) => {
  return request.get(`/sequence/options/${projectId}`)
}

/**
 * 获取已保存的 UML 数据
 * @param {string} modelType - 模型类型 (usecase | class | sequence)
 * @param {number} projectId - 项目ID
 * @param {number} [moduleId] - 模块ID（模块模式下使用）
 * @returns {Promise} - 返回 { model_type, records: [] }
 */
export const getSavedUML = (modelType, projectId, moduleId) => {
  let url = `/${modelType}/saved?project_id=${projectId}`
  if (moduleId) url += `&module_id=${moduleId}`
  return request.get(url)
}

/**
 * 从需求文本中提取实体
 * @param {string} modelType - 模型类型 (usecase | class | sequence 等)
 * @param {object} payload - 请求数据 { project_id, module_id?, selected_usecases? }
 * @returns {Promise}
 */
export const extractEntities = (modelType, payload) => {
  return request.post(`/${modelType}/extract`, payload)
}

/**
 * 生成 UML 图表
 * @param {string} modelType - 模型类型
 * @param {object} payload - 请求数据 { project_id, module_id?, thread_id, confirmed_data, selected_usecases? }
 * @returns {Promise}
 */
export const generateDiagram = (modelType, payload) => {
  return request.post(`/${modelType}/generate`, payload)
}

/**
 * 同步代码到项目
 * @param {object} payload - 请求数据 { project_id, module_id?, model_type, puml_code, usecase_name? }
 * @returns {Promise}
 */
export const syncCode = (payload) => {
  return request.post('/sync', payload)
}

/**
 * 删除 UML 记录（支持按用例名删除单条时序图）
 * @param {object} payload - 请求数据 { project_id, module_id?, model_type, usecase_name? }
 * @returns {Promise}
 */
export const deleteUmlRecord = (payload) => {
  return request.delete('/record', { data: payload })
}

/**
 * 获取项目下所有 UML 图表资产信息（用于批量导出）
 * @param {number} projectId - 项目ID
 * @param {number} [moduleId] - 模块ID（模块模式下使用，用于隔离不同模块的数据）
 * @returns {Promise} - 返回 { usecase: {}, class: {}, sequence: [] }
 */
export const getAllUmlAssets = (projectId, moduleId) => {
  let url = `/assets/${projectId}`
  if (moduleId) url += `?module_id=${moduleId}`
  return request.get(url)
}
