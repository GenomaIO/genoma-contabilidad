/**
 * Apertura.jsx — Módulo de Apertura de Ejercicio Fiscal
 *
 * Flujo (NIIF / principios contables internacionales):
 *   1. Verifica que el catálogo de cuentas tenga al menos cuentas de balance
 *   2. Verifica si ya existe apertura del año actual
 *   3. Si no existe: formulario para ingresar saldos iniciales
 *   4. Al confirmar: POST /ledger/opening-entry → POSTED directo
 *   5. Una vez aprobada: vista de solo lectura (perpetua e inmutable)
 *
 * Regla: solo cuentas de ACTIVO, PASIVO y PATRIMONIO.
 * Partida doble obligatoria: Debe = Haber.
 */
import { useState, useEffect, useMemo } from 'react'
import { useApp } from '../context/AppContext'

const TYPE_COLOR = { ACTIVO: '#3b82f6', PASIVO: '#ef4444', PATRIMONIO: '#8b5cf6', INGRESO: '#10b981', GASTO: '#f59e0b' }
const TYPE_ABBREV = { ACTIVO: 'ACT', PASIVO: 'PAS', PATRIMONIO: 'PAT', INGRESO: 'ING', GASTO: 'GAS' }
const BALANCE_TYPES = new Set(['ACTIVO', 'PASIVO', 'PATRIMONIO'])

const EMPTY_LINE = () => ({ account_code: '', display_code: '', _name: '', _type: '', debit: '', credit: '' })

const todayStr = () => {
    const d = new Date()
    return `${d.getFullYear()}-01-01`
}

const inputStyle = {
    padding: '8px 12px', borderRadius: 7, border: '1px solid var(--border-color)',
    background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.88rem',
    outline: 'none', width: '100%', boxSizing: 'border-box',
}

