import { useCallback, useMemo, useState } from 'react'
import { commitImport, importTemplateUrl, previewImport } from '../../api/imports.js'
import { downloadFile } from '../../api/client.js'
import { Alert, Loading } from '../../components/common/Feedback.jsx'
import { useToast } from '../../components/common/ToastProvider.jsx'
import { saveBlob } from '../../utils/download.js'
import ImportPreviewTable from './components/ImportPreviewTable.jsx'
import ImportResultTable from './components/ImportResultTable.jsx'
import ImportUploadCard from './components/ImportUploadCard.jsx'

const INITIAL_SETTINGS = {
  period: 'hourly',
  strategy: 'skip',
  dataSource: 'import',
  recorder: ''
}

function SummaryCards({ summary }) {
  if (!summary) return null
  const cards = [
    { label: '总行数', value: summary.total, tone: 'neutral' },
    { label: '可导入', value: summary.valid_count ?? 0, tone: 'success' },
    { label: '重复行', value: summary.duplicate_count ?? 0, tone: 'warning' },
    { label: '校验不通过', value: summary.invalid_count ?? 0, tone: 'danger' },
    { label: '本次新值超标', value: summary.exceeded_count ?? 0, tone: 'info' }
  ]
  return (
    <div className="stat-grid">
      {cards.map((card) => (
        <div key={card.label} className="stat-card">
          <div className="stat-label">{card.label}</div>
          <div className={`stat-value text-${card.tone === 'danger' ? 'danger' : card.tone === 'success' ? 'success' : ''}`}>
            {card.value}
            <small>行</small>
          </div>
        </div>
      ))}
    </div>
  )
}

function ResultSummaryBanner({ result }) {
  const s = result.summary
  const tone = s.failed_count > 0 ? 'warning' : 'success'
  return (
    <Alert tone={tone}>
      导入完成: 共 {s.total} 行 —— 新增 {s.created_count} 行, 合并更新 {s.updated_count} 行,
      重复跳过 {s.skipped_count} 行, 失败 {s.failed_count} 行;
      其中 {result.exceedances_created} 行超标已自动生成待标注记录。
    </Alert>
  )
}

export default function ImportsPage() {
  const toast = useToast()
  const [settings, setSettings] = useState(INITIAL_SETTINGS)
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)

  const changeSetting = useCallback((key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }))
    // 选项变化后历史预览失效, 需要重新上传校验
    setPreview(null)
    setResult(null)
  }, [])

  const handleFile = useCallback((next) => {
    setFile(next)
    setPreview(null)
    setResult(null)
    setError(null)
  }, [])

  const runPreview = async () => {
    if (!file) {
      toast.error('请先选择需要导入的表格文件')
      return
    }
    if (!/\.(xlsx|csv|txt)$/i.test(file.name)) {
      toast.error('仅支持 .xlsx 或 .csv 格式文件')
      return
    }
    setBusy('preview')
    setError(null)
    try {
      const payload = await previewImport({ file, ...settings })
      setPreview(payload)
      setResult(null)
      if (payload.summary.invalid_count > 0) {
        toast.warning(`校验完成: ${payload.summary.invalid_count} 行不通过, ${payload.summary.duplicate_count} 行重复`)
      } else if (payload.summary.duplicate_count > 0) {
        toast.warning(`校验完成: ${payload.summary.duplicate_count} 行重复, 将按所选策略处理`)
      } else {
        toast.success(`校验完成: ${payload.summary.valid_count} 行均可导入`)
      }
    } catch (err) {
      setError(err)
      toast.error(err.message)
    } finally {
      setBusy(null)
    }
  }

  const runCommit = async () => {
    if (!preview) return
    setBusy('commit')
    setError(null)
    try {
      const payload = await commitImport({
        rows: preview.rows.map((row) => ({
          row_number: row.row_number,
          raw: row.raw
        })),
        ...settings
      })
      setResult(payload)
      if (payload.summary.failed_count > 0) {
        toast.warning(`导入结束: ${payload.summary.failed_count} 行失败, 请查看逐行明细`)
      } else {
        toast.success('导入完成, 全部行处理成功')
      }
    } catch (err) {
      setError(err)
      toast.error(err.message)
    } finally {
      setBusy(null)
    }
  }

  const reset = () => {
    setFile(null)
    setPreview(null)
    setResult(null)
    setError(null)
  }

  const downloadTemplate = useCallback(async () => {
    try {
      const blob = await downloadFile(importTemplateUrl(settings.period))
      saveBlob(blob, `历史数据导入模板_${settings.period}.xlsx`)
    } catch (err) {
      toast.error(err.message)
    }
  }, [settings.period, toast])

  const importable = preview?.summary?.valid_count ?? 0
  const duplicate = preview?.summary?.duplicate_count ?? 0
  const invalid = preview?.summary?.invalid_count ?? 0
  const strategyLabel = settings.strategy === 'merge' ? '合并覆盖' : '跳过'
  const commitHint = useMemo(() => {
    if (!preview) return null
    const parts = [`${importable} 行直接新增`]
    if (duplicate > 0) parts.push(`${duplicate} 行重复将${strategyLabel}`)
    if (invalid > 0) parts.push(`${invalid} 行不通过将被放弃`)
    return parts.join(', ')
  }, [preview, importable, duplicate, invalid, strategyLabel])

  return (
    <div className="stack">
      <ImportUploadCard
        settings={settings}
        onChange={changeSetting}
        file={file}
        onFileChange={handleFile}
        onDownloadTemplate={downloadTemplate}
        busy={busy !== null}
      />

      {error ? <Alert tone="error">{error.message}</Alert> : null}

      <div className="card">
        <div className="card-body inline">
          <button
            type="button"
            className="btn btn-primary"
            onClick={runPreview}
            disabled={busy !== null || !file}
          >
            {busy === 'preview' ? '校验中...' : '上传并校验预览'}
          </button>
          <button
            type="button"
            className="btn"
            onClick={runCommit}
            disabled={busy !== null || !preview || (importable + duplicate) === 0}
          >
            {busy === 'commit' ? '导入中...' : `确认导入(${strategyLabel})`}
          </button>
          <button type="button" className="btn btn-ghost" onClick={reset} disabled={busy !== null}>
            清空重来
          </button>
          {commitHint ? <span className="small muted">→ {commitHint}</span> : null}
        </div>
      </div>

      {busy === 'preview' ? <Loading text="正在解析表格并逐行校验, 请稍候..." /> : null}
      {busy === 'commit' ? <Loading text="正在批量入库并重新判定超标, 请稍候..." /> : null}

      {preview && busy !== 'preview' ? (
        <>
          <SummaryCards summary={preview.summary} />
          <ImportPreviewTable
            rows={preview.rows}
            periodLabel={preview.period_label}
            strategy={settings.strategy}
          />
        </>
      ) : null}

      {result ? (
        <>
          <ResultSummaryBanner result={result} />
          <ImportResultTable result={result} />
        </>
      ) : null}
    </div>
  )
}
