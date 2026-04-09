import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const isActive = (path) => location.pathname === path ? 'nav-link active' : 'nav-link'

  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <Link to="/" className="brand-link">NL-CAD</Link>
        <span className="navbar-subtitle">자연어 CAD 생성기</span>
      </div>

      {user ? (
        <div className="navbar-menu">
          <Link to="/" className={isActive('/')}>생성</Link>
          <Link to="/history" className={isActive('/history')}>히스토리</Link>
          {user.is_admin && <Link to="/admin" className={isActive('/admin')}>관리자</Link>}
          <span className="navbar-email">{user.email}</span>
          <button onClick={handleLogout} className="btn-logout">로그아웃</button>
        </div>
      ) : (
        <div className="navbar-menu">
          <Link to="/login" className={isActive('/login')}>로그인</Link>
          <Link to="/register" className={isActive('/register')}>회원가입</Link>
        </div>
      )}
    </nav>
  )
}
