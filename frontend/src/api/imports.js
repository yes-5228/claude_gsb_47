import http from './client.js'

/** 上传表格做逐行校验预览 (multipart/form-data). */
export function previewImport({ file, period, strategy, dataSource, recorder }) {
  const form = new FormData()
  form.append('file', file)
  form.append('period', period)
  form.append('strategy', strategy)
  form.append('data_source', dataSource)
  if (recorder) form.append('recorder', recorder)
  return http.post('/measurements/import-preview', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000
  })
}

/** 确认预览结果后入库, 重复数据按 skip/merge 策略处理. */
export function commitImport({ rows, period, strategy, dataSource, recorder }) {
  return http.post('/measurements/import-commit', {
    rows,
    period,
    strategy,
    data_source: dataSource,
    recorder: recorder || null
  }, { timeout: 120000 })
}

export const importTemplateUrl = (period = 'hourly') =>
  `/measurements/import-template?period=${period}`