export default function Apertura() {
    const { state } = useApp()
    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')
    const role = state.user?.role
    const canWrite = role === 'admin' || role === 'contador'

    // Estado de la apertura existente
    const [existing, setExisting] = useState(null)   // null = cargando, false = no existe, {...} = existe
    const [loadingAp, setLoadingAp] = useState(true)

    // Catálogo de cuentas de balance disponibles
    const [balanceAccounts, setBalanceAccounts] = useState([])
    const [loadingCat, setLoadingCat] = useState(true)

    // Formulario
    const [lines, setLines] = useState([EMPTY_LINE(), EMPTY_LINE()])
    const [date, setDate] = useState(todayStr())
    const [desc, setDesc] = useState('Asiento de Apertura de Ejercicio')
    const [saving, setSaving] = useState(false)
    const [formError, setFormError] = useState(null)
    const [success, setSuccess] = useState(false)

    // Picker de cuenta
    const [pickers, setPickers] = useState({})

    const currentYear = new Date().getFullYear()

    // ── Cargar apertura existente ──────────────────────────────────
    useEffect(() => {
        if (!token) return
        setLoadingAp(true)
        fetch(`${apiUrl}/ledger/opening-entry?year=${currentYear}`, {
            headers: { Authorization: `Bearer ${token}` }
        })
            .then(r => r.ok ? r.json() : { exists: false })
            .then(data => setExisting(data))
            .catch(() => setExisting({ exists: false }))
            .finally(() => setLoadingAp(false))
    }, [success])

    // ── Cargar catálogo de balance (ACTIVO, PASIVO, PATRIMONIO) ────
    useEffect(() => {
        if (!token) return
        setLoadingCat(true)
        fetch(`${apiUrl}/catalog/accounts/posteable`, {
            headers: { Authorization: `Bearer ${token}` }
        })
            .then(r => r.ok ? r.json() : [])
            .then(data => {
                const bal = Array.isArray(data) ? data.filter(a => BALANCE_TYPES.has(a.account_type)) : []
                setBalanceAccounts(bal)
            })
            .catch(() => { })
            .finally(() => setLoadingCat(false))
    }, [])

    // ── Totales y balance ──────────────────────────────────────────
    const totalDebit = useMemo(() => lines.reduce((s, l) => s + (parseFloat(l.debit) || 0), 0), [lines])
    const totalCredit = useMemo(() => lines.reduce((s, l) => s + (parseFloat(l.credit) || 0), 0), [lines])
    const isBalanced = Math.abs(totalDebit - totalCredit) < 0.0001 && totalDebit > 0
    const canSave = isBalanced && canWrite && lines.length >= 2
        && lines.every(l => l.account_code)
        && date && desc.trim().length >= 3

    // ── Fuzzy de cuentas de balance ────────────────────────────────
    function fuzzyBalance(q) {
        if (!q || !q.trim()) return { items: balanceAccounts.slice(0, 12), total: balanceAccounts.length }
        const ql = q.toLowerCase().trim()
        const all = balanceAccounts.filter(a =>
            a.code.toLowerCase().includes(ql) ||
            (a.display_code || '').toLowerCase().includes(ql) ||
            a.name.toLowerCase().includes(ql) ||
            (TYPE_ABBREV[a.account_type] || '').toLowerCase().includes(ql)
        )
        return { items: all.slice(0, 12), total: all.length }
    }

    const inputRefs = []
    function openPicker(i) {
        const ref = inputRefs[i]
        let top = 0, left = 0, width = 380
        if (ref?.current) {
            const r = ref.current.getBoundingClientRect()
            const dH = 280
            const dW = Math.max(r.width, 380)
            const dropUp = (window.innerHeight - r.bottom) < dH && r.top > (window.innerHeight - r.bottom)
            top = dropUp ? r.top - dH - 4 : r.bottom + 4
            left = Math.min(r.left, window.innerWidth - dW - 8)
            left = Math.max(left, 8)
            width = dW
            setPickers(p => ({ ...p, [i]: { open: true, query: lines[i]?.display_code || '', hi: 0, top, left, width } }))
        } else {
            setPickers(p => ({ ...p, [i]: { open: true, query: lines[i]?.display_code || '', hi: 0, top, left, width } }))
        }
    }
    function closePicker(i) { setPickers(p => ({ ...p, [i]: { ...p[i], open: false } })) }
    function selectAccount(i, acc) {
        const newLines = [...lines]
        newLines[i] = { ...newLines[i], account_code: acc.code, display_code: acc.display_code, _name: acc.name, _type: acc.account_type }
        setLines(newLines)
        closePicker(i)
    }

    function updateLine(i, field, value) {
        const newLines = [...lines]
        newLines[i] = { ...newLines[i], [field]: value }
        if (field === 'debit' && parseFloat(value) > 0) newLines[i].credit = ''
        if (field === 'credit' && parseFloat(value) > 0) newLines[i].debit = ''
        setLines(newLines)
    }

    function addLine() { setLines(l => [...l, EMPTY_LINE()]) }
    function removeLine(i) { if (lines.length > 2) setLines(l => l.filter((_, x) => x !== i)) }

    // ── Guardar apertura ───────────────────────────────────────────
    async function handleSave() {
        if (!canSave) return
        setSaving(true); setFormError(null)
        try {
            const body = {
                date,
                description: desc,
                lines: lines.map(l => ({
                    account_code: l.account_code,
                    description: l._name || '',
                    debit: parseFloat(l.debit) || 0,
                    credit: parseFloat(l.credit) || 0,
                }))
            }
            const res = await fetch(`${apiUrl}/ledger/opening-entry`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            })
            if (!res.ok) {
                const err = await res.json()
                const detail = err.detail
                if (typeof detail === 'object' && detail.errors) throw new Error(detail.errors.join(' | '))
                throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
            }
            setSuccess(true)
        } catch (e) { setFormError(e.message) }
        finally { setSaving(false) }
    }

    // ─── Render ────────────────────────────────────────────────────
    if (loadingAp || loadingCat) return (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
            ⏳ Verificando estado del sistema contable...
        </div>
    )

    // ── Vista: apertura ya existe (solo lectura) ───────────────────
    if (existing?.exists) return (
        <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 24 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontSize: '1.5rem' }}>📋</span>
                    <div>
                        <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-primary)' }}>
                            Apertura de Ejercicio {currentYear}
                        </h2>
                        <span style={{ fontSize: '0.78rem', color: '#10b981' }}>✅ Aprobada — inmutable</span>
                    </div>
                </div>
                {/* 💡 Tooltip hover — sin click */}
                <div style={{ position: 'relative', display: 'inline-block' }}
                    onMouseEnter={e => e.currentTarget.querySelector('.apertura-guide').style.display = 'block'}
                    onMouseLeave={e => e.currentTarget.querySelector('.apertura-guide').style.display = 'none'}
                >
                    <button id="btn-guia-apertura" style={{ background: 'transparent', border: '1px solid var(--border-color)', borderRadius: 20, padding: '5px 10px', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: 5 }}>💡 Guía</button>
                    <div className="apertura-guide" style={{ display: 'none', position: 'absolute', right: 0, top: '110%', zIndex: 999, background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 10, padding: '14px 16px', width: 340, boxShadow: '0 8px 24px rgba(0,0,0,0.35)', fontSize: '0.78rem' }}>
                        <p style={{ margin: '0 0 8px', fontWeight: 700, color: 'var(--text-primary)', fontSize: '0.85rem' }}>💡 ¿Para qué sirve la Apertura de Ejercicio?</p>
                        <p style={{ margin: '0 0 10px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>Es el primer registro contable del año. Define los saldos iniciales de todas las cuentas de Balance (Activo, Pasivo, Patrimonio). Una vez aprobada, es <strong>perpetua e inmutable</strong>.</p>
                        <p style={{ margin: '0 0 6px', fontWeight: 600, color: 'var(--text-primary)' }}>Flujo correcto:</p>
                        <ol style={{ margin: '0 0 10px', paddingLeft: 16, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                            <li>Define el Catálogo de Cuentas</li>
                            <li>Ingresa los saldos iniciales aquí</li>
                            <li>Confirma → el sistema queda habilitado</li>
                        </ol>
                        <p style={{ margin: 0, fontSize: '0.73rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border-color)', paddingTop: 8 }}>Solo <strong>ACTIVO, PASIVO y PATRIMONIO</strong> — nunca ingresos ni gastos.<br />Debe = Haber obligatorio (partida doble).</p>
                    </div>
                </div>
            </div>

            {/* Cabecera del asiento */}
            <div style={{ background: 'var(--bg-card)', borderRadius: 10, padding: '14px 18px', marginBottom: 16, border: '1px solid var(--border-color)' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: '0.85rem' }}>
                    <div><span style={{ color: 'var(--text-muted)' }}>Fecha:</span> <strong>{existing.date}</strong></div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Estado:</span> <strong style={{ color: '#10b981' }}>POSTED</strong></div>
                    <div style={{ gridColumn: '1/-1' }}><span style={{ color: 'var(--text-muted)' }}>Descripción:</span> {existing.description}</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Aprobado:</span> {existing.approved_at?.slice(0, 10)}</div>
                </div>
            </div>

            {/* Líneas */}
            <div style={{ border: '1px solid var(--border-color)', borderRadius: 10, overflow: 'hidden' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr 120px 120px', gap: 8, padding: '8px 14px', background: 'rgba(0,0,0,0.1)', fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 700 }}>
                    <span>CUENTA</span><span>DESCRIPCIÓN</span>
                    <span style={{ textAlign: 'right' }}>DEBE</span>
                    <span style={{ textAlign: 'right' }}>HABER</span>
                </div>
                {existing.lines?.map((l, i) => (
                    <div key={i} style={{ display: 'grid', gridTemplateColumns: '200px 1fr 120px 120px', gap: 8, padding: '8px 14px', borderTop: '1px solid var(--border-color)', fontSize: '0.83rem' }}>
                        <span style={{ fontFamily: 'monospace', color: '#3b82f6' }}>{l.account_code}</span>
                        <span style={{ color: 'var(--text-secondary)' }}>{l.description}</span>
                        <span style={{ textAlign: 'right', color: '#3b82f6' }}>{l.debit > 0 ? `₡${l.debit.toLocaleString('es-CR', { minimumFractionDigits: 2 })}` : '—'}</span>
                        <span style={{ textAlign: 'right', color: '#10b981' }}>{l.credit > 0 ? `₡${l.credit.toLocaleString('es-CR', { minimumFractionDigits: 2 })}` : '—'}</span>
                    </div>
                ))}
                {/* Totales */}
                {(() => {
                    const td = existing.lines?.reduce((s, l) => s + l.debit, 0) || 0
                    const tc = existing.lines?.reduce((s, l) => s + l.credit, 0) || 0
                    return (
                        <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr 120px 120px', gap: 8, padding: '9px 14px', borderTop: '2px solid var(--border-color)', background: 'rgba(0,0,0,0.05)', fontSize: '0.85rem', fontWeight: 700 }}>
                            <span></span><span></span>
                            <span style={{ textAlign: 'right', color: '#3b82f6' }}>₡{td.toLocaleString('es-CR', { minimumFractionDigits: 2 })}</span>
                            <span style={{ textAlign: 'right', color: '#10b981' }}>₡{tc.toLocaleString('es-CR', { minimumFractionDigits: 2 })}</span>
                        </div>
                    )
                })()}
            </div>

            <div style={{ marginTop: 16, padding: '10px 14px', borderRadius: 8, background: 'rgba(16,185,129,0.08)', border: '1px solid #10b981', fontSize: '0.82rem', color: '#10b981' }}>
                ⚖️ Asiento balanceado · El ejercicio {currentYear} está correctamente abierto. Los módulos de Asientos, Mayorización y EEFF están habilitados.
            </div>
        </div>
    )

    // ── Vista: formulario de apertura ──────────────────────────────
    const catOk = balanceAccounts.length >= 2

    return (
        <div style={{ maxWidth: 820, margin: '0 auto', padding: '32px 20px' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontSize: '1.5rem' }}>📂</span>
                    <div>
                        <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-primary)' }}>
                            Apertura de Ejercicio {currentYear}
                        </h2>
                        <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                            Registra los saldos iniciales. Una vez aprobado, este asiento es perpetuo e inmutable.
                        </p>
                    </div>
                </div>
                {/* 💡 Tooltip hover — sin click */}
                <div style={{ position: 'relative', display: 'inline-block' }}
                    onMouseEnter={e => e.currentTarget.querySelector('.apertura-guide').style.display = 'block'}
                    onMouseLeave={e => e.currentTarget.querySelector('.apertura-guide').style.display = 'none'}
                >
                    <button id="btn-guia-apertura" style={{ background: 'transparent', border: '1px solid var(--border-color)', borderRadius: 20, padding: '5px 10px', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: 5 }}>💡 Guía</button>
                    <div className="apertura-guide" style={{ display: 'none', position: 'absolute', right: 0, top: '110%', zIndex: 999, background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 10, padding: '14px 16px', width: 340, boxShadow: '0 8px 24px rgba(0,0,0,0.35)', fontSize: '0.78rem' }}>
                        <p style={{ margin: '0 0 8px', fontWeight: 700, color: 'var(--text-primary)', fontSize: '0.85rem' }}>💡 ¿Para qué sirve la Apertura de Ejercicio?</p>
                        <p style={{ margin: '0 0 10px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>Es el primer registro contable del año. Define los saldos iniciales de todas las cuentas de Balance (Activo, Pasivo, Patrimonio). Una vez aprobada, es <strong>perpetua e inmutable</strong>.</p>
                        <p style={{ margin: '0 0 6px', fontWeight: 600, color: 'var(--text-primary)' }}>Flujo correcto:</p>
                        <ol style={{ margin: '0 0 10px', paddingLeft: 16, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                            <li>Define el Catálogo de Cuentas</li>
                            <li>Ingresa los saldos iniciales aquí</li>
                            <li>Confirma → el sistema queda habilitado</li>
                        </ol>
                        <p style={{ margin: 0, fontSize: '0.73rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border-color)', paddingTop: 8 }}>Solo <strong>ACTIVO, PASIVO y PATRIMONIO</strong> — nunca ingresos ni gastos.<br />Debe = Haber obligatorio (partida doble).</p>
                    </div>
                </div>
            </div>

            {/* Step 1: diagnóstico del catálogo */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', borderRadius: 8, marginBottom: 20, background: catOk ? 'rgba(16,185,129,0.08)' : 'rgba(245,158,11,0.1)', border: `1px solid ${catOk ? '#10b981' : '#f59e0b'}` }}>
                <span style={{ fontSize: '1.1rem' }}>{catOk ? '✅' : '⚠️'}</span>
                <span style={{ fontSize: '0.85rem', color: catOk ? '#10b981' : '#f59e0b' }}>
                    {catOk
                        ? `Catálogo listo — ${balanceAccounts.length} cuentas de balance disponibles (Activo, Pasivo, Patrimonio).`
                        : 'El catálogo no tiene cuentas de balance. Configura el Catálogo de Cuentas antes de crear la apertura.'
                    }
                </span>
            </div>

            {!catOk && (
                <div style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)' }}>
                    <a href="/catalog" style={{ color: '#7c3aed', fontWeight: 700 }}>→ Ir al Catálogo de Cuentas</a>
                </div>
            )}

            {catOk && !canWrite && (
                <div style={{ padding: '10px 16px', background: 'rgba(239,68,68,0.08)', border: '1px solid #ef4444', borderRadius: 8, color: '#ef4444', fontSize: '0.85rem', marginBottom: 20 }}>
                    Solo el contador o administrador puede crear el asiento de apertura.
                </div>
            )}

            {catOk && canWrite && (
                <>
                    {/* Fecha + Descripción */}
                    <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 12, marginBottom: 16 }}>
                        <div>
                            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Fecha de Apertura *</label>
                            <input type="date" value={date} onChange={e => setDate(e.target.value)} style={inputStyle} />
                        </div>
                        <div>
                            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Descripción *</label>
                            <input type="text" value={desc} onChange={e => setDesc(e.target.value)} style={inputStyle} />
                        </div>
                    </div>

                    {/* Tabla de líneas */}
                    <div style={{ border: '1px solid var(--border-color)', borderRadius: 10, overflow: 'hidden', marginBottom: 12 }}>
                        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(240px,280px) 1fr 110px 110px 36px', gap: 8, padding: '8px 12px', background: 'rgba(0,0,0,0.1)', fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 700 }}>
                            <span>CUENTA (solo Balance) *</span><span>DESCRIPCIÓN</span>
                            <span style={{ textAlign: 'right' }}>DEBE</span>
                            <span style={{ textAlign: 'right' }}>HABER</span>
                            <span></span>
                        </div>

                        {lines.map((line, i) => (
                            <div key={i} style={{ display: 'grid', gridTemplateColumns: 'minmax(240px,280px) 1fr 110px 110px 36px', gap: 6, padding: '6px 12px', borderTop: '1px solid var(--border-color)', alignItems: 'center', background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.03)' }}>
                                {/* AccountPicker (solo balance) */}
                                <div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, border: `1px solid ${line.account_code ? (TYPE_COLOR[line._type] || 'var(--border-color)') + '80' : 'var(--border-color)'}`, borderRadius: 6, overflow: 'hidden', background: 'var(--bg-card)' }}>
                                        {line._type && (
                                            <span style={{ fontSize: '0.62rem', fontWeight: 700, padding: '0 5px', background: TYPE_COLOR[line._type] + '20', color: TYPE_COLOR[line._type], whiteSpace: 'nowrap', lineHeight: '28px' }}>
                                                {TYPE_ABBREV[line._type]}
                                            </span>
                                        )}
                                        <input
                                            id={`ap-account-${i}`}
                                            ref={el => { if (!inputRefs[i]) inputRefs[i] = {}; inputRefs[i].current = el }}
                                            value={pickers[i]?.open ? (pickers[i]?.query || '') : (line.display_code || line.account_code || '')}
                                            placeholder="Buscar cuenta de balance..."
                                            onFocus={() => openPicker(i)}
                                            onChange={e => setPickers(p => ({ ...p, [i]: { ...p[i], open: true, query: e.target.value, hi: 0 } }))}
                                            onKeyDown={e => {
                                                const { items } = fuzzyBalance(pickers[i]?.query || '')
                                                const hi = pickers[i]?.hi || 0
                                                if (e.key === 'ArrowDown') { e.preventDefault(); setPickers(p => ({ ...p, [i]: { ...p[i], hi: Math.min(hi + 1, items.length - 1) } })) }
                                                if (e.key === 'ArrowUp') { e.preventDefault(); setPickers(p => ({ ...p, [i]: { ...p[i], hi: Math.max(hi - 1, 0) } })) }
                                                if ((e.key === 'Enter' || e.key === 'Tab') && items[hi]) { e.preventDefault(); selectAccount(i, items[hi]) }
                                                if (e.key === 'Escape') closePicker(i)
                                            }}
                                            onBlur={() => setTimeout(() => closePicker(i), 180)}
                                            style={{ flex: 1, border: 'none', background: 'transparent', padding: '5px 6px', fontSize: '0.78rem', fontFamily: 'monospace', color: 'var(--text-primary)', outline: 'none', minWidth: 0 }}
                                        />
                                    </div>
                                </div>

                                {/* Descripción */}
                                <input
                                    value={line._name}
                                    placeholder="Descripción de la cuenta"
                                    onChange={e => { const nl = [...lines]; nl[i] = { ...nl[i], _name: e.target.value }; setLines(nl) }}
                                    style={{ ...inputStyle, fontSize: '0.8rem', padding: '5px 8px' }}
                                />

                                {/* Debe */}
                                <input
                                    id={`ap-debit-${i}`}
                                    type="number" min="0" step="0.01"
                                    value={line.debit}
                                    onChange={e => updateLine(i, 'debit', e.target.value)}
                                    style={{ ...inputStyle, textAlign: 'right', fontSize: '0.82rem', padding: '5px 8px' }}
                                />

                                {/* Haber */}
                                <input
                                    type="number" min="0" step="0.01"
                                    value={line.credit}
                                    onChange={e => updateLine(i, 'credit', e.target.value)}
                                    style={{ ...inputStyle, textAlign: 'right', fontSize: '0.82rem', padding: '5px 8px' }}
                                />

                                {/* Eliminar */}
                                <button
                                    onClick={() => removeLine(i)}
                                    disabled={lines.length <= 2}
                                    style={{ background: 'transparent', border: 'none', color: lines.length <= 2 ? 'transparent' : 'var(--text-muted)', cursor: lines.length <= 2 ? 'default' : 'pointer', fontSize: '1rem' }}
                                >✕</button>
                            </div>
                        ))}
                    </div>

                    {/* Botón agregar línea */}
                    <button onClick={addLine} style={{ padding: '6px 14px', background: 'transparent', border: '1px dashed var(--border-color)', borderRadius: 7, color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.82rem', marginBottom: 16 }}>
                        + Agregar línea de balance
                    </button>

                    {/* Dropdowns position:fixed */}
                    {lines.map((_, i) => {
                        const pk = pickers[i]
                        if (!pk?.open) return null
                        const { items, total } = fuzzyBalance(pk.query || '')
                        return (
                            <div key={`ap-pk-${i}`} style={{ position: 'fixed', top: pk.top || 0, left: pk.left || 0, width: pk.width || 380, zIndex: 9999, background: 'var(--bg-elevated)', border: '1px solid var(--border-color)', borderRadius: 12, boxShadow: '0 16px 56px rgba(0,0,0,0.6)', maxHeight: 280, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                                <div style={{ overflowY: 'auto', flex: 1 }}>
                                    {items.length === 0
                                        ? <div style={{ padding: '14px 16px', fontSize: '0.82rem', color: 'var(--text-muted)', textAlign: 'center' }}>Sin resultados</div>
                                        : items.map((a, idx) => (
                                            <div key={a.code} onMouseDown={() => selectAccount(i, a)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', cursor: 'pointer', background: idx === (pk.hi || 0) ? (TYPE_COLOR[a.account_type] || '#7c3aed') + '1a' : 'transparent', borderBottom: '1px solid var(--border-color)' }}>
                                                <span style={{ fontSize: '0.65rem', fontWeight: 800, padding: '2px 6px', borderRadius: 5, background: (TYPE_COLOR[a.account_type] || '#9ca3af') + '22', color: TYPE_COLOR[a.account_type] || '#9ca3af', flexShrink: 0, minWidth: 32, textAlign: 'center' }}>
                                                    {TYPE_ABBREV[a.account_type] || a.account_type?.slice(0, 3)}
                                                </span>
                                                <span style={{ fontFamily: 'monospace', fontSize: '0.78rem', fontWeight: 700, color: TYPE_COLOR[a.account_type] || '#9ca3af', flexShrink: 0, minWidth: 78 }}>{a.display_code}</span>
                                                <span style={{ fontSize: '0.82rem', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.name}</span>
                                            </div>
                                        ))
                                    }
                                </div>
                                <div style={{ padding: '7px 14px', fontSize: '0.72rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border-color)', background: 'rgba(0,0,0,0.15)', flexShrink: 0 }}>
                                    {total <= 12 ? `${total} cuentas de balance` : `Mostrando 12 de ${total} · Seguí escribiendo`}
                                </div>
                            </div>
                        )
                    })}

                    {/* Balance en tiempo real */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', borderRadius: 8, marginBottom: 16, background: isBalanced ? 'rgba(16,185,129,0.1)' : totalDebit > 0 || totalCredit > 0 ? 'rgba(239,68,68,0.08)' : 'rgba(0,0,0,0.04)', border: `1px solid ${isBalanced ? '#10b981' : totalDebit > 0 || totalCredit > 0 ? '#ef4444' : 'var(--border-color)'}` }}>
                        <div style={{ display: 'flex', gap: 24, fontSize: '0.88rem' }}>
                            <span>Debe: <strong style={{ color: '#3b82f6' }}>₡{totalDebit.toLocaleString('es-CR', { minimumFractionDigits: 2 })}</strong></span>
                            <span>Haber: <strong style={{ color: '#10b981' }}>₡{totalCredit.toLocaleString('es-CR', { minimumFractionDigits: 2 })}</strong></span>
                        </div>
                        <span style={{ fontSize: '0.85rem', fontWeight: 700, color: isBalanced ? '#10b981' : '#ef4444' }}>
                            {isBalanced ? '⚖️ Balanceado' : totalDebit > 0 || totalCredit > 0 ? `⚠️ Diferencia: ₡${Math.abs(totalDebit - totalCredit).toLocaleString('es-CR', { minimumFractionDigits: 2 })}` : '—'}
                        </span>
                    </div>

                    {/* Error */}
                    {formError && (
                        <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '8px 14px', color: '#ef4444', marginBottom: 16, fontSize: '0.85rem' }}>
                            ⚠️ {formError}
                        </div>
                    )}

                    {/* Advertencia perpetuidad */}
                    <div style={{ padding: '10px 14px', background: 'rgba(245,158,11,0.08)', border: '1px solid #f59e0b', borderRadius: 8, fontSize: '0.82rem', color: '#f59e0b', marginBottom: 16 }}>
                        ⚠️ <strong>Este asiento es perpetuo e inmutable.</strong> Una vez aprobado no puede editarse ni eliminarse. Los errores se corrigen con asientos posteriores (NIIF — principio del documento contable).
                    </div>

                    {/* Botón aprobar */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <button
                            id="btn-save-apertura"
                            onClick={handleSave}
                            disabled={!canSave || saving}
                            style={{ padding: '10px 24px', background: canSave ? '#7c3aed' : 'var(--bg-card)', border: 'none', borderRadius: 8, color: canSave ? 'white' : 'var(--text-muted)', fontWeight: 700, cursor: canSave ? 'pointer' : 'not-allowed', fontSize: '0.9rem', transition: 'all 0.15s' }}
                        >
                            {saving ? '⏳ Procesando...' : '📂 Aprobar Apertura del Ejercicio'}
                        </button>
                    </div>
                </>
            )}
        </div>
    )
}
