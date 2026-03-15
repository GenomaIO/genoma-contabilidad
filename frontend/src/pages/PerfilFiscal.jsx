import { useState, useEffect, useCallback } from 'react'
import { useApp } from '../context/AppContext'

const API_BASE = import.meta.env.VITE_API_URL || ''

const MESES = [
    { v: 1, l: 'Enero' }, { v: 2, l: 'Febrero' }, { v: 3, l: 'Marzo' },
    { v: 4, l: 'Abril' }, { v: 5, l: 'Mayo' }, { v: 6, l: 'Junio' },
    { v: 7, l: 'Julio' }, { v: 8, l: 'Agosto' }, { v: 9, l: 'Septiembre' },
    { v: 10, l: 'Octubre' }, { v: 11, l: 'Noviembre' }, { v: 12, l: 'Diciembre' },
]

function authHeaders(token) {
    return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
}

/* ─── Fila editable de un tramo ─── */
function BracketRow({ bracket, index, onChange, onDelete }) {
    return (
        <tr>
            <td style={{ padding: '6px 8px' }}>
                <input
                    type="number" min="0" step="1000"
                    value={bracket.income_from}
                    onChange={e => onChange(index, 'income_from', Number(e.target.value))}
                    style={inputStyle}
                />
            </td>
            <td style={{ padding: '6px 8px' }}>
                <input
                    type="number" min="0" step="1000"
                    placeholder="Sin límite"
                    value={bracket.income_to ?? ''}
                    onChange={e => onChange(index, 'income_to', e.target.value === '' ? null : Number(e.target.value))}
                    style={inputStyle}
                />
            </td>
            <td style={{ padding: '6px 8px' }}>
                <input
                    type="number" min="0" max="100" step="0.5"
                    value={(bracket.rate * 100).toFixed(1)}
                    onChange={e => onChange(index, 'rate', Number(e.target.value) / 100)}
                    style={{ ...inputStyle, width: 70 }}
                />
            </td>
            <td style={{ padding: '6px 8px', textAlign: 'center' }}>
                <button onClick={() => onDelete(index)} style={btnDangerSm}>✕</button>
            </td>
        </tr>
    )
}

