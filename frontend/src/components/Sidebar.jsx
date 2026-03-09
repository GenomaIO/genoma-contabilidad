import { useState } from 'react'
import { useApp } from '../context/AppContext'
import { useNavigate, useLocation } from 'react-router-dom'

// collapsible: true → el encabezado de la sección es clickeable para colapsar/expandir
// defaultOpen: false → empieza colapsado (Principal y Sistema siempre abiertos)
const NAV_ITEMS = [
    {
        section: 'Principal',
        collapsible: false,
        items: [
            { icon: '📊', label: 'Dashboard', path: '/' },
        ]
    },
    {
        section: 'Registros Contables',
        collapsible: true,
        defaultOpen: true,
        items: [
            { icon: '📒', label: 'Diario', path: '/diario' },
            { icon: '📈', label: 'Mayor', path: '/mayor' },
            { icon: '📆', label: 'Cierre Mensual', path: '/cierre' },
            { icon: '📅', label: 'Cierre Anual', path: '/cierre-anual' },
        ]
    },
    {
        section: 'Documentos',
        collapsible: true,
        defaultOpen: true,
        items: [
            { icon: '🔗', label: 'Facturador', path: '/integracion' },
        ]

    },
    {
        section: 'Auxiliares',
        collapsible: true,
        defaultOpen: true,
        items: [
            { icon: '🏗️', label: 'Activos Fijos', path: '/auxiliares/activos' },
            { icon: '👥', label: 'Clientes (CxC)', path: '/auxiliares/clientes', coming: true },
            { icon: '🤝', label: 'Proveedores (CxP)', path: '/auxiliares/proveedores', coming: true },
        ]
    },
    {
        section: 'Generadores',
        collapsible: true,
        defaultOpen: true,
        items: [
            { icon: '💱', label: 'Ajuste FX', path: '/generadores/fx', coming: true },
            { icon: '🛡️', label: 'CENTINELA Fiscal', path: '/centinela' },
            { icon: '🏦', label: 'Conciliación Bancaria', path: '/conciliacion' },
            { icon: '💵', label: 'Nómina', path: '/generadores/nomina', coming: true },
            { icon: '📐', label: 'Provisiones', path: '/generadores/provisiones' },
        ]
    },
    {
        section: 'Impuestos',
        collapsible: true,
        defaultOpen: true,
        items: [
            { icon: '🏛️', label: 'Tribu-CR', path: '/declaraciones' },
            { icon: '🔢', label: 'Prorrata IVA', path: '/prorrata' },
            { icon: '📋', label: 'D-102 Renta', path: '/impuestos/d102', coming: true },
        ]
    },
    {
        section: 'Reportes',
        collapsible: true,
        defaultOpen: true,
        items: [
            { icon: '⚖️', label: 'Balanza de Comprobación', path: '/balanza' },
            { icon: '📑', label: 'Estados Financieros', path: '/reportes' },
            { icon: '📚', label: 'Libros Digitales', path: '/libros-digitales' },
            { icon: '📝', label: 'Notas EEFF', path: '/reportes/notas', coming: true },
        ]
    },
    {
        section: 'Sistema',
        collapsible: false,
        items: [
            {
                icon: '⚙️', label: 'Configuración', path: '/config',
                children: [
                    { icon: '📂', label: 'Apertura', path: '/config/apertura' },
                    { icon: '📁', label: 'Catálogo', path: '/catalogo' },
                    { icon: '🧾', label: 'Perfil Fiscal', path: '/config/perfil-fiscal' },
                    { icon: '🗂️', label: 'Dimensiones', path: '/config/dimensiones', coming: true },
                ]
            },
        ]
    }
]

// Inicializar el estado de colapso desde localStorage o por defecto
function initCollapsed() {
    try {
        const saved = localStorage.getItem('gc_sidebar_collapsed')
        if (saved) return JSON.parse(saved)
    } catch { /* descartar */ }
    // Valor por defecto: estado según defaultOpen de cada sección
    const init = {}
    NAV_ITEMS.forEach(s => {
        if (s.collapsible) init[s.section] = !(s.defaultOpen ?? true)
    })
    return init
}

export default function Sidebar() {
    const { state, dispatch } = useApp()
    const navigate = useNavigate()
    const location = useLocation()

    // collapsed[sectionName] = true → seccion colapsada
    const [collapsed, setCollapsed] = useState(initCollapsed)

    function toggleSection(sectionName) {
        setCollapsed(prev => {
            const next = { ...prev, [sectionName]: !prev[sectionName] }
            try { localStorage.setItem('gc_sidebar_collapsed', JSON.stringify(next)) } catch { /* noop */ }
            return next
        })
    }

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

    // Si la sección activa está colapsada, la abrimos automáticamente
    // (para que el usuario no pierda el ítem activo de vista)
    NAV_ITEMS.forEach(section => {
        if (section.collapsible && collapsed[section.section]) {
            const hasActive = section.items.some(item =>
                parentActive(item) || item.children?.some(c => isActive(c.path))
            )
            if (hasActive) {
                // Abrir sin guardar en localStorage (temporal)
                collapsed[section.section] = false
            }
        }
    })

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
                    {NAV_ITEMS.map(section => {
                        const isCollapsed = section.collapsible && collapsed[section.section]

                        return (
                            <div key={section.section}>
                                {/* Encabezado de sección */}
                                <div
                                    className="nav-section-title"
                                    onClick={section.collapsible ? () => toggleSection(section.section) : undefined}
                                    style={{
                                        cursor: section.collapsible ? 'pointer' : 'default',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        userSelect: 'none',
                                        transition: 'opacity 0.15s',
                                        ...(section.collapsible ? { opacity: 0.85 } : {}),
                                    }}
                                    onMouseEnter={section.collapsible
                                        ? e => e.currentTarget.style.opacity = '1'
                                        : undefined}
                                    onMouseLeave={section.collapsible
                                        ? e => e.currentTarget.style.opacity = '0.85'
                                        : undefined}
                                >
                                    {section.section}
                                    {section.collapsible && (
                                        <span style={{
                                            fontSize: '0.65rem',
                                            opacity: 0.6,
                                            transition: 'transform 0.22s ease',
                                            transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
                                            display: 'inline-block',
                                            lineHeight: 1,
                                        }}>
                                            ▾
                                        </span>
                                    )}
                                </div>

                                {/* Ítems — animación max-height */}
                                <div style={{
                                    overflow: 'hidden',
                                    maxHeight: isCollapsed ? '0px' : '600px',
                                    transition: isCollapsed
                                        ? 'max-height 0.22s ease-in'
                                        : 'max-height 0.32s ease-out',
                                    opacity: isCollapsed ? 0 : 1,
                                    transitionProperty: 'max-height, opacity',
                                }}>
                                    {section.items.map(item => (
                                        <div key={item.path}>
                                            {/* Ítem principal */}
                                            {item.coming ? (
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

                                            {/* Sub-ítems (children) */}
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
                                                        style={{ paddingLeft: 36, fontSize: '0.82rem', opacity: 0.85 }}
                                                    >
                                                        <span className="nav-icon" style={{ fontSize: '0.85rem' }}>{child.icon}</span>
                                                        <span>{child.label}</span>
                                                    </div>
                                                )
                                            ))}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )
                    })}
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
