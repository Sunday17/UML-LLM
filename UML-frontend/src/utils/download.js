import { ElMessage } from 'element-plus'

/**
 * 通过 fetch 下载图片到本地，避免浏览器直接打开图片页面
 * @param {string} url - 图片 URL
 * @param {string} filename - 下载文件名（需含扩展名）
 * @returns {Promise<void>}
 */
export async function downloadImageUrl(url, filename) {
  try {
    const res = await fetch(url)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const blob = await res.blob()
    const blobUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = filename
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)
  } catch (err) {
    console.warn('[download] CORS or network error, fallback to open:', err.message)
    ElMessage.warning('图片跨域限制，请在图片上右键另存为')
    window.open(url, '_blank')
  }
}

/**
 * 将 Blob 写入 ZIP（供批量导出使用）
 * @param {JSZip} zip - JSZip 实例
 * @param {string} path - ZIP 内部路径
 * @param {Blob} blob - 图片 Blob
 * @param {string} filename - 下载文件名（不含路径）
 * @returns {Promise<void>}
 */
export async function blobToZip(zip, path, blob) {
  return new Promise((resolve, reject) => {
    zip.file(path, blob)
    resolve()
  })
}
