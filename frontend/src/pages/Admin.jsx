import { useState, useEffect } from 'react'
import api from '../api/client.js'

export default function Admin() {
  const [tab, setTab] = useState('users')
  const [users, setUsers] = useState([])
  const [generations, setGenerations] = useState([])
  const [prompt, setPrompt] = useState(null)
  const [promptContent, setPromptContent] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    loadTab(tab)
  }, [tab])

  const loadTab = async (t) => {
    setLoading(true)
    try {
      if (t === 'users') {
        const res = await api.get('/api/admin/users')
        setUsers(res.data)
      } else if (t === 'prompt') {
        const res = await api.get('/api/admin/prompt')
        setPrompt(res.data)
        setPromptContent(res.data.content)
      } else if (t === 'generations') {
        const res = await api.get('/api/admin/generations')
        setGenerations(res.data)
      }
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const handleApprove = async (userId, approve) => {
    try {
      await api.put(`/api/admin/users/${userId}/${approve ? 'approve' : 'revoke'}`)
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, is_approved: approve } : u)))
    } catch {
      alert('처리에 실패했습니다.')
    }
  }

  const handleSavePrompt = async () => {
    try {
      const res = await api.put('/api/admin/prompt', { content: promptContent })
      setPrompt(res.data)
      alert('시스템 프롬프트가 저장되었습니다.')
    } catch {
      alert('저장에 실패했습니다.')
    }
  }

  const formatDate = (dt) =>
    new Date(dt).toLocaleString('ko-KR', { year: '2-digit', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

  return (
    <div className="page-container">
      <h2 style={{ marginBottom: '1.25rem' }}>관리자 패널</h2>

      <div className="tab-bar">
        <button className={`tab${tab === 'users' ? ' active' : ''}`} onClick={() => setTab('users')}>
          사용자 관리
        </button>
        <button className={`tab${tab === 'prompt' ? ' active' : ''}`} onClick={() => setTab('prompt')}>
          시스템 프롬프트
        </button>
        <button className={`tab${tab === 'generations' ? ' active' : ''}`} onClick={() => setTab('generations')}>
          생성 기록
        </button>
      </div>

      {loading && <div className="page-loading">로딩 중...</div>}

      {/* Users tab */}
      {!loading && tab === 'users' && (
        <div className="table-wrapper">
          <table className="admin-table">
            <thead>
              <tr>
                <th>이메일</th>
                <th>가입일</th>
                <th>상태</th>
                <th>역할</th>
                <th>작업</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td>{formatDate(u.created_at)}</td>
                  <td>
                    <span className={`status-badge ${u.is_approved ? 'status-success' : 'status-pending'}`}>
                      {u.is_approved ? '승인됨' : '대기 중'}
                    </span>
                  </td>
                  <td>{u.is_admin ? <strong>관리자</strong> : '사용자'}</td>
                  <td>
                    {!u.is_admin && (
                      u.is_approved ? (
                        <button className="btn-small btn-danger" onClick={() => handleApprove(u.id, false)}>
                          취소
                        </button>
                      ) : (
                        <button className="btn-small btn-primary" onClick={() => handleApprove(u.id, true)}>
                          승인
                        </button>
                      )
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {users.length === 0 && <div className="empty-state" style={{ borderRadius: 0 }}>사용자가 없습니다.</div>}
        </div>
      )}

      {/* Prompt tab */}
      {!loading && tab === 'prompt' && prompt && (
        <div className="panel">
          <p className="label-muted" style={{ marginBottom: '0.75rem' }}>
            마지막 수정: {formatDate(prompt.updated_at)}
          </p>
          <p className="label-muted" style={{ marginBottom: '0.75rem' }}>
            AI가 사용자 입력을 해석할 때 사용하는 기본 프롬프트입니다. 일반 사용자는 수정할 수 없습니다.
          </p>
          <textarea
            value={promptContent}
            onChange={(e) => setPromptContent(e.target.value)}
            rows={16}
            style={{ fontFamily: 'monospace', fontSize: '0.85rem', marginBottom: '0.75rem' }}
          />
          <button className="btn-primary" style={{ width: 'auto' }} onClick={handleSavePrompt}>
            저장
          </button>
        </div>
      )}

      {/* Generations tab */}
      {!loading && tab === 'generations' && (
        <div className="table-wrapper">
          <table className="admin-table">
            <thead>
              <tr>
                <th>#</th>
                <th>사용자</th>
                <th>입력</th>
                <th>상태</th>
                <th>생성일</th>
              </tr>
            </thead>
            <tbody>
              {generations.map((g) => (
                <tr key={g.id}>
                  <td>{g.id}</td>
                  <td>{g.user_email}</td>
                  <td className="cell-truncate">{g.input_text}</td>
                  <td>
                    <span className={`status-badge status-${g.status}`}>
                      {g.status === 'success' ? '성공' : g.status === 'failed' ? '실패' : '처리 중'}
                    </span>
                  </td>
                  <td>{formatDate(g.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {generations.length === 0 && <div className="empty-state" style={{ borderRadius: 0 }}>기록이 없습니다.</div>}
        </div>
      )}
    </div>
  )
}
