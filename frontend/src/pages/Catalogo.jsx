/**
 * Catalogo.jsx — Pantalla del Plan de Cuentas
 *
 * Árbol expandible por tipo (ACTIVO/PASIVO/PATRIMONIO/INGRESO/GASTO).
 * Búsqueda live por código o nombre.
 * Botón "Nueva cuenta" solo para admin/contador.
 * Toggle activo/inactivo — sin DELETE (Regla de Oro: audit trail permanente).
 */
import { useState, useEffect, useMemo } from 'react'
import { useApp } from '../context/AppContext'

const TYPE_CONFIG = {
    ACTIVO: { label: 'ACTIVOS', icon: '🏦', color: '#3b82f6' },
    PASIVO: { label: 'PASIVOS', icon: '📄', color: '#ef4444' },
    PATRIMONIO: { label: 'PATRIMONIO', icon: '🏛️', color: '#8b5cf6' },
    INGRESO: { label: 'INGRESOS', icon: '📈', color: '#10b981' },
    GASTO: { label: 'GASTOS Y COSTOS', icon: '📉', color: '#f59e0b' },
}

const TYPE_ORDER = ['ACTIVO', 'PASIVO', 'PATRIMONIO', 'INGRESO', 'GASTO']

// ─── Jerarquía punteada — estándar NIIF PYMES Costa Rica (CCPA) ─────────────
// Convierte código interno → notación académica CR
// 1000→1  1100→1.1  1101→1.1.1  1201.02→1.2.1.02  5210.01→5.2.10.01
function getDisplayCode(code) {
    if (code.includes('.')) {
        const [base, sub] = code.split('.', 2)
        return `${getDisplayCode(base)}.${sub}`
    }
    if (code.length !== 4) return code
    const [g1, g2, g3, g4] = code
    if (g2 === '0' && g3 === '0' && g4 === '0') return g1          // 1000 → 1
    if (g3 === '0' && g4 === '0') return `${g1}.${g2}` // 1100 → 1.1
    const seq = String(parseInt(g3 + g4, 10))                       // 1101 → '1'
    return `${g1}.${g2}.${seq}`                                      // 1101 → 1.1.1
}

// Nivel de indentación: 1=raíz, 2=subgrupo, 3=cuenta, 4+=sub-cuenta
function getLevel(code) {
    if (code.includes('.')) return getLevel(code.split('.')[0]) + 1
    if (code.length !== 4) return 1
    const [, g2, g3, g4] = code
    if (g2 === '0' && g3 === '0' && g4 === '0') return 1
    if (g3 === '0' && g4 === '0') return 2
    return 3
}

