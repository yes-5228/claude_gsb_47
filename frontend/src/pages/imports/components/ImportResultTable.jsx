import { useMemo, useState } from 'react'
import { SectionCard } from '../../../components/common/Card.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { formatNumber } from '../../../utils/format.js'

const TABS = [
  { key: 'all', label: '全部' },
  { key: 'created', label: '新增成功' },
  { key: 'updated', label: '合并更新' },
  { key: 'skipped', label: '已跳过' },
  { key: 'failed', label: '失败' }
]

const STATUS_META = {
  created: { tag: 'success', text: '新增成功' },
  updated: { tag: 'info', text: '合并更新' },
  skipped: { tag: 'neutral', text: '跳过' },
  failed: { tag: 'danger', text: '失败' }
}

export default function ImportResultTable({ result }) {
  const [tab, setTab] = useState('all')
  const details = result?.details || []
  const counts = useMemo(
    () => ({
      all: details.length,
      created: details.filter((r) => r.status === 'created').length,
      updated: details.filter((r) => r.status === 'updated').length,
      skipped: details.filter((r) => r.status === 'skipped').length,
      failed: details.filter((r) => r.status === 'failed').length
    }),
    [details]
  )
  const visible = tab === 'all' ? details : details.filter((row) => row.status === tab)

  return (
    <SectionCard
      title="第三步 · 导入结果逐行明细"
      hint="成功入库与失败原因逐行可查; 失败行不影响其它行导入"
      actions={
        <div className="btn-group">
          {TABS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`btn btn-sm${tab === item.key ? ' btn-primary' : ''}`}
              onClick={() => setTab(item.key)}
            >
              {item.label} {counts[item.key]}
            </button>
          ))}
        </div>
      }
      footer={`当前显示 ${visible.length} 行 · 新增 ${counts.created} / 合并 ${counts.updated} / 跳过 ${counts.skipped} / 失败 ${counts.failed}`}
    >
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 56 }}>行号</th>
              <th>监测点</th>
              <th>因子</th>
              <th>监测时间</th>
              <th className="text-right">数值</th>
              <th>记录</th>
              <th>处理结果</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => {
              const meta = STATUS_META[row.status] || STATUS_META.failed
              return (
                <tr key={row.row_number} className={row.status === 'failed' ? 'row-invalid' : ''}>
                  <td className="mono muted">{row.row_number}</td>
                  <td>
                    <span className="mono">{row.station_code || '(空)'}</span>
                    {row.station_name ? <span className="muted small"> · {row.station_name}</span> : null}
                  </td>
                  <td>{row.pollutant_label || '(空)'}</td>
                  <td className="nowrap">{(row.measured_at || '').replace('T', ' ').slice(0, 16) || '—'}</td>
                  <td className="text-right nowrap">
                    {row.value === null || row.value === undefined ? (
                      '—'
                    ) : (
                      <>
                        {formatNumber(row.value)}
                        <span className="muted small"> {row.unit}</span>
                      </>
                    )}
                  </td>
                  <td className="nowrap">
                    {row.measurement_id ? <span className="mono small">#{row.measurement_id}</span> : '—'}
                    {row.is_exceeded ? (
                      <span style={{ marginLeft: 6 }}>
                        <Tag tone="danger">
                          超标{row.exceedance_level ? ` · ${
                            row.exceedance_level === 'light'
                              ? '轻度'
                              : row.exceedance_level === 'moderate'
                                ? '中度'
                                : '重度'
                          }` : ''}
                        </Tag>
                      </span>
                    ) : null}
                  </td>
                  <td>
                    <Tag tone={meta.tag}>{meta.text}</Tag>
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
