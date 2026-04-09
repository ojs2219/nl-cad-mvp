import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client.js'
import Preview3D from '../components/Preview3D.jsx'

export default function History() {
  const [records, setRecords] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    api
      .get('/api/history/')
      .then((res) => setRecords(res.data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const handleDelete = async (id) => {
    if (!window.confirm('이 기록을 삭제하시겠습니까?')) return
    try {
      await api.delete(`/api/history/${id}`)
      setRecords((prev) => prev.filter((r) => r.id !== id))
      if (selected?.id === id) setSelected(null)
    } catch {
      alert('삭제에 실패했습니다.')
    }
  }

  const handleReuse = (record) => {
    navigate('/', { state: { input: record.input_text } })
  }

  const handleDownload = (record) => {
    if (!record.stl_url) return
    const a = document.createElement('a')
    a.href = record.stl_url
    a.download = `cad_${record.id}.stl`
    a.click()
  }

  const formatDate = (dt) =>
    new Date(dt).toLocaleString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

  const parsedParams = (() => {
    try {
      return selected?.params_json ? JSON.parse(selected.params_json) : null
    } catch {
      return null
    }
  })()

  if (loading) return <div className="page-container"><div className="page-loading">로딩 중...</div></div>

  return (
    <div className="page-container">
      <h2 style={{ marginBottom: '1.25rem' }}>생성 히스토리</h2>

      {records.length === 0 ? (
        <div className="empty-state">
          <p>생성 기록이 없습니다.</p>
          <button className="btn-primary" style={{ width: 'auto', marginTop: '1rem' }} onClick={() => navigate('/')}>
            첫 번째 형상 만들기
          </button>
        </div>
      ) : (
        <div className="history-layout">
          {/* List */}
          <div className="history-list">
            {records.map((r) => (
              <div
                key={r.id}
                className={`history-item${selected?.id === r.id ? ' selected' : ''}${r.status === 'failed' ? ' failed' : ''}`}
                onClick={() => setSelected(r)}
              >
                <div className="history-item-text">{r.input_text}</div>
                <div className="history-item-meta">
                  <span className={`status-badge status-${r.status}`}>
                    {r.status === 'success' ? '성공' : r.status === 'failed' ? '실패' : '처리 중'}
                  </span>
                  <span>{formatDate(r.created_at)}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Detail */}
          {selected && (
            <div className="panel">
              <h3 style={{ marginBottom: '1rem' }}>상세 정보</h3>
              <p style={{ marginBottom: '0.4rem' }}>
                <strong>입력:</strong> {selected.input_text}
              </p>
              <p style={{ marginBottom: '0.75rem' }}>
                <strong>상태:</strong>{' '}
                <span className={`status-badge status-${selected.status}`}>
                  {selected.status === 'success' ? '성공' : selected.status === 'failed' ? '실패' : '처리 중'}
                </span>
              </p>

              {selected.error_message && (
                <div className="error-box">{selected.error_message}</div>
              )}

              {selected.stl_url && (
                <Preview3D key={selected.stl_url} stlUrl={selected.stl_url} />
              )}

              <div className="history-actions">
                <button className="btn-primary" style={{ width: 'auto' }} onClick={() => handleReuse(selected)}>
                  다시 사용
                </button>
                {selected.stl_url && (
                  <button className="btn-secondary" onClick={() => handleDownload(selected)}>
                    STL 다운로드
                  </button>
                )}
                <button className="btn-danger" onClick={() => handleDelete(selected.id)}>
                  삭제
                </button>
              </div>

              {parsedParams && (
                <div style={{ marginTop: '1rem' }}>
                  <p className="label-muted">파라미터</p>
                  <pre className="params-pre">{JSON.stringify(parsedParams, null, 2)}</pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