export default function Catalogo() {
    const { state } = useApp()
    const [accounts, setAccounts] = useState([])
    const [loading, setLoading] = useState(true)
    const [q, setQ] = useState('')
    const [showInactive, setShowInactive] = useState(false)
    const [expanded, setExpanded] = useState({})
    const [showForm, setShowForm] = useState(false)
    const [toggling, setToggling] = useState(null)
    const [seeding, setSeeding] = useState(false)
    const [error, setError] = useState(null)
    // Botón ⊕ inline
    const [inlineForm, setInlineForm] = useState({ parentCode: null, name: '', saving: false })
    const [hoveredRow, setHoveredRow] = useState(null)

    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')
    const role = state.user?.role
    const canWrite = role === 'admin' || role === 'contador'

    // RO#6 Safe Fallback: si el contexto no tiene catalogMode (tenant sin onboarding),
    // Catalogo hace su propio fetch de /auth/me para obtenerlo directamente.
    // Usa estado local para no pisarle el contexto a otros componentes.
    const [localCatalogMode, setLocalCatalogMode] = useState(null)
    useEffect(() => {
        const ctxMode = state.catalogMode  // puede ser null si tenant es anterior al onboarding
        if (ctxMode) {
            setLocalCatalogMode(ctxMode)  // usar el contexto si ya está
            return
        }
        // Solo admin/contador necesitan saber el modo
        if (!canWrite || !token) return
        fetch(`${apiUrl}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d?.catalog_mode) setLocalCatalogMode(d.catalog_mode) })
            .catch(() => { }) // No-critico
    }, [state.catalogMode])

    // catalogMode efectivo: contexto tiene prioridad, luego fetch local
    const catalogMode = state.catalogMode || localCatalogMode

    useEffect(() => {
        fetchAccounts()
    }, [showInactive])

    async function fetchAccounts() {
        setLoading(true)
        setError(null)
        try {
            const params = new URLSearchParams({ only_active: !showInactive })
            const res = await fetch(`${apiUrl}/catalog/accounts?${params}`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (!res.ok) throw new Error('No se pudo cargar el catálogo')
            const data = await res.json()
            setAccounts(data)
            // Expandir todas las raíces por defecto
            const rootOpen = {}
            TYPE_ORDER.forEach(t => { rootOpen[t] = true })
            setExpanded(rootOpen)
        } catch (e) {
            setError(e.message)
        } finally {
            setLoading(false)
        }
    }

    async function handleToggle(code, isActive) {
        setToggling(code)
        try {
            const res = await fetch(`${apiUrl}/catalog/accounts/${code}/toggle`, {
                method: 'PATCH',
                headers: { Authorization: `Bearer ${token}` }
            })
            if (!res.ok) {
                const err = await res.json()
                alert(err.detail || 'Error al cambiar estado')
            } else {
                await fetchAccounts()
            }
        } finally {
            setToggling(null)
        }
    }

    // G2: Carga el catálogo según el modo (idempotente, no duplica)
    // mode: opcional — si viene, se pasa al backend para tenants sin onboarding
    async function handleSeed(mode) {
        setSeeding(true)
        setError(null)
        try {
            const body = mode ? JSON.stringify({ mode }) : '{}'
            const res = await fetch(`${apiUrl}/catalog/seed`, {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${token}`,
                    'Content-Type': 'application/json',
                },
                body,
            })
            if (!res.ok) {
                const err = await res.json()
                throw new Error(err.detail || 'Error al cargar el catálogo')
            }
            await fetchAccounts()
        } catch (e) {
            setError(e.message)
        } finally {
            setSeeding(false)
        }
    }

    // G3: Actualiza el catálogo añadiendo solo las cuentas nuevas del seed estándar
    async function handleReseedMissing() {
        setSeeding(true)
        setError(null)
        try {
            const res = await fetch(`${apiUrl}/catalog/reseed-missing`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` },
            })
            const data = await res.json()
            if (!res.ok) throw new Error(data.detail || 'Error al actualizar catálogo')
            await fetchAccounts()
            if (data.inserted > 0)
                alert(`✅ ${data.inserted} cuentas nuevas agregadas al catálogo.`)
        } catch (e) {
            setError(e.message)
        } finally {
            setSeeding(false)
        }
    }

    // ─── Funciones form inline ⊕ ─────────────────────────────────────────────
    function nextChildCode(parentCode) {
        const prefix = parentCode + '.'
        const children = accounts
            .map(a => a.code)
            .filter(c => c.startsWith(prefix) && !c.slice(prefix.length).includes('.'))
        if (!children.length) return `${parentCode}.01`
        const nums = children.map(c => {
            const n = parseInt(c.slice(prefix.length), 10)
            return isNaN(n) ? 0 : n
        })
        return `${parentCode}.${String(Math.max(...nums) + 1).padStart(2, '0')}`
    }

    function openInline(parentCode) {
        setInlineForm({ parentCode, name: '', saving: false })
    }

    function closeInline() {
        setInlineForm({ parentCode: null, name: '', saving: false })
    }

    async function handleAddChild(parentAcc) {
        const name = inlineForm.name.trim()
        if (name.length < 2) return
        const suggestedCode = nextChildCode(parentAcc.code)
        setInlineForm(f => ({ ...f, saving: true }))
        try {
            const res = await fetch(`${apiUrl}/catalog/accounts`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    code: suggestedCode,
                    name,
                    account_type: parentAcc.account_type,
                    account_sub_type: parentAcc.account_sub_type || null,
                    parent_code: parentAcc.code,
                    allow_entries: true,
                }),
            })
            if (!res.ok) {
                const err = await res.json()
                alert(err.detail || 'Error al crear cuenta')
            } else {
                closeInline()
                await fetchAccounts()
            }
        } catch { alert('Error de red') } finally {
            setInlineForm(f => ({ ...f, saving: false }))
        }
    }

    // Filtrar por búsqueda
    const filtered = useMemo(() => {
        if (!q) return accounts
        const ql = q.toLowerCase()
        return accounts.filter(a =>
            a.code.toLowerCase().includes(ql) || a.name.toLowerCase().includes(ql)
        )
    }, [accounts, q])

    // Agrupar por tipo
    const grouped = useMemo(() => {
        const g = {}
        TYPE_ORDER.forEach(t => { g[t] = [] })
        filtered.forEach(a => {
            if (g[a.account_type]) g[a.account_type].push(a)
        })
        return g
    }, [filtered])

    const totalCuentas = accounts.filter(a => a.allow_entries).length
    const totalGrupos = accounts.filter(a => !a.allow_entries).length

    return (
        <div style={{ padding: '24px', maxWidth: 900, margin: '0 auto', fontFamily: 'Inter, sans-serif' }}>

            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
                <div>
                    <h1 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        📒 Catálogo de Cuentas
                    </h1>
                    <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        {totalCuentas} cuentas · {totalGrupos} grupos
                    </p>
                </div>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                    {/* Mostrar inactivas */}
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.82rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                        <input type="checkbox" checked={showInactive} onChange={e => setShowInactive(e.target.checked)} />
                        Ver inactivas
                    </label>


                    {/* 💡 Guía de jerarquía DGCN — tooltip al hover */}
                    <div style={{ position: 'relative', display: 'inline-block' }}
                        onMouseEnter={e => e.currentTarget.querySelector('.dgcn-guide').style.display = 'block'}
                        onMouseLeave={e => e.currentTarget.querySelector('.dgcn-guide').style.display = 'none'}
                    >
                        <button id="btn-guia-catalogo" style={{
                            background: 'transparent', border: '1px solid var(--border-color)',
                            borderRadius: 20, padding: '5px 10px', cursor: 'pointer',
                            color: 'var(--text-secondary)', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: 5,
                        }}>💡 Guía</button>
                        <div className="dgcn-guide" style={{
                            display: 'none', position: 'absolute', right: 0, top: '110%', zIndex: 999,
                            background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                            borderRadius: 10, padding: '14px 16px', width: 360,
                            boxShadow: '0 8px 24px rgba(0,0,0,0.35)', fontSize: '0.78rem',
                        }}>
                            <p style={{ margin: '0 0 8px', fontWeight: 700, color: 'var(--text-primary)', fontSize: '0.85rem' }}>💡 Guía del Catálogo</p>
                            <p style={{ margin: '0 0 10px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                                Tu catálogo sigue la estructura de cuentas NIIF PYMES.
                                Recomendamos llegar hasta el <strong>Nivel 4 (Cuenta)</strong> y dejar que el usuario profundice si lo necesita.
                            </p>
                            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                <thead><tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                                    <th style={{ textAlign: 'left', padding: '3px 6px', color: 'var(--text-muted)', fontWeight: 600 }}>Nivel</th>
                                    <th style={{ textAlign: 'left', padding: '3px 6px', color: 'var(--text-muted)', fontWeight: 600 }}>Nombre</th>
                                    <th style={{ textAlign: 'left', padding: '3px 6px', color: 'var(--text-muted)', fontWeight: 600 }}>Ejemplo</th>
                                </tr></thead>
                                <tbody>
                                    {[['A', 'Clase', '1 = ACTIVO', '#3b82f6', true],
                                    ['B', 'Grupo', '1.1 = Activo Corriente', '#3b82f6', true],
                                    ['C', 'Rubro', '1.1.1 = Efectivo y Equiv.', '#3b82f6', true],
                                    ['DD', 'Cuenta ⭐', '1.1.1.01 = Caja y Bancos', '#10b981', true],
                                    ['EE', 'Subcuenta', '1.1.1.01.01 = Caja Chica', '#f59e0b', false],
                                    ['FF', 'Subcuenta anexa', '1.1.1.01.01.01', '#9ca3af', false],
                                    ['G', 'Detalle', '…nivel máximo', '#6b7280', false],
                                    ].map(([niv, nom, ej, col, rec]) => (
                                        <tr key={niv} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', opacity: rec ? 1 : 0.55 }}>
                                            <td style={{ padding: '4px 6px', fontFamily: 'monospace', color: col, fontWeight: 700 }}>{niv}</td>
                                            <td style={{ padding: '4px 6px', color: 'var(--text-primary)' }}>{nom}</td>
                                            <td style={{ padding: '4px 6px', color: 'var(--text-secondary)', fontFamily: 'monospace', fontSize: '0.72rem' }}>{ej}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            <p style={{ margin: '10px 0 0', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                ⭐ = Nivel recomendado · Use ⊕ en cualquier cuenta para agregar sub-cuentas.
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            {/* Buscador */}
            <input
                id="catalogo-search"
                type="text"
                placeholder="🔍  Buscar por código o nombre..."
                value={q}
                onChange={e => setQ(e.target.value)}
                style={{
                    width: '100%',
                    padding: '10px 14px',
                    border: '1px solid var(--border-color)',
                    borderRadius: 8,
                    background: 'var(--bg-card)',
                    color: 'var(--text-primary)',
                    fontSize: '0.9rem',
                    marginBottom: 20,
                    boxSizing: 'border-box'
                }}
            />

            {/* Error */}
            {error && (
                <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 14px', color: '#ef4444', marginBottom: 16, fontSize: '0.88rem' }}>
                    ⚠️ {error}
                </div>
            )}

            {/* Loading */}
            {loading && (
                <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-secondary)' }}>
                    ⏳ Cargando catálogo...
                </div>
            )}

            {/* Árbol por tipo */}
            {!loading && TYPE_ORDER.map(type => {
                const cfg = TYPE_CONFIG[type]
                const items = grouped[type] || []
                if (items.length === 0) return null

                return (
                    <div key={type} style={{ marginBottom: 16, border: '1px solid var(--border-color)', borderRadius: 10, overflow: 'hidden' }}>
                        {/* Cabecera grupo */}
                        <div
                            onClick={() => setExpanded(e => ({ ...e, [type]: !e[type] }))}
                            style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                padding: '12px 16px',
                                background: cfg.color + '18',
                                cursor: 'pointer',
                                userSelect: 'none'
                            }}
                        >
                            <span style={{ fontWeight: 700, color: cfg.color, fontSize: '0.95rem' }}>
                                {cfg.icon} {cfg.label}
                            </span>
                            <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                                {items.length} cuentas {expanded[type] ? '▲' : '▼'}
                            </span>
                        </div>

                        {/* Cuentas */}
                        {expanded[type] && (
                            <div>
                                {items.map((acc, i) => (
                                    <div key={acc.code} style={{ borderTop: '1px solid var(--border-color)' }}>
                                        {/* Fila principal */}
                                        <div
                                            id={`account-row-${acc.code}`}
                                            onMouseEnter={() => setHoveredRow(acc.code)}
                                            onMouseLeave={() => setHoveredRow(null)}
                                            style={{
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                alignItems: 'center',
                                                padding: `${getLevel(acc.code) >= 4 ? 7 : 9}px 16px`,
                                                paddingLeft: `${(getLevel(acc.code) - 1) * 20 + 16}px`,
                                                background: hoveredRow === acc.code ? 'rgba(255,255,255,0.03)' : i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)',
                                                opacity: acc.is_active ? 1 : 0.45,
                                                borderLeft: getLevel(acc.code) >= 4
                                                    ? `2px solid ${cfg.color}40`
                                                    : getLevel(acc.code) === 3
                                                        ? `2px solid ${cfg.color}22`
                                                        : 'none',
                                                transition: 'background 0.15s',
                                            }}
                                        >
                                            {/* Código punteado + nombre */}
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1, minWidth: 0 }}>
                                                <span style={{
                                                    fontFamily: 'monospace',
                                                    fontSize: getLevel(acc.code) <= 2 ? '0.88rem' : '0.78rem',
                                                    color: getLevel(acc.code) <= 2 ? cfg.color : cfg.color + 'bb',
                                                    fontWeight: getLevel(acc.code) <= 2 ? 700 : 500,
                                                    minWidth: getLevel(acc.code) >= 4 ? 90 : 70,
                                                    flexShrink: 0,
                                                }}>
                                                    {getDisplayCode(acc.code)}
                                                </span>
                                                <span style={{
                                                    fontSize: getLevel(acc.code) <= 1 ? '0.95rem'
                                                        : getLevel(acc.code) === 2 ? '0.88rem'
                                                            : getLevel(acc.code) === 3 ? '0.85rem' : '0.8rem',
                                                    fontWeight: getLevel(acc.code) <= 2 ? 600 : 400,
                                                    color: getLevel(acc.code) <= 2 ? 'var(--text-primary)' : 'var(--text-secondary)',
                                                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                                }}>
                                                    {acc.name}
                                                </span>
                                                {!acc.allow_entries && (
                                                    <span style={{ fontSize: '0.7rem', padding: '1px 7px', background: 'rgba(156,163,175,0.15)', borderRadius: 10, color: 'var(--text-muted)', flexShrink: 0 }}>grupo</span>
                                                )}
                                                {acc.is_generic && (
                                                    <span style={{ fontSize: '0.7rem', padding: '1px 7px', background: 'rgba(124,58,237,0.15)', borderRadius: 10, color: '#7c3aed', flexShrink: 0 }}>genérica</span>
                                                )}
                                                {!acc.is_active && (
                                                    <span style={{ fontSize: '0.7rem', padding: '1px 7px', background: 'rgba(239,68,68,0.15)', borderRadius: 10, color: '#ef4444', flexShrink: 0 }}>inactiva</span>
                                                )}
                                            </div>

                                            {/* Acciones */}
                                            {canWrite && !acc.is_generic && (
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                                                    {/* ⊕ Agregar sub-cuenta — en CUALQUIER cuenta activa, crea una hija directa (lógica DGCN) */}
                                                    {acc.is_active && (
                                                        <button
                                                            id={`add-child-${acc.code}`}
                                                            title="Agregar subcuenta"
                                                            onClick={() => inlineForm.parentCode === acc.code ? closeInline() : openInline(acc.code)}
                                                            style={{
                                                                width: 26, height: 26,
                                                                borderRadius: '50%',
                                                                border: `1px solid ${inlineForm.parentCode === acc.code ? cfg.color : cfg.color + '60'}`,
                                                                background: inlineForm.parentCode === acc.code ? cfg.color + '25' : 'transparent',
                                                                color: inlineForm.parentCode === acc.code ? cfg.color : cfg.color + '80',
                                                                cursor: 'pointer',
                                                                fontSize: '1rem',
                                                                lineHeight: 1,
                                                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                                opacity: hoveredRow === acc.code || inlineForm.parentCode === acc.code ? 1 : 0,
                                                                transition: 'opacity 0.2s, background 0.15s, color 0.15s',
                                                                padding: 0,
                                                            }}
                                                        >⊕</button>
                                                    )}
                                                    {/* Desactivar / Reactivar */}
                                                    <button
                                                        id={`toggle-${acc.code}`}
                                                        onClick={() => handleToggle(acc.code, acc.is_active)}
                                                        disabled={toggling === acc.code}
                                                        style={{
                                                            padding: '4px 10px',
                                                            fontSize: '0.75rem',
                                                            background: acc.is_active ? 'rgba(239,68,68,0.1)' : 'rgba(16,185,129,0.1)',
                                                            color: acc.is_active ? '#ef4444' : '#10b981',
                                                            border: `1px solid ${acc.is_active ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)'}`,
                                                            borderRadius: 6, cursor: 'pointer', whiteSpace: 'nowrap',
                                                        }}
                                                    >
                                                        {toggling === acc.code ? '...' : acc.is_active ? 'Desactivar' : 'Reactivar'}
                                                    </button>
                                                </div>
                                            )}
                                        </div>

                                        {/* Formulario inline ⊕ — se expande bajo la cuenta padre */}
                                        {canWrite && inlineForm.parentCode === acc.code && (
                                            <div style={{
                                                display: 'flex', alignItems: 'center', gap: 8,
                                                padding: '8px 16px',
                                                paddingLeft: `${(getLevel(acc.code)) * 20 + 16}px`,
                                                background: `${cfg.color}08`,
                                                borderLeft: `2px solid ${cfg.color}`,
                                                borderTop: `1px dashed ${cfg.color}40`,
                                                flexWrap: 'wrap',
                                            }}>
                                                <span style={{ fontSize: '0.72rem', color: cfg.color, fontWeight: 600, flexShrink: 0 }}>
                                                    ↳ {getDisplayCode(nextChildCode(acc.code))}
                                                </span>
                                                <input
                                                    id={`inline-name-${acc.code}`}
                                                    autoFocus
                                                    placeholder="Nombre de la cuenta..."
                                                    value={inlineForm.name}
                                                    onChange={e => setInlineForm(f => ({ ...f, name: e.target.value }))}
                                                    onKeyDown={e => { if (e.key === 'Enter') handleAddChild(acc); if (e.key === 'Escape') closeInline() }}
                                                    style={{
                                                        flex: 1, minWidth: 160,
                                                        padding: '5px 9px',
                                                        fontSize: '0.82rem',
                                                        border: `1px solid ${cfg.color}50`,
                                                        borderRadius: 6,
                                                        background: 'var(--bg-card)',
                                                        color: 'var(--text-primary)',
                                                        outline: 'none',
                                                    }}
                                                />
                                                <button
                                                    id={`inline-save-${acc.code}`}
                                                    onClick={() => handleAddChild(acc)}
                                                    disabled={inlineForm.name.trim().length < 2 || inlineForm.saving}
                                                    style={{
                                                        padding: '5px 12px', fontSize: '0.78rem', flexShrink: 0,
                                                        background: cfg.color, color: '#fff',
                                                        border: 'none', borderRadius: 6, cursor: 'pointer',
                                                        opacity: inlineForm.name.trim().length < 2 ? 0.45 : 1,
                                                    }}
                                                >
                                                    {inlineForm.saving ? '...' : '💾 Guardar'}
                                                </button>
                                                <button
                                                    onClick={closeInline}
                                                    style={{
                                                        padding: '5px 8px', fontSize: '0.78rem', flexShrink: 0,
                                                        background: 'transparent', color: 'var(--text-muted)',
                                                        border: '1px solid var(--border-color)', borderRadius: 6, cursor: 'pointer',
                                                    }}
                                                >✕</button>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )
            })}

            {/* Estado vacío — inteligente según catalogMode */}
            {!loading && filtered.length === 0 && (
                <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>
                    <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>
                        {q ? '🔍' : catalogMode === 'NONE' ? '⚙️' : catalogMode === 'STANDARD' ? '📋' : catalogMode === 'CUSTOM' ? '📂' : '📚'}
                    </div>
                    <p style={{ marginBottom: 16 }}>
                        {q
                            ? `No se encontraron cuentas para "${q}".`
                            : '¡Todavía no hay cuentas en el catálogo!'}
                    </p>

                    {/* Modo STANDARD: solo NIIF */}
                    {canWrite && !q && catalogMode === 'STANDARD' && (
                        <button id="btn-cargar-catalogo-standard" onClick={handleSeed} disabled={seeding}
                            style={{ display: 'block', width: '100%', maxWidth: 380, margin: '0 auto 10px', padding: '12px 22px', background: '#7c3aed', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: seeding ? 'not-allowed' : 'pointer', fontSize: '0.9rem' }}>
                            {seeding ? '⏳ Cargando...' : '📋 Cargar catálogo NIIF CR estándar (~70 cuentas)'}
                        </button>
                    )}

                    {/* Modo NONE: solo genérico */}
                    {canWrite && !q && catalogMode === 'NONE' && (
                        <button id="btn-cargar-catalogo-generico" onClick={handleSeed} disabled={seeding}
                            style={{ display: 'block', width: '100%', maxWidth: 380, margin: '0 auto 10px', padding: '12px 22px', background: '#10b981', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: seeding ? 'not-allowed' : 'pointer', fontSize: '0.9rem' }}>
                            {seeding ? '⏳ Cargando...' : '⚙️ Cargar cuentas genéricas'}
                        </button>
                    )}

                    {/* Modo CUSTOM: solo crear */}
                    {canWrite && !q && catalogMode === 'CUSTOM' && (
                        <div>
                            <button id="btn-crear-primera-cuenta" onClick={() => setShowForm(true)}
                                style={{ display: 'block', width: '100%', maxWidth: 380, margin: '0 auto 8px', padding: '12px 22px', background: '#f59e0b', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.9rem' }}>
                                📂 + Crear primera cuenta
                            </button>
                            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 4 }}>o importá un CSV desde Configuración</p>
                        </div>
                    )}

                    {/* Fallback: catalogMode=null (tenant existente sin modo) — RO#6 Safe Fallback */}
                    {/* Mostrar AMBOS seeds + crear para que el usuario elija */}
                    {canWrite && !q && !catalogMode && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center', maxWidth: 400, margin: '0 auto' }}>
                            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 4 }}>Eligé cómo iniciar tu catálogo:</p>
                            <button id="btn-cargar-catalogo-standard" onClick={() => handleSeed('STANDARD')} disabled={seeding}
                                style={{ width: '100%', padding: '12px 22px', background: '#7c3aed', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: seeding ? 'not-allowed' : 'pointer', fontSize: '0.9rem' }}>
                                {seeding ? '⏳ Cargando...' : '📋 Cargar catálogo NIIF CR (~70 cuentas recomendadas)'}
                            </button>
                            <button id="btn-cargar-catalogo-generico" onClick={() => handleSeed('NONE')} disabled={seeding}
                                style={{ width: '100%', padding: '10px 22px', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 8, color: 'var(--text-primary)', fontWeight: 600, cursor: seeding ? 'not-allowed' : 'pointer', fontSize: '0.88rem' }}>
                                {seeding ? '⏳ Cargando...' : '⚙️ Cargar cuentas genéricas básicas'}
                            </button>
                            <button id="btn-crear-primera-cuenta" onClick={() => setShowForm(true)}
                                style={{ width: '100%', padding: '10px 22px', background: 'transparent', border: '1px solid var(--border-color)', borderRadius: 8, color: 'var(--text-secondary)', fontWeight: 500, cursor: 'pointer', fontSize: '0.88rem' }}>
                                + Crear cuenta manualmente
                            </button>
                        </div>
                    )}
                </div>
            )}

            {/* Modal Nueva Cuenta (simplificado — componente completo en siguiente iteración) */}
            {showForm && <NuevaCuentaModal onClose={() => { setShowForm(false); fetchAccounts() }} apiUrl={apiUrl} token={token} />}
        </div>
    )
}


