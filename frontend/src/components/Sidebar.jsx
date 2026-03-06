import { useApp } from '../context/AppContext'
import { useNavigate, useLocation } from 'react-router-dom'

const NAV_ITEMS = [
    {
        section: 'Principal',
        items: [
            { icon: '📊', label: 'Dashboard', path: '/' },
            { icon: '📒', label: 'Diario', path: '/diario' },
            { icon: '📈', label: 'Mayor', path: '/mayor' },
            { icon: '⚖️', label: 'Balance', path: '/balance' },
        ]
    },
    {
        section: 'Documentos',
        items: [
            { icon: '🔗', label: 'Facturador', path: '/integracion' },
            { icon: '🔄', label: 'Asientos Internos', path: '/asientos' },
        ]
    },
    {
        section: 'Impuestos',
        items: [
            { icon: '🏛️', label: 'Tribu-CR', path: '/declaraciones' },
            { icon: '🔢', label: 'Prorrata IVA', path: '/prorrata' },
        ]
    },
    {
        section: 'Reportes',
        items: [
            { icon: '📑', label: 'Estados Financieros', path: '/reportes' },
            { icon: '📆', label: 'Cierre', path: '/cierre' },
        ]
    },
    {
        section: 'Sistema',
        items: [
            {
                icon: '⚙️', label: 'Configuración', path: '/config',
                children: [
                    { icon: '📂', label: 'Apertura', path: '/config/apertura' },
                    { icon: '📁', label: 'Catálogo', path: '/catalogo' },
                ]
            },
        ]
    }
]

export default function Sidebar() {
    const { state, dispatch } = useApp()
    const navigate = useNavigate()
    const location = useLocation()

    function handleNav(path) {
        navigate(path)
        if (window.innerWidth <= 768) {
            dispatch({ type: 'SET_SIDEBAR', payload: false })
        }
    }

    function isActive(path) {
        if (path === '/') return location.pathname === '/'
        return location.pathname === path || location.pathname.startsWith(path + '/')
    }

    function parentActive(item) {
        if (isActive(item.path)) return true
        return item.children?.some(c => isActive(c.path)) ?? false
    }

    return (
        <>
            {/* Overlay solo mobile */}
            <div
                className="sidebar-overlay"
                onClick={() => dispatch({ type: 'SET_SIDEBAR', payload: false })}
            />

            <aside className="sidebar">
                {/* Logo */}
                <div className="sidebar-logo">
                    <div className="sidebar-logo-icon">📚</div>
                    <div className="sidebar-logo-text">
                        <span className="sidebar-logo-name">Contabilidad</span>
                        <span className="sidebar-logo-sub">NIIF PYMES · Tribu-CR</span>
                    </div>
                </div>

                {/* Tenant info */}
                {state.tenant && (
                    <div style={{
                        padding: '8px 16px',
                        borderBottom: '1px solid rgba(255,255,255,0.07)',
                        fontSize: '0.75rem',
                        color: 'var(--sidebar-text)',
                    }}>
                        <div style={{ fontWeight: 600, color: '#fff', marginBottom: 2 }}>
                            {state.tenant.nombre}
                        </div>
                        <div>{state.tenant.cedula}</div>
                    </div>
                )}

                {/* Navegación */}
                <nav className="sidebar-nav">
                    {NAV_ITEMS.map(section => (
                        <div key={section.section}>
                            <div className="nav-section-title">{section.section}</div>

                            {section.items.map(item => (
                                <div key={item.path}>
                                    {/* Ítem principal */}
                                    <div
                                        className={`nav-item${parentActive(item) ? ' active' : ''}`}
                                        onClick={() => handleNav(item.path)}
                                        role="button"
                                        tabIndex={0}
                                        onKeyDown={e => e.key === 'Enter' && handleNav(item.path)}
                                    >
                                        <span className="nav-icon">{item.icon}</span>
                                        <span>{item.label}</span>
                                    </div>

                                    {/* Sub-ítems (children) — siempre visibles con indentación */}
                                    {item.children?.map(child => (
                                        <div
                                            key={child.path}
                                            className={`nav-item${isActive(child.path) ? ' active' : ''}`}
                                            onClick={() => handleNav(child.path)}
                                            role="button"
                                            tabIndex={0}
                                            onKeyDown={e => e.key === 'Enter' && handleNav(child.path)}
                                            style={{
                                                paddingLeft: 36,
                                                fontSize: '0.82rem',
                                                opacity: 0.85,
                                            }}
                                        >
                                            <span className="nav-icon" style={{ fontSize: '0.85rem' }}>{child.icon}</span>
                                            <span>{child.label}</span>
                                        </div>
                                    ))}
                                </div>
                            ))}
                        </div>
                    ))}
                </nav>

                {/* Footer */}
                <div style={{
                    padding: '12px 16px',
                    borderTop: '1px solid rgba(255,255,255,0.07)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    fontSize: '0.75rem',
                    color: 'var(--sidebar-text)',
                }}>
                    <div style={{
                        width: 8, height: 8, borderRadius: '50%',
                        background: state.apiStatus === 'ok' ? 'var(--success)' : 'var(--danger)',
                    }} />
                    API {state.apiStatus === 'ok' ? 'conectada' : 'sin conexión'}
                </div>
            </aside>
        </>
    )
}
