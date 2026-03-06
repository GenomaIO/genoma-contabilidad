import { useState, useCallback, useEffect } from 'react'
import { useApp } from '../context/AppContext'

// ─── Helpers ─────────────────────────────────────────────────────
const fmt = n => {
    if (n == null) return '—'
    return new Intl.NumberFormat('es-CR', { style: 'currency', currency: 'CRC', minimumFractionDigits: 2 }).format(n)
}

const fmtDate = d => d ? new Date(d + 'T12:00:00').toLocaleDateString('es-CR', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'

const TYPE_COLOR = {
    ACTIVO: '#10b981',
    PASIVO: '#ef4444',
    PATRIMONIO: '#8b5cf6',
    INGRESO: '#3b82f6',
    GASTO: '#f59e0b',
}

const TYPE_LABEL = {
    ACTIVO: 'ACT', PASIVO: 'PAS', PATRIMONIO: 'PAT', INGRESO: 'ING', GASTO: 'GST'
}

/**
 * getSaldoColor: color del saldo según la naturaleza contable
 *   ACTIVO / GASTO → saldo normal es DR (positivo) → verde si ≥ 0
 *   PASIVO / PATRIMONIO / INGRESO → saldo normal es CR (negativo) → verde si ≤ 0
 */
function getSaldoColor(saldo, accountType) {
    const drNormal = accountType === 'ACTIVO' || accountType === 'GASTO'
    if (drNormal) return saldo >= 0 ? '#10b981' : '#ef4444'
    return saldo <= 0 ? '#10b981' : '#ef4444'
}

// ─── Componente principal ─────────────────────────────────────────
export default function Mayor() {
    const { state } = useApp()
    const token = state?.user?.token || state?.token
    const apiUrl = import.meta.env.VITE_API_URL || ''

    // ── Estado ────────────────────────────────────────────────────
    const [searchQ, setSearchQ] = useState('')
    const [allAccounts, setAllAccounts] = useState([])
    const [selectedAcc, setSelectedAcc] = useState(null)
    const [fromDate, setFromDate] = useState(() => `${new Date().getFullYear()}-01-01`)
    const [toDate, setToDate] = useState(() => new Date().toISOString().slice(0, 10))

    const [mayorData, setMayorData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    const [showSearch, setShowSearch] = useState(false)
    const [accsLoaded, setAccsLoaded] = useState(false)

    // Índice automático — cuentas con actividad al cargar
    const [indexData, setIndexData] = useState(null)
    const [indexLoading, setIndexLoading] = useState(false)

    // ── Cargar catálogo N4 (mayorizable=true) — incluye N4 aunque tengan hijos N5 ──
    const loadAccounts = useCallback(async () => {
        if (accsLoaded) return
        try {
            const r = await fetch(`${apiUrl}/catalog/accounts/posteable?mayorizable=true`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (r.ok) {
                const d = await r.json()
                setAllAccounts(d)
                setAccsLoaded(true)
            }
        } catch { /* sin catálogo */ }
    }, [apiUrl, token, accsLoaded])

    // ── Índice automático: al cargar, buscar cuentas con actividad ──
    const loadIndex = useCallback(async () => {
        if (!token || indexData || indexLoading) return  // guard: esperar token
        setIndexLoading(true)
        try {
            const r = await fetch(
                `${apiUrl}/ledger/mayor?from_date=${fromDate}&to_date=${toDate}`,
                { headers: { Authorization: `Bearer ${token}` } }
            )
            if (r.ok) setIndexData(await r.json())
        } catch { /* sin índice */ }
        finally { setIndexLoading(false) }
    }, [apiUrl, token, fromDate, toDate, indexData, indexLoading])

    // Cargar índice cuando el token esté disponible (puede hidratarse después de montar)
    useEffect(() => { if (token && !indexData) loadIndex() }, [token]) // eslint-disable-line

    // ── Filtrar cuentas por búsqueda ──────────────────────────────
    const filtered = allAccounts.filter(a =>
        a.display_code?.toLowerCase().includes(searchQ.toLowerCase()) ||
        a.name?.toLowerCase().includes(searchQ.toLowerCase())
    ).slice(0, 20)

    // ── Consultar el mayor ────────────────────────────────────────
    async function fetchMayor(code = selectedAcc?.code) {
        if (!code) return
        setLoading(true); setError(null)
        try {
            const r = await fetch(
                `${apiUrl}/ledger/mayor/${encodeURIComponent(code)}?from_date=${fromDate}&to_date=${toDate}`,
                { headers: { Authorization: `Bearer ${token}` } }
            )
            if (!r.ok) {
                const e = await r.json()
                throw new Error(e.detail || `Error ${r.status}`)
            }
            setMayorData(await r.json())
        } catch (e) {
            setError(e.message)
        } finally {
            setLoading(false)
        }
    }

    // ── Seleccionar cuenta ────────────────────────────────────────
    function selectAccount(acc) {
        setSelectedAcc(acc)
        setShowSearch(false)
        setSearchQ('')
        setMayorData(null)
    }

    const color = mayorData ? (TYPE_COLOR[mayorData.account_type] || '#6b7280') : '#6b7280'
    const hasData = mayorData && !loading

    // ────────────────────────────────────────────────────────────────
    return (
        <div style={{ padding: '24px', maxWidth: 980, margin: '0 auto', fontFamily: 'Inter, sans-serif' }}>

            {/* ── Header ─────────────────────────────────────── */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
                <div>
                    <h1 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                        📒 Libro Mayor
                    </h1>
                    <p style={{ margin: '4px 0 0', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        T-account por cuenta — saldo inicial + movimientos + saldo cierre
                    </p>
                </div>

                {/* Tooltip guía */}
                <div style={{ position: 'relative', display: 'inline-block' }}
                    onMouseEnter={e => e.currentTarget.querySelector('.mayor-guide').style.display = 'block'}
                    onMouseLeave={e => e.currentTarget.querySelector('.mayor-guide').style.display = 'none'}
                >
                    <span style={{ cursor: 'help', fontSize: '1.1rem' }}>💡 Guía</span>
                    <div className="mayor-guide" style={{
                        display: 'none', position: 'absolute', right: 0, top: '130%',
                        background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                        borderRadius: 10, padding: '14px 18px', zIndex: 100, width: 320,
                        fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.6,
                        boxShadow: '0 8px 32px rgba(0,0,0,0.25)',
                    }}>
                        <strong style={{ color: 'var(--text-primary)' }}>📒 ¿Qué es el Libro Mayor?</strong><br />
                        Muestra todos los movimientos de una cuenta específica ordenados por fecha,
                        con el saldo acumulado (saldo running) después de cada asiento.<br /><br />
                        <strong>Saldo inicial:</strong> viene del asiento de <em>Apertura</em>.<br />
                        <strong>Saldo cierre:</strong> apertura + débitos − créditos del período.<br /><br />
                        Solo se incluyen asientos <strong>POSTED</strong> — los borradores no afectan el mayor.
                    </div>
                </div>
            </div>

            {/* ── Filtros ─────────────────────────────────────── */}
            <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: 12,
                marginBottom: 20, alignItems: 'end',
            }}>
                {/* Selector de cuenta */}
                <div style={{ gridColumn: '1 / 2' }}>
                    <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                        Cuenta
                    </label>
                    <div style={{ position: 'relative' }}>
                        <div
                            id="mayor-account-select"
                            onClick={() => { setShowSearch(s => !s); loadAccounts() }}
                            style={{
                                padding: '8px 12px', borderRadius: 8,
                                border: `1px solid ${selectedAcc ? color : 'var(--border-color)'}`,
                                background: 'var(--bg-card)', cursor: 'pointer',
                                display: 'flex', alignItems: 'center', gap: 8,
                                fontSize: '0.83rem', color: 'var(--text-primary)',
                                minHeight: 38,
                            }}
                        >
                            {selectedAcc ? (
                                <>
                                    <span style={{ fontFamily: 'monospace', color, fontWeight: 700, fontSize: '0.82rem' }}>
                                        {selectedAcc.display_code}
                                    </span>
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {selectedAcc.name}
                                    </span>
                                </>
                            ) : (
                                <span style={{ color: 'var(--text-muted)' }}>Seleccionar cuenta...</span>
                            )}
                        </div>

                        {/* Dropdown de búsqueda */}
                        {showSearch && (
                            <div style={{
                                position: 'absolute', top: '110%', left: 0, right: 0, zIndex: 200,
                                background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                                borderRadius: 10, boxShadow: '0 8px 24px rgba(0,0,0,0.2)', overflow: 'hidden',
                            }}>
                                <input
                                    id="mayor-search-input"
                                    autoFocus
                                    placeholder="Buscar por código o nombre..."
                                    value={searchQ}
                                    onChange={e => setSearchQ(e.target.value)}
                                    style={{
                                        width: '100%', padding: '9px 12px', border: 'none', outline: 'none',
                                        borderBottom: '1px solid var(--border-color)',
                                        background: 'var(--bg-card)', color: 'var(--text-primary)',
                                        fontSize: '0.83rem', boxSizing: 'border-box',
                                    }}
                                />
                                <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                                    {filtered.length === 0 && (
                                        <div style={{ padding: '12px 16px', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                                            Sin resultados
                                        </div>
                                    )}
                                    {filtered.map(acc => {
                                        const col = TYPE_COLOR[acc.account_type] || '#6b7280'
                                        return (
                                            <div
                                                key={acc.code}
                                                id={`mayor-acc-${acc.code}`}
                                                onClick={() => selectAccount(acc)}
                                                style={{
                                                    padding: '8px 14px', cursor: 'pointer',
                                                    display: 'flex', alignItems: 'center', gap: 10,
                                                    transition: 'background 0.12s',
                                                }}
                                                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                                                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                                            >
                                                <span style={{ fontFamily: 'monospace', color: col, fontWeight: 700, fontSize: '0.78rem', minWidth: 60 }}>
                                                    {acc.display_code}
                                                </span>
                                                <span style={{ fontSize: '0.82rem', color: 'var(--text-primary)' }}>
                                                    {acc.name}
                                                </span>
                                                <span style={{ marginLeft: 'auto', fontSize: '0.68rem', color: col, fontWeight: 600 }}>
                                                    {TYPE_LABEL[acc.account_type] || ''}
                                                </span>
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Desde */}
                <div>
                    <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Desde</label>
                    <input
                        id="mayor-from-date"
                        type="date"
                        value={fromDate}
                        onChange={e => setFromDate(e.target.value)}
                        style={{ width: '100%', padding: '7px 10px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.83rem', boxSizing: 'border-box' }}
                    />
                </div>

                {/* Hasta */}
                <div>
                    <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Hasta</label>
                    <input
                        id="mayor-to-date"
                        type="date"
                        value={toDate}
                        onChange={e => setToDate(e.target.value)}
                        style={{ width: '100%', padding: '7px 10px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.83rem', boxSizing: 'border-box' }}
                    />
                </div>

                {/* Botón Consultar */}
                <button
                    id="mayor-consultar-btn"
                    onClick={() => fetchMayor()}
                    disabled={!selectedAcc || loading}
                    style={{
                        padding: '8px 20px', borderRadius: 8, border: 'none',
                        background: selectedAcc ? 'var(--accent)' : 'var(--border-color)',
                        color: selectedAcc ? '#fff' : 'var(--text-muted)',
                        cursor: selectedAcc ? 'pointer' : 'not-allowed',
                        fontSize: '0.85rem', fontWeight: 600, whiteSpace: 'nowrap',
                        transition: 'opacity 0.2s',
                    }}
                >
                    {loading ? '⏳' : '🔍 Consultar'}
                </button>
            </div>

            {/* ── Error ──────────────────────────────────────── */}
            {error && (
                <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 16px', marginBottom: 16, color: '#ef4444', fontSize: '0.82rem' }}>
                    ⚠️ {error}
                </div>
            )}

            {/* ── Resultado del Mayor ──────────────────────────── */}
            {hasData && (
                <div>
                    {/* Header de la cuenta */}
                    <div style={{
                        background: `${color}12`, border: `1.5px solid ${color}40`,
                        borderRadius: 12, padding: '16px 20px', marginBottom: 16,
                        display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16,
                    }}>
                        <div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 4 }}>Cuenta</div>
                            <div style={{ fontFamily: 'monospace', fontWeight: 800, fontSize: '1rem', color }}>
                                {mayorData.account_code}
                            </div>
                            <div style={{ fontSize: '0.82rem', color: 'var(--text-primary)', fontWeight: 600 }}>
                                {mayorData.account_name}
                            </div>
                        </div>
                        <div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 4 }}>
                                Saldo Inicial {mayorData.has_apertura ? '(Apertura)' : '(sin apertura)'}
                            </div>
                            <div style={{ fontSize: '0.95rem', fontWeight: 700, color: getSaldoColor(mayorData.opening_balance, mayorData.account_type) }}>
                                {fmt(mayorData.opening_balance)}
                            </div>
                        </div>
                        <div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 4 }}>Movimientos del período</div>
                            <div style={{ fontSize: '0.82rem', color: '#10b981' }}>DR {fmt(mayorData.total_debit)}</div>
                            <div style={{ fontSize: '0.82rem', color: '#ef4444' }}>CR {fmt(mayorData.total_credit)}</div>
                        </div>
                        <div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 4 }}>Saldo Cierre</div>
                            <div style={{ fontSize: '1rem', fontWeight: 800, color: getSaldoColor(mayorData.closing_balance, mayorData.account_type) }}>
                                {fmt(mayorData.closing_balance)}
                            </div>
                        </div>
                    </div>

                    {/* Tabla T-account */}
                    <div style={{ borderRadius: 10, overflow: 'hidden', border: '1px solid var(--border-color)' }}>
                        {/* Columnas */}
                        <div style={{
                            display: 'grid', gridTemplateColumns: '110px 1fr 140px 140px 160px',
                            background: 'var(--bg-header)', padding: '8px 16px',
                            borderBottom: '1px solid var(--border-color)',
                        }}>
                            {['FECHA', 'DESCRIPCIÓN', 'DEBE (DR)', 'HABER (CR)', 'SALDO'].map((h, i) => (
                                <div key={i} style={{
                                    fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.05em',
                                    color: 'var(--text-muted)',
                                    textAlign: i >= 2 ? 'right' : 'left',
                                }}>
                                    {h}
                                </div>
                            ))}
                        </div>

                        {/* Fila de saldo inicial */}
                        <div style={{
                            display: 'grid', gridTemplateColumns: '110px 1fr 140px 140px 160px',
                            padding: '10px 16px',
                            background: `${color}10`,
                            borderBottom: '1px solid var(--border-color)',
                        }}>
                            <div style={{ fontSize: '0.77rem', color: 'var(--text-muted)' }}>{mayorData.from_date}</div>
                            <div style={{ fontSize: '0.82rem', color, fontWeight: 600, fontStyle: 'italic' }}>
                                ← Saldo de Apertura
                            </div>
                            <div style={{ textAlign: 'right' }} />
                            <div style={{ textAlign: 'right' }} />
                            <div style={{ textAlign: 'right', fontWeight: 700, fontSize: '0.85rem', color: getSaldoColor(mayorData.opening_balance, mayorData.account_type) }}>
                                {fmt(mayorData.opening_balance)}
                            </div>
                        </div>

                        {/* Movimientos */}
                        {mayorData.movements.length === 0 && (
                            <div style={{ padding: '20px 16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                                Sin movimientos en el período seleccionado
                            </div>
                        )}
                        {mayorData.movements.map((m, i) => (
                            <div
                                key={i}
                                style={{
                                    display: 'grid', gridTemplateColumns: '110px 1fr 140px 140px 160px',
                                    padding: '9px 16px',
                                    borderBottom: '1px solid var(--border-color)',
                                    background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                                    transition: 'background 0.1s',
                                }}
                                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                                onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)'}
                            >
                                <div style={{ fontSize: '0.77rem', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                                    {fmtDate(m.date)}
                                </div>
                                <div style={{ fontSize: '0.82rem', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingRight: 8 }}>
                                    {m.description}
                                    {m.source !== 'MANUAL' && (
                                        <span style={{ marginLeft: 6, fontSize: '0.68rem', color: 'var(--text-muted)', background: 'rgba(99,102,241,0.15)', padding: '1px 5px', borderRadius: 4 }}>
                                            {m.source}
                                        </span>
                                    )}
                                </div>
                                <div style={{ textAlign: 'right', fontSize: '0.82rem', color: m.debit > 0 ? '#10b981' : 'var(--text-muted)', fontWeight: m.debit > 0 ? 600 : 400, fontFamily: 'monospace' }}>
                                    {m.debit > 0 ? fmt(m.debit) : ''}
                                </div>
                                <div style={{ textAlign: 'right', fontSize: '0.82rem', color: m.credit > 0 ? '#ef4444' : 'var(--text-muted)', fontWeight: m.credit > 0 ? 600 : 400, fontFamily: 'monospace' }}>
                                    {m.credit > 0 ? fmt(m.credit) : ''}
                                </div>
                                <div style={{ textAlign: 'right', fontSize: '0.83rem', fontWeight: 700, fontFamily: 'monospace', color: getSaldoColor(m.balance, mayorData.account_type) }}>
                                    {fmt(m.balance)}
                                </div>
                            </div>
                        ))}

                        {/* Fila totales */}
                        <div style={{
                            display: 'grid', gridTemplateColumns: '110px 1fr 140px 140px 160px',
                            padding: '10px 16px',
                            background: `${color}10`,
                            borderTop: `2px solid ${color}40`,
                        }}>
                            <div />
                            <div style={{ fontSize: '0.78rem', fontWeight: 700, color }}>TOTALES DEL PERÍODO</div>
                            <div style={{ textAlign: 'right', fontWeight: 700, fontSize: '0.85rem', color: '#10b981', fontFamily: 'monospace' }}>
                                {fmt(mayorData.total_debit)}
                            </div>
                            <div style={{ textAlign: 'right', fontWeight: 700, fontSize: '0.85rem', color: '#ef4444', fontFamily: 'monospace' }}>
                                {fmt(mayorData.total_credit)}
                            </div>
                            <div style={{ textAlign: 'right', fontWeight: 800, fontSize: '0.9rem', fontFamily: 'monospace', color: getSaldoColor(mayorData.closing_balance, mayorData.account_type) }}>
                                {fmt(mayorData.closing_balance)}
                            </div>
                        </div>
                    </div>

                    {/* Metadatos */}
                    <div style={{ marginTop: 10, fontSize: '0.72rem', color: 'var(--text-muted)', textAlign: 'right' }}>
                        Período: {fmtDate(mayorData.from_date)} → {fmtDate(mayorData.to_date)} ·
                        {mayorData.movements.length} movimiento{mayorData.movements.length !== 1 ? 's' : ''} ·
                        Solo asientos POSTED
                    </div>
                </div>
            )}

            {/* Estado vacío: índice automático de cuentas con actividad */}
            {!hasData && !loading && !error && (
                <div>
                    {/* NOTA: carga del índice solo en useEffect, no aquí */}

                    {indexLoading && (
                        <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                            ⏳ Buscando cuentas con actividad...
                        </div>
                    )}

                    {indexData && indexData.accounts && indexData.accounts.length > 0 && (
                        <div>
                            <div style={{ marginBottom: 12, fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.05em' }}>
                                📊 ÍNDICE DEL MAYOR — Cuentas con actividad ({indexData.accounts.length})
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '60px 1fr 140px 140px 140px', gap: 0, borderRadius: 10, overflow: 'hidden', border: '1px solid var(--border-color)' }}>
                                {/* Header */}
                                <div style={{ display: 'contents' }}>
                                    {['TIPO', 'CUENTA', 'SALDO APERTURA', 'MOVIMIENTOS', 'SALDO CIERRE'].map((h, i) => (
                                        <div key={i} style={{
                                            background: 'var(--bg-header)', padding: '8px 12px',
                                            fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.05em',
                                            color: 'var(--text-muted)', textAlign: i >= 2 ? 'right' : 'left',
                                            borderBottom: '1px solid var(--border-color)',
                                        }}>{h}</div>
                                    ))}
                                </div>
                                {/* Filas */}
                                {indexData.accounts.map((acc, i) => {
                                    const col = TYPE_COLOR[acc.account_type] || '#6b7280'
                                    return (
                                        <div key={acc.account_code} style={{ display: 'contents' }}
                                            onClick={() => {
                                                setSelectedAcc({ code: acc.account_code, display_code: acc.display_code || acc.account_code, name: acc.account_name, account_type: acc.account_type })
                                                fetchMayor(acc.account_code)
                                            }}
                                        >
                                            {[' ', ' ', ' ', ' ', ' '].map((_, ci) => (
                                                <div key={ci} style={{
                                                    padding: '9px 12px',
                                                    borderBottom: '1px solid var(--border-color)',
                                                    background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                                                    cursor: 'pointer',
                                                    transition: 'background 0.1s',
                                                }}
                                                    onMouseEnter={e => { e.currentTarget.parentElement.querySelectorAll('div').forEach(d => d.style.background = 'var(--bg-hover)') }}
                                                    onMouseLeave={e => { e.currentTarget.parentElement.querySelectorAll('div').forEach(d => d.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)') }}
                                                >
                                                    {ci === 0 && <span style={{ fontSize: '0.68rem', color: col, fontWeight: 700, background: `${col}20`, padding: '2px 6px', borderRadius: 4 }}>{TYPE_LABEL[acc.account_type] || '?'}</span>}
                                                    {ci === 1 && <><span style={{ fontFamily: 'monospace', color: col, fontWeight: 700, fontSize: '0.8rem', marginRight: 8 }}>{acc.display_code || acc.account_code}</span><span style={{ fontSize: '0.82rem', color: 'var(--text-primary)' }}>{acc.account_name}</span></>}
                                                    {ci === 2 && <span style={{ fontFamily: 'monospace', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{fmt(acc.opening_balance)}</span>}
                                                    {ci === 3 && <span style={{ fontFamily: 'monospace', fontSize: '0.8rem', color: acc.net_movement > 0 ? '#10b981' : acc.net_movement < 0 ? '#ef4444' : 'var(--text-muted)' }}>{fmt(Math.abs(acc.net_movement))}</span>}
                                                    {ci === 4 && <span style={{ fontFamily: 'monospace', fontSize: '0.82rem', fontWeight: 700, color: getSaldoColor(acc.closing_balance, acc.account_type) }}>{fmt(acc.closing_balance)}</span>}
                                                </div>
                                            ))}
                                        </div>
                                    )
                                })}
                            </div>
                            <div style={{ marginTop: 8, fontSize: '0.72rem', color: 'var(--text-muted)', textAlign: 'right' }}>
                                👇 Haz clic en una cuenta para ver su T-account
                            </div>
                        </div>
                    )}

                    {indexData && (!indexData.accounts || indexData.accounts.length === 0) && (
                        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)' }}>
                            <div style={{ fontSize: '3rem', marginBottom: 12 }}>📖</div>
                            <p style={{ fontSize: '0.9rem' }}>No hay movimientos registrados aún</p>
                            <p style={{ fontSize: '0.8rem', marginTop: 4 }}>El libro mayor se abre con el asiento de Apertura</p>
                        </div>
                    )}

                    {!indexData && !indexLoading && (
                        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)' }}>
                            <div style={{ fontSize: '3rem', marginBottom: 12 }}>📖</div>
                            <p style={{ fontSize: '0.9rem' }}>Selecciona una cuenta y presiona <strong>Consultar</strong></p>
                            <p style={{ fontSize: '0.8rem', marginTop: 4 }}>El mayor muestra el saldo inicial (apertura) + todos los movimientos del período</p>
                        </div>
                    )}
                </div>
            )}

            {loading && (
                <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                    ⏳ Cargando libro mayor...
                </div>
            )}
        </div>
    )
}
