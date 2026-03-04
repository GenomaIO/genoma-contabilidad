import { useApp } from '../context/AppContext'
import { useLocation } from 'react-router-dom'

const PAGE_TITLES = {
    '/': 'Dashboard',
    '/diario': 'Libro Diario',
    '/mayor': 'Mayor General',
    '/balance': 'Balance de Comprobación',
    '/integracion': 'Integración Facturador',
    '/asientos': 'Asientos Internos',
    '/catalogo': 'Catálogo Contable',
    '/declaraciones': 'Declaraciones Tribu-CR',
    '/prorrata': 'Prorrata IVA',
    '/reportes': 'Estados Financieros',
    '/cierre': 'Cierre de Período',
    '/config': 'Configuración',
}

export default function Header() {
    const { state, dispatch, toggleTheme } = useApp()
    const location = useLocation()

    const now = new Date()
    const periodLabel = state.period
        ? `${state.period.year}-${String(state.period.month).padStart(2, '0')}`
        : `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`

    return (
        <header className="header">
            <div className="header-left">
                {/* Hamburger (mobile/tablet) */}
                <button
                    className="btn-icon"
                    onClick={() => dispatch({ type: 'TOGGLE_SIDEBAR' })}
                    aria-label="Abrir menú"
                    title="Menú"
                >
                    ☰
                </button>

                {/* Breadcrumb / Título */}
                <h1 style={{ fontSize: '1rem', fontWeight: 600 }}>
                    {PAGE_TITLES[location.pathname] || 'Contabilidad'}
                </h1>
            </div>

            <div className="header-right">
                {/* Selector de período */}
                <div className="period-selector" title="Período contable activo">
                    📅 <span>{periodLabel}</span> ▾
                </div>

                {/* Toggle dark/light */}
                <button
                    className="btn-icon"
                    onClick={toggleTheme}
                    title={state.theme === 'dark' ? 'Modo claro' : 'Modo oscuro'}
                    aria-label="Cambiar tema"
                >
                    {state.theme === 'dark' ? '☀️' : '🌙'}
                </button>

                {/* Usuario */}
                <button
                    className="btn-icon"
                    title={state.user?.nombre || 'Usuario'}
                    style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--accent-light)' }}
                >
                    {state.user?.nombre?.charAt(0)?.toUpperCase() || '👤'}
                </button>
            </div>
        </header>
    )
}
