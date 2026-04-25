import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
  timeout: 0,
})

const requestBlob = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
  timeout: 0,
  responseType: 'blob',
})

// 响应拦截器（request）
request.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  }
)

// 响应拦截器（requestBlob —— blob 下载不走统一拦截，直接返回 response）
requestBlob.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || '下载失败'
    ElMessage.error(message)
    return Promise.reject(error)
  }
)

export { request, requestBlob }
export default request