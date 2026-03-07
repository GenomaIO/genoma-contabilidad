import { useApp } from '../context/AppContext'
import { useNavigate, useLocation } from 'react-router-dom'

// coming: true → muestra el ítem desactivado con badge "Pronto" (no navega, no rompe rutas)
const NAV_ITEMS = [
    {
        section: 'Principal',
        items: [
            { icon: '📊', label: 'Dashboard', path: '/' },
        ]
    },
    {
        section: 'Registros Contables',
        items: [
            { icon: '📒', label: 'Diario', path: '/diario' },
            { icon: '📈', label: 'Mayor', path: '/mayor' },
            { icon: '⚖️', label: 'Balance', path: '/balance' },
            { icon: '📆', label: 'Cierre', path: '/cierre' },
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
        section: 'Auxiliares',
        items: [
            { icon: '🏗️', label: 'Activos Fijos', path: '/auxiliares/activos' },
            { icon: '👥', label: 'Clientes (CxC)', path: '/auxiliares/clientes', coming: true },
            { icon: '🤝', label: 'Proveedores (CxP)', path: '/auxiliares/proveedores', coming: true },
        ]
    },
    {
        section: 'Generadores',
        items: [
            { icon: '📐', label: 'Provisiones', path: '/generadores/provisiones' },
            { icon: '💵', label: 'Nómina', path: '/generadores/nomina', coming: true },
            { icon: '💱', label: 'Ajuste FX', path: '/generadores/fx', coming: true },
        ]
    },
    {
        section: 'Impuestos',
        items: [
            { icon: '🏛️', label: 'Tribu-CR', path: '/declaraciones' },
            { icon: '🔢', label: 'Prorrata IVA', path: '/prorrata' },
            { icon: '📋', label: 'D-102 Renta', path: '/impuestos/d102', coming: true },
        ]
    },
    {
        section: 'Reportes',
        items: [
            { icon: '📑', label: 'Estados Financieros', path: '/reportes' },
            { icon: '📚', label: 'Libros Digitales', path: '/libros-digitales' },
            { icon: '📝', label: 'Notas EEFF', path: '/reportes/notas', coming: true },
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
                    { icon: '🗂️', label: 'Dimensiones', path: '/config/dimensiones', coming: true },
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
                                    {item.coming ? (
                                        /* Coming-soon: desactivado, badge "Pronto" */
                                        <div
                                            className="nav-item"
                                            style={{ opacity: 0.45, cursor: 'default', pointerEvents: 'none' }}
                                        >
                                            <span className="nav-icon">{item.icon}</span>
                                            <span style={{ flex: 1 }}>{item.label}</span>
                                            <span style={{
                                                fontSize: '0.6rem', fontWeight: 700,
                                                background: 'rgba(251,191,36,0.25)',
                                                color: '#fbbf24', padding: '1px 5px',
                                                borderRadius: 4, letterSpacing: '0.04em',
                                            }}>PRONTO</span>
                                        </div>
                                    ) : (
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
                                    )}

                                    {/* Sub-ítems (children) — siempre visibles con indentación */}
                                    {item.children?.map(child => (
                                        child.coming ? (
                                            <div
                                                key={child.path}
                                                className="nav-item"
                                                style={{
                                                    paddingLeft: 36, fontSize: '0.82rem',
                                                    opacity: 0.4, cursor: 'default',
                                                    pointerEvents: 'none',
                                                    display: 'flex', alignItems: 'center', gap: 4,
                                                }}
                                            >
                                                <span className="nav-icon" style={{ fontSize: '0.85rem' }}>{child.icon}</span>
                                                <span style={{ flex: 1 }}>{child.label}</span>
                                                <span style={{
                                                    fontSize: '0.6rem', fontWeight: 700,
                                                    background: 'rgba(251,191,36,0.25)',
                                                    color: '#fbbf24', padding: '1px 5px',
                                                    borderRadius: 4,
                                                }}>PRONTO</span>
                                            </div>
                                        ) : (
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
                                        )
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
