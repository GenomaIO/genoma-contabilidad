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
    ACTIVO: { label: 'Activos (1xxx)', icon: '🏦', color: '#3b82f6' },
    PASIVO: { label: 'Pasivos (2xxx)', icon: '📄', color: '#ef4444' },
    PATRIMONIO: { label: 'Patrimonio (3xxx)', icon: '🏛️', color: '#8b5cf6' },
    INGRESO: { label: 'Ingresos (4xxx)', icon: '📈', color: '#10b981' },
    GASTO: { label: 'Gastos (5xxx)', icon: '📉', color: '#f59e0b' },
}

const TYPE_ORDER = ['ACTIVO', 'PASIVO', 'PATRIMONIO', 'INGRESO', 'GASTO']

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

    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')
    const role = state.user?.role
    const catalogMode = state.catalogMode   // G3: leer modo del contexto
    const canWrite = role === 'admin' || role === 'contador'

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
    async function handleSeed() {
        setSeeding(true)
        setError(null)
        try {
            const res = await fetch(`${apiUrl}/catalog/seed`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` }
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
                    {/* Nueva cuenta — solo admin/contador */}
                    {canWrite && (
                        <button
                            id="btn-nueva-cuenta"
                            onClick={() => setShowForm(true)}
                            style={{
                                padding: '8px 16px',
                                background: '#7c3aed',
                                border: 'none',
                                borderRadius: 8,
                                color: 'white',
                                fontSize: '0.85rem',
                                fontWeight: 600,
                                cursor: 'pointer'
                            }}
                        >
                            + Nueva cuenta
                        </button>
                    )}
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
                                    <div
                                        key={acc.code}
                                        id={`account-row-${acc.code}`}
                                        style={{
                                            display: 'flex',
                                            justifyContent: 'space-between',
                                            alignItems: 'center',
                                            padding: '10px 16px',
                                            paddingLeft: acc.parent_code ? 32 : 16,
                                            background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)',
                                            borderTop: '1px solid var(--border-color)',
                                            opacity: acc.is_active ? 1 : 0.45
                                        }}
                                    >
                                        {/* Código + nombre */}
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                            <span style={{
                                                fontFamily: 'monospace',
                                                fontSize: '0.85rem',
                                                color: cfg.color,
                                                fontWeight: 700,
                                                minWidth: 70
                                            }}>
                                                {acc.code}
                                            </span>
                                            <span style={{ fontSize: '0.88rem', color: 'var(--text-primary)' }}>
                                                {acc.name}
                                            </span>
                                            {!acc.allow_entries && (
                                                <span style={{ fontSize: '0.7rem', padding: '1px 7px', background: 'rgba(156,163,175,0.2)', borderRadius: 10, color: 'var(--text-muted)' }}>
                                                    grupo
                                                </span>
                                            )}
                                            {acc.is_generic && (
                                                <span style={{ fontSize: '0.7rem', padding: '1px 7px', background: 'rgba(124,58,237,0.2)', borderRadius: 10, color: '#7c3aed' }}>
                                                    genérica
                                                </span>
                                            )}
                                            {!acc.is_active && (
                                                <span style={{ fontSize: '0.7rem', padding: '1px 7px', background: 'rgba(239,68,68,0.15)', borderRadius: 10, color: '#ef4444' }}>
                                                    inactiva
                                                </span>
                                            )}
                                        </div>

                                        {/* Acciones — solo admin/contador */}
                                        {canWrite && !acc.is_generic && (
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
                                                    borderRadius: 6,
                                                    cursor: 'pointer',
                                                    whiteSpace: 'nowrap'
                                                }}
                                            >
                                                {toggling === acc.code ? '...' : acc.is_active ? 'Desactivar' : 'Reactivar'}
                                            </button>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )
            })}

            {/* Estado vacío — G2+G3: inteligente según catalogMode */}
            {!loading && filtered.length === 0 && (
                <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-secondary)' }}>
                    <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>
                        {q ? '🔍' : catalogMode === 'NONE' ? '⚙️' : catalogMode === 'STANDARD' ? '📋' : '📂'}
                    </div>
                    <p style={{ marginBottom: 16 }}>
                        {q
                            ? `No se encontraron cuentas para "${q}".`
                            : '¡Todavía no hay cuentas en el catálogo!'}
                    </p>

                    {/* Boton seed — solo si no hay busqueda activa y el rol lo permite */}
                    {canWrite && !q && catalogMode === 'STANDARD' && (
                        <button
                            id="btn-cargar-catalogo-standard"
                            onClick={handleSeed}
                            disabled={seeding}
                            style={{ padding: '10px 22px', background: '#7c3aed', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: seeding ? 'not-allowed' : 'pointer', fontSize: '0.9rem', marginBottom: 10 }}
                        >
                            {seeding ? '⏳ Cargando...' : '📋 Cargar catálogo NIIF CR estándar (~70 cuentas)'}
                        </button>
                    )}
                    {canWrite && !q && catalogMode === 'NONE' && (
                        <button
                            id="btn-cargar-catalogo-generico"
                            onClick={handleSeed}
                            disabled={seeding}
                            style={{ padding: '10px 22px', background: '#10b981', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: seeding ? 'not-allowed' : 'pointer', fontSize: '0.9rem', marginBottom: 10 }}
                        >
                            {seeding ? '⏳ Cargando...' : '⚙️ Cargar cuentas genéricas'}
                        </button>
                    )}
                    {canWrite && !q && catalogMode === 'CUSTOM' && (
                        <div>
                            <button
                                id="btn-crear-primera-cuenta"
                                onClick={() => setShowForm(true)}
                                style={{ padding: '10px 22px', background: '#f59e0b', border: 'none', borderRadius: 8, color: 'white', fontWeight: 700, cursor: 'pointer', fontSize: '0.9rem', marginBottom: 8 }}
                            >
                                📂 + Crear primera cuenta
                            </button>
                            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 4 }}>o importá un CSV desde Configuración</p>
                        </div>
                    )}
                    {/* Fallback si catalogMode no está seteado */}
                    {canWrite && !q && !catalogMode && (
                        <button onClick={() => setShowForm(true)} style={{ padding: '8px 20px', background: '#7c3aed', border: 'none', borderRadius: 8, color: 'white', cursor: 'pointer' }}>
                            + Crear primera cuenta
                        </button>
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
