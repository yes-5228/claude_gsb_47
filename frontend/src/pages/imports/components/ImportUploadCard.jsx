import { useRef, useState } from 'react'
import { SectionCard } from '../../../components/common/Card.jsx'
import { Field, Input, Select } from '../../../components/common/FormField.jsx'
import { Alert } from '../../../components/common/Feedback.jsx'

const PERIODS = [
  { value: 'hourly', label: '小时均值' },
  { value: 'daily', label: '日均值' }
]

const DATA_SOURCES = [
  { value: 'import', label: '历史导入' },
  { value: 'device', label: '设备上传' },
  { value: 'manual', label: '手工录入' }
]

const STRATEGIES = [
  { value: 'skip', label: '跳过重复数据' },
  { value: 'merge', label: '合并覆盖(以导入值为准)' }
]

const ACCEPT = '.xlsx,.csv,.txt'

export default function ImportUploadCard({ settings, onChange, file, onFileChange, onDownloadTemplate, busy }) {
  const inputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)

  const selectedName = file?.name || ''
  const invalidExt = selectedName && !/\.(xlsx|csv|txt)$/i.test(selectedName)

  const pickFile = (next) => {
    if (next) onFileChange(next)
  }

  return (
    <SectionCard
      title="第一步 · 选择文件与导入选项"
      hint="支持 .xlsx / .csv 表格, 单次最多 5000 行; 上传后先校验预览, 确认无误才会入库"
    >
      <div className="stack">
        <div className="form-grid">
          <Field label="数据周期" required hint="整份表格按同一周期判定限值">
            <Select
              value={settings.period}
              onChange={(e) => onChange('period', e.target.value)}
              options={PERIODS}
            />
          </Field>
          <Field label="重复数据策略" required hint="库中已存在相同“站点+因子+时刻”时的处理方式">
            <Select
              value={settings.strategy}
              onChange={(e) => onChange('strategy', e.target.value)}
              options={STRATEGIES}
            />
          </Field>
          <Field label="默认数据来源" hint="表格“数据来源”列为空时使用该值">
            <Select
              value={settings.dataSource}
              onChange={(e) => onChange('dataSource', e.target.value)}
              options={DATA_SOURCES}
            />
          </Field>
          <Field label="默认录入人" hint="表格“录入人”列为空时使用该值">
            <Input
              value={settings.recorder}
              onChange={(e) => onChange('recorder', e.target.value)}
              placeholder="如: 张三"
              maxLength={64}
            />
          </Field>
        </div>

        <div
          className={`drop-zone${dragOver ? ' drag-over' : ''}${invalidExt ? ' is-invalid' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            pickFile(e.dataTransfer.files?.[0])
          }}
          role="button"
          tabIndex={0}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            style={{ display: 'none' }}
            disabled={busy}
            onChange={(e) => pickFile(e.target.files?.[0])}
          />
          <div className="drop-icon">📄</div>
          <div className="strong">{selectedName ? selectedName : '点击选择或拖拽表格到此处'}</div>
          <div className="small muted">
            {selectedName
              ? `大小 ${(file.size / 1024).toFixed(1)} KB · 点击可重新选择`
              : '必填列: 监测点编码 / 监测因子 / 监测时间 / 数值'}
          </div>
          {invalidExt ? <Alert tone="error">仅支持 .xlsx 或 .csv 格式文件</Alert> : null}
        </div>

        <div className="inline">
          <button type="button" className="btn btn-ghost btn-sm" onClick={onDownloadTemplate}>
            ⬇ 下载标准导入模板(.xlsx)
          </button>
          <span className="small muted">模板含示例行、下拉选项与填写说明, 导入前请删除示例数据</span>
        </div>
      </div>
    </SectionCard>
  )
}
