import { useMemo, useState } from 'react'
import { SectionCard } from '../../../components/common/Card.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { formatNumber } from '../../../utils/format.js'

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'valid', label: '可导入' },
  { key: 'duplicate', label: '重复行' },
  { key: 'invalid', label: '校验不通过' }
]

const STATUS_META = {
  valid: { tag: 'success', text: '可导入' },
  duplicate: { tag: 'warning', text: '重复' },
  invalid: { tag: 'danger', text: '不通过' }
}

function RowStatusTag({ status }) {
  const meta = STATUS_META[status] || STATUS_META.invalid
  return <Tag tone={meta.tag}>{meta.text}</Tag>
}

export default function ImportPreviewTable({ rows, periodLabel, strategy }) {
  const [filter, setFilter] = useState('all')
  const visible = useMemo(
    () => (filter === 'all' ? rows : rows.filter((row) => row.status === filter)),
    [rows, filter]
  )
  const counts = useMemo(
    () => ({
      all: rows.length,
      valid: rows.filter((r) => r.status === 'valid').length,
      duplicate: rows.filter((r) => r.status === 'duplicate').length,
      invalid: rows.filter((r) => r.status === 'invalid').length
    }),
    [rows]
  )

  return (
    <SectionCard
      title="第二步 · 逐行校验预览"
      hint={`按“监测点 + 因子 + ${periodLabel} + 监测时间”判定重复; 未通过的行不会入库`}
      actions={
        <div className="btn-group">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`btn btn-sm${filter === item.key ? ' btn-primary' : ''}`}
              onClick={() => setFilter(item.key)}
            >
              {item.label} {counts[item.key]}
            </button>
          ))}
        </div>
      }
      footer={`当前显示 ${visible.length} 行 · 重复行将按“${
        strategy === 'merge' ? '合并覆盖' : '跳过'
      }”策略处理`}
    >
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 56 }}>行号</th>
              <th>监测点</th>
              <th>监测因子</th>
              <th>监测时间</th>
              <th className="text-right">数值</th>
              <th>限值判定</th>
              <th>重复结论</th>
              <th>校验结论</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => {
              const evaluation = row.evaluation
              return (
                <tr key={row.row_number} className={row.status === 'invalid' ? 'row-invalid' : ''}>
                  <td className="mono muted">{row.row_number}</td>
                  <td>
                    {row.field_errors?.station_code ? (
                      <span className="danger-text">{row.station_code || '(空)'}</span>
                    ) : (
                      <>
                        <span className="mono">{row.station_code}</span>
                        {row.station_name ? <span className="muted small"> · {row.station_name}</span> : null}
                      </>
                    )}
                    {row.field_errors?.station_code ? (
                      <div className="small danger-text">{row.field_errors.station_code}</div>
                    ) : null}
                  </td>
                  <td>
                    {row.pollutant_label || '(空)'}
                    {row.field_errors?.pollutant ? (
                      <div className="small danger-text">{row.field_errors.pollutant}</div>
                    ) : null}
                  </td>
                  <td className="nowrap">
                    {(row.measured_at || '').replace('T', ' ').slice(0, 16) || (
                      <span className="danger-text">{row.field_errors?.measured_at || '(空)'}</span>
                    )}
                  </td>
                  <td className="text-right nowrap">
                    {row.value === null || row.value === undefined ? (
                      <span className="danger-text">{row.field_errors?.value || '(空)'}</span>
                    ) : (
                      <>
                        {formatNumber(row.value)}
                        <span className="muted small"> {row.unit}</span>
                      </>
                    )}
                  </td>
                  <td>
                    {evaluation ? (
                      evaluation.exceeded ? (
                        <Tag tone="danger">
                          超标 {formatNumber(evaluation.ratio, 2)} 倍
                          {evaluation.level === 'light'
                            ? '(轻度)'
                            : evaluation.level === 'moderate'
                              ? '(中度)'
                              : evaluation.level === 'severe'
                                ? '(重度)'
                                : ''}
                        </Tag>
                      ) : evaluation.applicable ? (
                        <Tag tone="success">达标</Tag>
                      ) : (
                        <Tag tone="neutral">仅记录</Tag>
                      )
                    ) : (
                      <span className="muted small">—</span>
                    )}
                  </td>
                  <td>
                    {row.status === 'duplicate' ? (
                      <>
                        <Tag tone="warning">库中重复</Tag>
                        <div className="small muted">
                          原值 {formatNumber(row.existing?.value)} · id={row.existing?.id}
                        </div>
                      </>
                    ) : row.status === 'invalid' && /文件第/.test(row.message || '') ? (
                      <Tag tone="danger">文件内重复</Tag>
                    ) : (
                      <span className="muted small">—</span>
                    )}
                  </td>
                  <td>
                    <RowStatusTag status={row.status} />
                    {row.message ? <div className="small muted">{row.message}</div> : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </SectionCard>
  )
}