// ─────────────────────────────────────────────────────────────────
// Modal Nueva Cuenta
// ─────────────────────────────────────────────────────────────────

function NuevaCuentaModal({ onClose, apiUrl, token }) {
    const [form, setForm] = useState({ code: '', name: '', account_type: 'ACTIVO', parent_code: '', allow_entries: true })
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState(null)

    async function handleSubmit(e) {
        e.preventDefault()
        setSaving(true)
        setError(null)
        try {
            const body = {
                code: form.code,
                name: form.name,
                account_type: form.account_type,
                parent_code: form.parent_code || undefined,
                allow_entries: form.allow_entries,
            }
            const res = await fetch(`${apiUrl}/catalog/accounts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                body: JSON.stringify(body)
            })
            if (!res.ok) {
                const err = await res.json()
                throw new Error(err.detail || 'Error al crear cuenta')
            }
            onClose()
        } catch (e) {
            setError(e.message)
            setSaving(false)
        }
    }

    const inputStyle = { width: '100%', padding: '9px 12px', border: '1px solid var(--border-color)', borderRadius: 7, background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.88rem', boxSizing: 'border-box' }

    return (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
            <div style={{ background: 'var(--bg-secondary)', borderRadius: 14, padding: 28, width: '100%', maxWidth: 460, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
                <h2 style={{ margin: '0 0 20px', fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)' }}>➕ Nueva Cuenta</h2>
                <form onSubmit={handleSubmit}>
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Código *</label>
                        <input id="nueva-code" style={inputStyle} value={form.code} onChange={e => setForm(f => ({ ...f, code: e.target.value }))} placeholder="Ej: 5215" required />
                    </div>
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Nombre *</label>
                        <input id="nueva-name" style={inputStyle} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Ej: Gastos de Capacitación" required />
                    </div>
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Tipo *</label>
                        <select id="nueva-type" style={inputStyle} value={form.account_type} onChange={e => setForm(f => ({ ...f, account_type: e.target.value }))}>
                            {Object.entries(TYPE_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.icon} {v.label}</option>)}
                        </select>
                    </div>
                    <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Cuenta padre (código, opcional)</label>
                        <input id="nueva-parent" style={inputStyle} value={form.parent_code} onChange={e => setForm(f => ({ ...f, parent_code: e.target.value }))} placeholder="Ej: 5200" />
                    </div>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 18, fontSize: '0.85rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                        <input type="checkbox" checked={form.allow_entries} onChange={e => setForm(f => ({ ...f, allow_entries: e.target.checked }))} />
                        Permite asientos (desmarcar si es cuenta-grupo)
                    </label>
                    {error && <div style={{ color: '#ef4444', fontSize: '0.82rem', marginBottom: 12 }}>⚠️ {error}</div>}
                    <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                        <button type="button" onClick={onClose} style={{ padding: '8px 16px', background: 'transparent', border: '1px solid var(--border-color)', borderRadius: 7, color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.85rem' }}>Cancelar</button>
                        <button id="btn-guardar-cuenta" type="submit" disabled={saving} style={{ padding: '8px 20px', background: '#7c3aed', border: 'none', borderRadius: 7, color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.85rem' }}>
                            {saving ? 'Guardando...' : 'Guardar'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}