/* ─── Panel de tramos para un tipo de contribuyente ─── */
function BracketsPanel({ token, tenantId, fiscalYear, taxpayerType, label }) {
    const [brackets, setBrackets] = useState([])
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [msg, setMsg] = useState(null)

    const load = useCallback(async () => {
        if (!fiscalYear) return
        setLoading(true)
        try {
            const r = await fetch(`${API_BASE}/tax/tax-brackets?year=${fiscalYear}`, { headers: authHeaders(token) })
            const d = await r.json()
            const tp = taxpayerType === 'PJ_GRANDE' ? 'PJ_GRANDE' : taxpayerType
            setBrackets(d.brackets?.[tp] || [])
        } catch { setBrackets([]) }
        setLoading(false)
    }, [fiscalYear, taxpayerType, token])

    useEffect(() => { load() }, [load])

    function handleChange(idx, field, value) {
        setBrackets(prev => prev.map((b, i) => i === idx ? { ...b, [field]: value } : b))
    }
    function handleDelete(idx) {
        setBrackets(prev => prev.filter((_, i) => i !== idx))
    }
    function addRow() {
        const last = brackets[brackets.length - 1]
        setBrackets(prev => [...prev, {
            taxpayer_type: taxpayerType,
            income_from: last?.income_to ?? 0,
            income_to: null,
            rate: 0,
        }])
    }

    async function save() {
        setSaving(true); setMsg(null)
        try {
            const r = await fetch(`${API_BASE}/tax/tax-brackets`, {
                method: 'PUT',
                headers: authHeaders(token),
                body: JSON.stringify({ fiscal_year: fiscalYear, taxpayer_type: taxpayerType, brackets }),
            })
            const d = await r.json()
            setMsg({ ok: r.ok, text: d.message || (r.ok ? 'Guardado ✓' : 'Error al guardar') })
        } catch (e) { setMsg({ ok: false, text: String(e) }) }
        setSaving(false)
    }

    return (
        <div style={{ marginBottom: 24 }}>
            <div style={{ fontWeight: 700, fontSize: '0.9rem', marginBottom: 10, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                {label}
                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 400 }}>
                    ({brackets.length} tramos)
                </span>
            </div>

            {loading ? (
                <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Cargando...</div>
            ) : (
                <>
                    <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                            <thead>
                                <tr style={{ background: 'var(--bg-3)', color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                                    <th style={{ padding: '6px 8px', textAlign: 'left' }}>Desde (₡)</th>
                                    <th style={{ padding: '6px 8px', textAlign: 'left' }}>Hasta (₡)</th>
                                    <th style={{ padding: '6px 8px', textAlign: 'left' }}>Tasa (%)</th>
                                    <th style={{ padding: '6px 8px' }}></th>
                                </tr>
                            </thead>
                            <tbody>
                                {brackets.length === 0 ? (
                                    <tr><td colSpan={4} style={{ padding: 12, color: 'var(--text-muted)', textAlign: 'center', fontSize: '0.83rem' }}>
                                        Sin tramos — agrega uno o usa el pre-llenado 2026
                                    </td></tr>
                                ) : brackets.map((b, i) => (
                                    <BracketRow key={i} bracket={b} index={i} onChange={handleChange} onDelete={handleDelete} />
                                ))}
                            </tbody>
                        </table>
                    </div>

                    <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                        <button onClick={addRow} style={btnSecondary}>＋ Agregar tramo</button>
                        <button onClick={save} disabled={saving} style={btnPrimary}>
                            {saving ? 'Guardando...' : '💾 Guardar tramos'}
                        </button>
                        {msg && (
                            <span style={{
                                fontSize: '0.82rem', color: msg.ok ? 'var(--success)' : 'var(--danger)',
                                padding: '4px 10px', borderRadius: 6,
                                background: msg.ok ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                            }}>
                                {msg.text}
                            </span>
                        )}
                    </div>
                </>
            )}
        </div>
    )
}

/* ─── Página principal ─── */
export default function PerfilFiscal() {
    const { state } = useApp()
    // Misma fuente de token que Dashboard — gc_token en localStorage
    const token = state.token || localStorage.getItem('gc_token')

    // Perfil fiscal
    const [profile, setProfile] = useState({
        taxpayer_type: 'PJ',
        is_large_taxpayer: false,
        fiscal_year_end_month: 9,
        prorrata_iva: 1.0,
    })
    // Iniciar en true: muestra el form de inmediato con defaults mientras la API responde
    const [profileLoaded, setProfileLoaded] = useState(true)
    const [savingProfile, setSavingProfile] = useState(false)
    const [profileMsg, setProfileMsg] = useState(null)
    const [calcProrrata, setCalcProrrata] = useState(null)   // resultado del auto-cálculo
    const [calculando, setCalculando]   = useState(false)

    // Tramos
    const [years, setYears] = useState([])
    const [selectedYear, setSelectedYear] = useState(new Date().getFullYear())
    const [newYear, setNewYear] = useState('')
    const [prefilling, setPrefilling] = useState(false)
    const [prefillMsg, setPrefillMsg] = useState(null)

    // Cargar perfil al montar
    useEffect(() => {
        if (!token) return
        fetch(`${API_BASE}/tax/fiscal-profile`, { headers: authHeaders(token) })
            .then(r => r.json())
            .then(d => {
                if (d.configured) {
                    setProfile({
                        taxpayer_type: d.taxpayer_type || 'PJ',
                        is_large_taxpayer: d.is_large_taxpayer || false,
                        fiscal_year_end_month: d.fiscal_year_end_month || 9,
                        prorrata_iva: d.prorrata_iva ?? 1.0,
                    })
                }
                setProfileLoaded(true)
            })
            .catch(() => setProfileLoaded(true))
    }, [token])

    // Cargar años disponibles
    useEffect(() => {
        if (!token) return
        fetch(`${API_BASE}/tax/tax-brackets/years`, { headers: authHeaders(token) })
            .then(r => r.json())
            .then(d => {
                const yr = d.years || []
                setYears(yr)
                if (yr.length > 0 && !yr.includes(selectedYear)) setSelectedYear(yr[0])
                else if (yr.includes(new Date().getFullYear())) setSelectedYear(new Date().getFullYear())
            })
            .catch(() => { })
    }, [token]) // eslint-disable-line

    async function saveProfile() {
        setSavingProfile(true); setProfileMsg(null)
        try {
            const r = await fetch(`${API_BASE}/tax/fiscal-profile`, {
                method: 'PUT',
                headers: authHeaders(token),
                body: JSON.stringify(profile),
            })
            const d = await r.json()
            setProfileMsg({ ok: r.ok, text: d.message || (r.ok ? 'Perfil guardado ✓' : 'Error') })
        } catch (e) { setProfileMsg({ ok: false, text: String(e) }) }
        setSavingProfile(false)
    }

    async function autoCalcProrrata() {
        setCalculando(true); setCalcProrrata(null)
        try {
            const r = await fetch(`${API_BASE}/tax/prorrata-calc?fiscal_year=${new Date().getFullYear()}`,
                { headers: authHeaders(token) })
            const d = await r.json()
            setCalcProrrata(d)
            if (d.ok && d.origen !== 'ERROR') {
                setProfile(p => ({ ...p, prorrata_iva: d.prorrata }))
            }
        } catch (e) { setCalcProrrata({ ok: false, advertencia: String(e), origen: 'ERROR' }) }
        setCalculando(false)
    }

    async function prefill2026() {
        setPrefilling(true); setPrefillMsg(null)
        try {
            const r = await fetch(`${API_BASE}/tax/tax-brackets/prefill-2026`, {
                method: 'POST', headers: authHeaders(token),
            })
            const d = await r.json()
            setPrefillMsg({ ok: r.ok, text: d.message })
            if (r.ok && !d.were_existing) {
                setYears(prev => prev.includes(2026) ? prev : [...prev, 2026].sort((a, b) => b - a))
                setSelectedYear(2026)
            }
        } catch (e) { setPrefillMsg({ ok: false, text: String(e) }) }
        setPrefilling(false)
    }

    function addYear() {
        const y = parseInt(newYear)
        if (!y || y < 2020 || y > 2040) return
        if (!years.includes(y)) setYears(prev => [...prev, y].sort((a, b) => b - a))
        setSelectedYear(y)
        setNewYear('')
    }

    // Determinar qué panels de tramos mostrar según tipo
    const panels = profile.taxpayer_type === 'PJ'
        ? (profile.is_large_taxpayer
            ? [{ key: 'PJ_GRANDE', label: 'Persona Jurídica — Gran Contribuyente (tasa fija)' }]
            : [{ key: 'PJ', label: 'Persona Jurídica' }])
        : [{ key: 'PF', label: 'Persona Física con Actividad Lucrativa' }]

    return (
        <div style={{ maxWidth: 820, margin: '0 auto', padding: '28px 20px' }}>
            {/* Encabezado */}
            <div style={{ marginBottom: 28 }}>
                <h1 style={{ fontSize: '1.45rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>
                    🧾 Perfil Fiscal
                </h1>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.87rem', marginTop: 6 }}>
                    Configura el tipo de contribuyente y carga los tramos de renta año a año
                    para generar proyecciones de Impuesto sobre la Renta (D-101/D-102).
                </p>
            </div>

            {/* ── Sección 1: Datos de contribuyente ── */}
            <div style={cardStyle}>
                <div style={cardHeader}>📋 Datos del Contribuyente</div>
                <div style={{ padding: '18px 20px' }}>
                    {!profileLoaded ? (
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Cargando perfil...</div>
                    ) : (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 18 }}>
                            {/* Tipo */}
                            <div>
                                <label style={labelStyle}>Tipo de contribuyente</label>
                                <div style={{ display: 'flex', gap: 10 }}>
                                    {['PJ', 'PF'].map(tp => (
                                        <button
                                            key={tp}
                                            onClick={() => setProfile(p => ({ ...p, taxpayer_type: tp, is_large_taxpayer: false }))}
                                            style={{
                                                ...btnChoice,
                                                background: profile.taxpayer_type === tp ? 'var(--accent)' : 'var(--bg-3)',
                                                color: profile.taxpayer_type === tp ? '#fff' : 'var(--text-secondary)',
                                                borderColor: profile.taxpayer_type === tp ? 'var(--accent)' : 'var(--border)',
                                            }}
                                        >
                                            {tp === 'PJ' ? '🏢 Persona Jurídica' : '👤 Persona Física'}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Gran contribuyente (solo PJ) */}
                            {profile.taxpayer_type === 'PJ' && (
                                <div>
                                    <label style={labelStyle}>¿Gran Contribuyente Nacional?</label>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
                                        <input
                                            type="checkbox"
                                            id="large-tp"
                                            checked={profile.is_large_taxpayer}
                                            onChange={e => setProfile(p => ({ ...p, is_large_taxpayer: e.target.checked }))}
                                            style={{ width: 16, height: 16, cursor: 'pointer' }}
                                        />
                                        <label htmlFor="large-tp" style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                                            Sí → aplica tasa fija 30%
                                        </label>
                                    </div>
                                </div>
                            )}

                            {/* Mes de cierre */}
                            <div>
                                <label style={labelStyle}>Mes de cierre fiscal</label>
                                <select
                                    value={profile.fiscal_year_end_month}
                                    onChange={e => setProfile(p => ({ ...p, fiscal_year_end_month: Number(e.target.value) }))}
                                    style={{ ...inputStyle, marginTop: 6 }}
                                >
                                    {MESES.map(m => <option key={m.v} value={m.v}>{m.l}</option>)}
                                </select>
                            </div>

                            {/* ── Prorrata IVA (Art. 31 Ley 9635) ── */}
                            <div style={{ gridColumn: '1 / -1' }}>
                                <label style={labelStyle}>
                                    Prorrata IVA — Art. 31 Ley 9635
                                    <span style={{ marginLeft: 8, fontWeight: 400, textTransform: 'none', letterSpacing: 0, color: 'var(--text-muted)' }}>
                                        (solo empresas con actividad mixta gravada + exenta)
                                    </span>
                                </label>

                                {/* Botón Auto-calcular */}
                                <button
                                    onClick={autoCalcProrrata}
                                    disabled={calculando}
                                    style={{ ...btnAccent, marginBottom: 12, fontSize: '0.8rem', padding: '6px 14px' }}
                                >
                                    {calculando ? '⏳ Calculando...' : '⚡ Auto-calcular desde contabilidad'}
                                </button>

                                {/* Resultado del cálculo automático */}
                                {calcProrrata && (
                                    <div style={{
                                        marginBottom: 10, padding: '10px 14px',
                                        background: calcProrrata.origen === 'LIBRO_DIARIO'
                                            ? 'rgba(34,197,94,0.08)' : 'rgba(245,158,11,0.08)',
                                        border: `1px solid ${calcProrrata.origen === 'LIBRO_DIARIO' ? 'rgba(34,197,94,0.3)' : 'rgba(245,158,11,0.3)'}`,
                                        borderRadius: 8, fontSize: '0.82rem',
                                    }}>
                                        {calcProrrata.origen === 'LIBRO_DIARIO' ? (
                                            <>
                                                <div style={{ fontWeight: 700, color: 'var(--success)', marginBottom: 4 }}>
                                                    ✅ Calculado desde el Libro Diario {calcProrrata.fiscal_year}
                                                </div>
                                                <div style={{ color: 'var(--text-secondary)', display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                                                    <span>Ventas gravadas: <strong>&#8353;{calcProrrata.ventas_gravadas?.toLocaleString('es-CR')}</strong></span>
                                                    <span>Ventas exentas: <strong>&#8353;{calcProrrata.ventas_exentas?.toLocaleString('es-CR')}</strong></span>
                                                    <span style={{ color: 'var(--accent)', fontWeight: 700 }}>
                                                        Prorrata: {calcProrrata.porcentaje}%
                                                    </span>
                                                </div>
                                            </>
                                        ) : (
                                            <div style={{ color: 'var(--warning, #f59e0b)' }}>
                                                ⚠️ {calcProrrata.advertencia}
                                            </div>
                                        )}
                                    </div>
                                )}

                                <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 6, flexWrap: 'wrap' }}>
                                    <input
                                        id="prorrata-slider"
                                        type="range" min="0" max="100" step="0.01"
                                        value={(profile.prorrata_iva * 100).toFixed(2)}
                                        onChange={e => setProfile(p => ({ ...p, prorrata_iva: Number(e.target.value) / 100 }))}
                                        style={{ flex: 1, minWidth: 160, accentColor: 'var(--accent)' }}
                                    />
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                        <input
                                            type="number" min="0" max="100" step="0.01"
                                            value={(profile.prorrata_iva * 100).toFixed(2)}
                                            onChange={e => {
                                                const v = Math.max(0, Math.min(100, Number(e.target.value)))
                                                setProfile(p => ({ ...p, prorrata_iva: v / 100 }))
                                            }}
                                            style={{ ...inputStyle, width: 80, textAlign: 'right' }}
                                        />
                                        <span style={{ color: 'var(--text-muted)', fontSize: '0.9rem', fontWeight: 700 }}>%</span>
                                    </div>
                                </div>
                                {/* Desglose visual del split */}
                                <div style={{
                                    marginTop: 10, padding: '10px 14px',
                                    background: 'var(--bg-3)', borderRadius: 8,
                                    fontSize: '0.82rem', color: 'var(--text-secondary)',
                                    display: 'flex', gap: 24, flexWrap: 'wrap',
                                }}>
                                    <span>
                                        <span style={{ color: 'var(--success)', fontWeight: 700 }}>
                                            DR 1104
                                        </span>{' '}IVA Acreditable → {(profile.prorrata_iva * 100).toFixed(2)}% del IVA
                                    </span>
                                    <span>
                                        <span style={{ color: 'var(--warning, #f59e0b)', fontWeight: 700 }}>
                                            DR 5xxx
                                        </span>{' '}IVA no acreditable → {((1 - profile.prorrata_iva) * 100).toFixed(2)}% del IVA (al gasto)
                                    </span>
                                    {profile.prorrata_iva === 1.0 && (
                                        <span style={{ color: 'var(--text-muted)' }}>
                                            ⚡ Default: 100% acreditable — sin prorrata
                                        </span>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    <div style={{ marginTop: 18, display: 'flex', alignItems: 'center', gap: 10 }}>
                        <button onClick={saveProfile} disabled={savingProfile || !profileLoaded} style={btnPrimary}>
                            {savingProfile ? 'Guardando...' : '💾 Guardar perfil'}
                        </button>
                        {profileMsg && (
                            <span style={{ fontSize: '0.82rem', color: profileMsg.ok ? 'var(--success)' : 'var(--danger)' }}>
                                {profileMsg.text}
                            </span>
                        )}
                    </div>
                </div>
            </div>

            {/* ── Sección 2: Tramos de Renta ── */}
            <div style={{ ...cardStyle, marginTop: 20 }}>
                <div style={cardHeader}>📊 Tramos de Renta por Año Fiscal</div>
                <div style={{ padding: '18px 20px' }}>
                    <p style={{ fontSize: '0.83rem', color: 'var(--text-muted)', marginTop: 0, marginBottom: 14 }}>
                        Carga los tramos oficiales de cada año según el Decreto que publique Hacienda.
                        Estos datos los ingresás vos directamente — sin depender de actualizaciones del sistema.
                    </p>

                    {/* Selector de año + botón agregar */}
                    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 20 }}>
                        {years.length > 0 && (
                            <div style={{ display: 'flex', gap: 6 }}>
                                {years.map(y => (
                                    <button
                                        key={y}
                                        onClick={() => setSelectedYear(y)}
                                        style={{
                                            ...btnChoice,
                                            background: selectedYear === y ? 'var(--accent)' : 'var(--bg-3)',
                                            color: selectedYear === y ? '#fff' : 'var(--text-secondary)',
                                            borderColor: selectedYear === y ? 'var(--accent)' : 'var(--border)',
                                            padding: '5px 14px',
                                        }}
                                    >
                                        {y}
                                    </button>
                                ))}
                            </div>
                        )}

                        {/* Agregar año nuevo */}
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                            <input
                                type="number" placeholder="Ej: 2027"
                                value={newYear}
                                onChange={e => setNewYear(e.target.value)}
                                style={{ ...inputStyle, width: 90 }}
                                onKeyDown={e => e.key === 'Enter' && addYear()}
                            />
                            <button onClick={addYear} style={btnSecondary}>＋ Año</button>
                        </div>

                        {/* Pre-llenar 2026 */}
                        {!years.includes(2026) && (
                            <button onClick={prefill2026} disabled={prefilling} style={btnAccent}>
                                {prefilling ? 'Cargando...' : '⚡ Pre-llenar datos 2026 oficiales'}
                            </button>
                        )}

                        {prefillMsg && (
                            <span style={{ fontSize: '0.82rem', color: prefillMsg.ok ? 'var(--success)' : 'var(--danger)' }}>
                                {prefillMsg.text}
                            </span>
                        )}
                    </div>

                    {/* Panels de tramos */}
                    {years.length === 0 ? (
                        <div style={{
                            textAlign: 'center', padding: '28px 20px',
                            color: 'var(--text-muted)', fontSize: '0.87rem',
                            border: '1px dashed var(--border)', borderRadius: 10,
                        }}>
                            <div style={{ fontSize: '2rem', marginBottom: 8 }}>📅</div>
                            <div>No hay años configurados.</div>
                            <div style={{ marginTop: 6 }}>Agrega el año 2026 con el botón de pre-llenado oficial, o ingresa cualquier año manualmente.</div>
                        </div>
                    ) : (
                        panels.map(p => (
                            <BracketsPanel
                                key={`${selectedYear}-${p.key}`}
                                token={token}
                                fiscalYear={selectedYear}
                                taxpayerType={p.key}
                                label={`${p.label} — ${selectedYear}`}
                            />
                        ))
                    )}
                </div>
            </div>
        </div>
    )
}

/* ─── Estilos locales ─── */
const inputStyle = {
    background: 'var(--bg-3)',
    border: '1px solid var(--border)',
    borderRadius: 7,
    padding: '6px 10px',
    color: 'var(--text-primary)',
    fontSize: '0.85rem',
    outline: 'none',
    width: '100%',
    boxSizing: 'border-box',
}
const labelStyle = {
    display: 'block',
    fontSize: '0.78rem',
    fontWeight: 600,
    color: 'var(--text-muted)',
    marginBottom: 6,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
}
const btnPrimary = {
    background: 'var(--accent)',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    padding: '8px 18px',
    fontSize: '0.85rem',
    fontWeight: 600,
    cursor: 'pointer',
}
const btnSecondary = {
    background: 'var(--bg-3)',
    color: 'var(--text-secondary)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    padding: '7px 14px',
    fontSize: '0.83rem',
    fontWeight: 600,
    cursor: 'pointer',
}
const btnAccent = {
    background: 'linear-gradient(135deg, #f59e0b, #d97706)',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    padding: '7px 16px',
    fontSize: '0.83rem',
    fontWeight: 700,
    cursor: 'pointer',
}
const btnDangerSm = {
    background: 'rgba(239,68,68,0.15)',
    color: 'var(--danger)',
    border: '1px solid rgba(239,68,68,0.3)',
    borderRadius: 6,
    padding: '3px 8px',
    fontSize: '0.78rem',
    cursor: 'pointer',
}
const btnChoice = {
    border: '1px solid var(--border)',
    borderRadius: 8,
    padding: '7px 14px',
    fontSize: '0.83rem',
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'all 0.15s ease',
}
const cardStyle = {
    background: 'var(--bg-card)',
    border: '1px solid var(--border-color)',
    borderRadius: 14,
    overflow: 'hidden',
}
const cardHeader = {
    padding: '12px 20px',
    borderBottom: '1px solid var(--border-color)',
    fontSize: '0.88rem',
    fontWeight: 700,
    color: 'var(--text-secondary)',
    background: 'var(--bg-secondary)',
}
