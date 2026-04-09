import { useState, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import api from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import Preview3D from '../components/Preview3D.jsx'

const EXAMPLES = [
  '100x50x10 박스',
  '지름 20 높이 50 원기둥',
  '반지름 15 구',
  '가로 100 세로 50 두께 5 판에 지름 10 구멍 2개',
  '60x60x20 박스 위에 반지름 10 높이 30 원기둥',
]

export default function Generator() {
  const { user, setUser } = useAuth()
  const location = useLocation()

  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const [customPrompt, setCustomPrompt] = useState(user?.custom_prompt || '')
  const [savingPrompt, setSavingPrompt] = useState(false)

  // Load pre-filled input from History page
  useEffect(() => {
    if (location.state?.input) {
      setInput(location.state.input)
      window.history.replaceState({}, '')
    }
  }, [location.state])

  const handleGenerate = async (text) => {
    const inputText = (text ?? input).trim()
    if (!inputText) return

    setError('')
    setLoading(true)
    setResult(null)
    try {
      const res = await api.post('/api/generate', { input_text: inputText })
      setResult(res.data)
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : '생성 중 오류가 발생했습니다.')
    } finally {
      setLoading(false)
    }
  }

  const handleExampleClick = (ex) => {
    setInput(ex)
    handleGenerate(ex)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && e.ctrlKey) handleGenerate()
  }

  const handleDownload = () => {
    if (!result?.stl_url) return
    const a = document.createElement('a')
    a.href = result.stl_url
    a.download = `cad_${result.id}.stl`
    a.click()
  }

  const handleSavePrompt = async () => {
    setSavingPrompt(true)
    try {
      const res = await api.put('/api/auth/settings', { custom_prompt: customPrompt || null })
      setUser(res.data)
      alert('개인 프롬프트가 저장되었습니다.')
    } catch {
      alert('저장에 실패했습니다.')
    } finally {
      setSavingPrompt(false)
    }
  }

  const parsedParams = (() => {
    try {
      return result?.params_json ? JSON.parse(result.params_json) : null
    } catch {
      return null
    }
  })()

  return (
    <div className="page-container">
      <div className="generator-layout">
        {/* Left panel — input */}
        <div className="panel">
          <h2 className="panel-title">형상 입력</h2>

          <div className="examples-section">
            <p className="label-muted">예시 입력 (클릭하면 바로 생성)</p>
            <div className="examples-grid">
              {EXAMPLES.map((ex, i) => (
                <button key={i} className="example-btn" onClick={() => handleExampleClick(ex)}>
                  {ex}
                </button>
              ))}
            </div>
          </div>

          <div className="form-group" style={{ marginBottom: '0.5rem' }}>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                '원하는 3D 형상을 자연어 또는 수치로 입력하세요.\n\n예: 100x50x10 박스\n예: 지름 30 높이 60 원기둥\n예: 가로 80 세로 60 두께 8 판에 지름 12 구멍 4개'
              }
              rows={5}
            />
          </div>
          <p className="hint-text">Ctrl + Enter 로 생성</p>

          <button
            className="btn-primary"
            style={{ marginTop: '0.75rem' }}
            onClick={() => handleGenerate()}
            disabled={loading || !input.trim()}
          >
            {loading ? '생성 중...' : 'CAD 생성'}
          </button>

          {error && <div className="error-box" style={{ marginTop: '1rem' }}>{error}</div>}

          {result?.status === 'success' && (
            <div className="result-section">
              <p className="label-muted">해석된 파라미터</p>
              <pre className="params-pre">{JSON.stringify(parsedParams, null, 2)}</pre>
              <button className="btn-secondary" onClick={handleDownload}>
                STL 다운로드
              </button>
            </div>
          )}

          {/* Personal prompt settings */}
          <div className="settings-toggle-section">
            <button className="btn-text" onClick={() => setShowSettings(!showSettings)}>
              {showSettings ? '▼' : '▶'} 개인 프롬프트 설정
            </button>
            {showSettings && (
              <div className="settings-panel">
                <p className="label-muted">
                  AI 해석에 반영할 추가 지시사항을 입력하세요.<br />
                  예: "기본 단위는 mm입니다", "모서리를 가능하면 둥글게"
                </p>
                <textarea
                  value={customPrompt}
                  onChange={(e) => setCustomPrompt(e.target.value)}
                  placeholder="개인 프롬프트 (선택사항)"
                  rows={3}
                  style={{ marginBottom: '0.5rem' }}
                />
                <button
                  className="btn-secondary"
                  onClick={handleSavePrompt}
                  disabled={savingPrompt}
                >
                  {savingPrompt ? '저장 중...' : '저장'}
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Right panel — 3D preview */}
        <div className="panel">
          <h2 className="panel-title">3D 미리보기</h2>
          <div className="preview-box">
            {loading && (
              <div className="preview-overlay">
                <div className="spinner" />
                <p>CAD 파일 생성 중...</p>
              </div>
            )}
            {!loading && result?.stl_url && <Preview3D key={result.stl_url} stlUrl={result.stl_url} />}
            {!loading && !result && (
              <div className="preview-placeholder">
                <span className="placeholder-icon">⬡</span>
                <p>형상을 입력하면 미리보기가 표시됩니다</p>
                <p className="label-muted" style={{ marginTop: '0.5rem', fontSize: '0.8rem' }}>
                  마우스로 회전 · 스크롤로 확대/축소
                </p>
              </div>
            )}
            {!loading && result?.status === 'failed' && (
              <div className="preview-placeholder">
                <span className="placeholder-icon" style={{ color: '#e74c3c' }}>✕</span>
                <p>생성 실패</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
