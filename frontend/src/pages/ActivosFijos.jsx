import { useState, useCallback, useEffect } from 'react'
import { useApp } from '../context/AppContext'

// ─── Helpers ─────────────────────────────────────────────────────
const fmt = (n) => {
    if (n == null || n === '') return '—'
    return new Intl.NumberFormat('es-CR', { style: 'currency', currency: 'CRC', minimumFractionDigits: 2 }).format(n)
}

// Tasas fiscales CR — Decreto 18455-H, Art. 24 Ley 7092
const TASAS_CR = [
    { categoria: 'VEHICULO', label: '🚗 Vehículos', tasa: 10, vida: 10 },
    { categoria: 'EQUIPO', label: '⚙️ Maquinaria y equipo', tasa: 10, vida: 10 },
    { categoria: 'INMUEBLE', label: '🏢 Edificios / Inmuebles', tasa: 2.5, vida: 40 },
    { categoria: 'MOBILIARIO', label: '🪑 Muebles y enseres', tasa: 10, vida: 10 },
    { categoria: 'INTANGIBLE', label: '💡 Intangibles', tasa: 10, vida: 10 },
    { categoria: 'OTRO', label: '📦 Instalaciones / Otro', tasa: 10, vida: 10 },
]
const TASA_BY_CAT = Object.fromEntries(TASAS_CR.map(t => [t.categoria, t.tasa]))

// Sugerencias de cuentas contables por categoría (catálogo estándar CR)
// Códigos en formato NO-DOTTED (como la BD los almacena: 1202.03, 5210.03)
// El display dotted (1.2.2.03, 5.2.10.03) es solo visual en el Libro Mayor
const CUENTAS_DEP_BY_CAT = {
    VEHICULO: { dep_acum: '1202.03', dep_gasto: '5210.03' }, // Vehículos y Medios de Transporte
    EQUIPO: { dep_acum: '1202.02', dep_gasto: '5210.02' }, // Maquinaria y Equipo Industrial
    INMUEBLE: { dep_acum: '1202.01', dep_gasto: '5210.01' }, // Edificios y Construcciones
    MOBILIARIO: { dep_acum: '1202.04', dep_gasto: '5210.04' }, // Mobiliario y Equipo de Oficina
    INTANGIBLE: { dep_acum: '', dep_gasto: '' },         // sin mapeo estándar
    OTRO: { dep_acum: '', dep_gasto: '' },
}

const METODOS = [
    { value: 'LINEA_RECTA', label: 'Línea Recta (NIIF)' },
    { value: 'SALDO_DECRECIENTE', label: 'Saldo Decreciente' },
    { value: 'UNIDADES_PRODUCCION', label: 'Unidades de Producción' },
]
const CATEGORIAS = [
    { value: 'INMUEBLE', label: '🏢 Inmueble / Terreno' },
    { value: 'VEHICULO', label: '🚗 Vehículo' },
    { value: 'EQUIPO', label: '⚙️ Equipo y Maquinaria' },
    { value: 'MOBILIARIO', label: '🪑 Mobiliario y Equipo Oficina' },
    { value: 'INTANGIBLE', label: '💡 Intangible' },
    { value: 'OTRO', label: '📦 Otro' },
]
const ESTADO_COLOR = { ACTIVO: '#10b981', BAJA: '#ef4444', VENDIDO: '#f59e0b' }

const EMPTY = {
    categoria: 'VEHICULO', nombre: '', descripcion: '',
    numero_serie: '', ubicacion: '', proveedor: '', numero_factura: '',
    account_code: '', dep_acum_code: '', dep_gasto_code: '',
    fecha_adquisicion: '', fecha_disponible: '',
    costo_historico: '', valor_residual: '0',
    // Modo Tasa Fiscal (default)
    tasa_anual: '10',
    dep_acum_apertura: '0',
    // Modo NIIF Detallado
    vida_util_meses: '',
    meses_usados_apertura: '0',
    metodo_depreciacion: 'LINEA_RECTA',
    apertura_line_id: null,
    modo: 'TASA',   // 'TASA' | 'NIIF'
}

// ─── Tooltip con tasas fiscales CR ────────────────────────────────
function TasasCRTooltip() {
    return (
        <div style={{ position: 'relative', display: 'inline-block' }}
            onMouseEnter={e => e.currentTarget.querySelector('.tasas-guide').style.display = 'block'}
            onMouseLeave={e => e.currentTarget.querySelector('.tasas-guide').style.display = 'none'}
        >
            <button id="btn-tasas-cr" style={{
                background: 'transparent', border: '1px solid var(--border-color)',
                borderRadius: 20, padding: '4px 10px', cursor: 'pointer',
                color: 'var(--text-secondary)', fontSize: '0.78rem',
                display: 'flex', alignItems: 'center', gap: 5,
            }}>📋 Tasas CR</button>

            <div className="tasas-guide" style={{
                display: 'none', position: 'absolute', left: 0, top: '110%', zIndex: 999,
                background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                borderRadius: 10, padding: '14px 16px', width: 420,
                boxShadow: '0 8px 24px rgba(0,0,0,0.4)', fontSize: '0.78rem',
            }}>
                <p style={{ margin: '0 0 6px', fontWeight: 700, color: 'var(--text-primary)', fontSize: '0.85rem' }}>
                    📋 Tasas Fiscales CR
                </p>
                <p style={{ margin: '0 0 10px', color: 'var(--text-muted)', fontSize: '0.73rem', lineHeight: 1.5 }}>
                    Decreto 18455-H · Art. 24, Ley 7092 (Ley de Renta)
                </p>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                            <th style={{ textAlign: 'left', padding: '3px 6px', color: 'var(--text-muted)', fontWeight: 600 }}>Categoría</th>
                            <th style={{ textAlign: 'right', padding: '3px 6px', color: 'var(--text-muted)', fontWeight: 600 }}>Tasa máx.</th>
                            <th style={{ textAlign: 'right', padding: '3px 6px', color: 'var(--text-muted)', fontWeight: 600 }}>Vida útil</th>
                        </tr>
                    </thead>
                    <tbody>
                        {[
                            ['🚗 Vehículos', '10%', '10 años'],
                            ['⚙️ Maquinaria y equipo', '10%', '10 años'],
                            ['🏢 Edificios / Inmuebles', '2.5%', '40 años'],
                            ['🔧 Instalaciones', '10%', '10 años'],
                            ['🏍️ Motos / Herramientas', '50%', '2 años'],
                            ['💻 Equipo de cómputo', '50%', '2 años'],
                            ['🪑 Muebles y enseres', '10%', '10 años'],
                            ['💡 Intangibles', '10-20%', '5-10 años'],
                        ].map(([cat, tasa, vida]) => (
                            <tr key={cat} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                                <td style={{ padding: '4px 6px', color: 'var(--text-primary)' }}>{cat}</td>
                                <td style={{ padding: '4px 6px', color: '#10b981', fontWeight: 700, textAlign: 'right', fontFamily: 'monospace' }}>{tasa}</td>
                                <td style={{ padding: '4px 6px', color: 'var(--text-muted)', textAlign: 'right' }}>{vida}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                <p style={{ margin: '10px 0 0', fontSize: '0.7rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                    ℹ️ NIIF puede usar tasas distintas si hay un estudio técnico del activo.
                    Motos/Herr. y Cómputo al 50% = método acelerado Hacienda.
                </p>
            </div>
        </div>
    )
}

export default function ActivosFijos() {
    const { state } = useApp()
    const apiUrl = import.meta.env.VITE_API_URL || ''
    const token = localStorage.getItem('gc_token')

    const [assets, setAssets] = useState([])
    const [loading, setLoading] = useState(false)
    const [aperturaData, setAperturaData] = useState(null)
    const [aperturaLoading, setAperturaLoading] = useState(false)

    const [showForm, setShowForm] = useState(false)
    const [form, setForm] = useState(EMPTY)
    const [saving, setSaving] = useState(false)
    const [formErr, setFormErr] = useState(null)

    const [depPeriod, setDepPeriod] = useState(() => new Date().toISOString().slice(0, 7))
    const [depLoading, setDepLoading] = useState(null)

    // ── Cargar activos ────────────────────────────────────────────
    const loadAssets = useCallback(async () => {
        if (!token) return
        setLoading(true)
        try {
            const r = await fetch(`${apiUrl}/api/assets`, { headers: { Authorization: `Bearer ${token}` } })
            if (r.ok) setAssets((await r.json()).assets || [])
        } finally { setLoading(false) }
    }, [apiUrl, token])

    // ── Detectar desde apertura ───────────────────────────────────
    const loadFromApertura = useCallback(async () => {
        if (!token || aperturaData) return
        setAperturaLoading(true)
        try {
            const r = await fetch(`${apiUrl}/api/assets/from-apertura`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (r.ok) setAperturaData(await r.json())
        } finally { setAperturaLoading(false) }
    }, [apiUrl, token, aperturaData])

    useEffect(() => { loadAssets(); loadFromApertura() }, []) // eslint-disable-line

    // ── Preview cuota mensual en tiempo real ──────────────────────
    const cuotaPreview = () => {
        const ch = parseFloat(form.costo_historico) || 0
        if (!ch) return null
        if (form.modo === 'TASA') {
            const tasa = parseFloat(form.tasa_anual) || 0
            if (!tasa) return null
            return { cuota: ch * tasa / 100 / 12, vidaUtil: Math.round(12 * 100 / tasa), meses: null, constante: true }
        } else {
            const vr = parseFloat(form.valor_residual) || 0
            const daa = parseFloat(form.dep_acum_apertura) || 0
            const vu = parseInt(form.vida_util_meses) || 0
            const mu = parseInt(form.meses_usados_apertura) || 0
            if (!vu) return null
            const base = Math.max((ch - vr) - daa, 0)
            const meses = Math.max(vu - mu, 0)
            if (!meses) return null
            return { cuota: base / meses, vidaUtil: vu, meses, constante: false }
        }
    }

    // ── Cambiar categoría → auto-fill tasa + sugerir cuentas ─────────
    const handleCategoriaChange = (cat) => {
        const tasa = TASA_BY_CAT[cat] ?? 10
        const cuentas = CUENTAS_DEP_BY_CAT[cat] || { dep_acum: '', dep_gasto: '' }
        setForm(f => ({
            ...f,
            categoria: cat,
            tasa_anual: String(tasa),
            // Solo sugerir si el campo aún no fue editado manualmente
            dep_acum_code: f.dep_acum_code || cuentas.dep_acum,
            dep_gasto_code: f.dep_gasto_code || cuentas.dep_gasto,
        }))
    }

    // ── Pre-llenar desde apertura ─────────────────────────────────
    const prefillFromLine = (line) => {
        // Inferir categoría desde el account_code de la apertura
        const catMap = { '1201.01': 'INMUEBLE', '1201.02': 'EQUIPO', '1201.03': 'MOBILIARIO', '1201.04': 'VEHICULO' }
        const cat = catMap[line.account_code] || 'VEHICULO'
        const cuentas = CUENTAS_DEP_BY_CAT[cat] || {}
        setForm({
            ...EMPTY,
            categoria: cat,
            account_code: line.account_code,
            // Para dep_acum: usar suggested_dep_acum del backend si existe, si no, sugerir por categoría
            dep_acum_code: line.suggested_dep_acum || cuentas.dep_acum || '',
            // Para dep_gasto: usar sugerencia por categoría (NO hardcode 5301.01)
            dep_gasto_code: cuentas.dep_gasto || '',
            costo_historico: String(line.debit || ''),
            apertura_line_id: line.line_id,
            fecha_adquisicion: line.entry_date?.slice(0, 10) || '',
            fecha_disponible: line.entry_date?.slice(0, 10) || '',
            tasa_anual: String(TASA_BY_CAT[cat] ?? 10),
            modo: 'TASA',
        })
        setShowForm(true)
    }

    // ── Guardar activo ────────────────────────────────────────────
    const saveAsset = async () => {
        setFormErr(null)
        setSaving(true)
        try {
            const body = {
                categoria: form.categoria,
                nombre: form.nombre,
                descripcion: form.descripcion || null,
                numero_serie: form.numero_serie || null,
                ubicacion: form.ubicacion || null,
                proveedor: form.proveedor || null,
                numero_factura: form.numero_factura || null,
                account_code: form.account_code,
                dep_acum_code: form.dep_acum_code,
                dep_gasto_code: form.dep_gasto_code,
                fecha_adquisicion: form.fecha_adquisicion,
                fecha_disponible: form.fecha_disponible,
                costo_historico: parseFloat(form.costo_historico),
                valor_residual: parseFloat(form.valor_residual) || 0,
                metodo_depreciacion: form.metodo_depreciacion,
                dep_acum_apertura: parseFloat(form.dep_acum_apertura) || 0,
                apertura_line_id: form.apertura_line_id || null,
                // Modo-específico:
                ...(form.modo === 'TASA'
                    ? { tasa_anual: parseFloat(form.tasa_anual) }
                    : { vida_util_meses: parseInt(form.vida_util_meses), meses_usados_apertura: parseInt(form.meses_usados_apertura) || 0 }
                )
            }
            const r = await fetch(`${apiUrl}/api/assets`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            })
            const data = await r.json()
            if (!r.ok) { setFormErr(data.detail || 'Error guardando activo'); return }
            setShowForm(false); setForm(EMPTY); setAperturaData(null)
            await loadAssets(); await loadFromApertura()
        } finally { setSaving(false) }
    }

    // ── Depreciar ─────────────────────────────────────────────────
    const depreciate = async (assetId) => {
        setDepLoading(assetId)
        try {
            const r = await fetch(`${apiUrl}/api/assets/${assetId}/depreciate?period=${depPeriod}`, {
                method: 'POST', headers: { Authorization: `Bearer ${token}` }
            })
            const data = await r.json()
            if (!r.ok) alert(data.detail || 'Error')
            else alert(`✅ Asiento DRAFT generado — ${fmt(data.cuota)} para ${data.period}\nRevisa y aprueba en el Diario.`)
        } finally { setDepLoading(null) }
    }

    const pendingApertura = aperturaData?.costo_lines?.filter(l => !l.already_registered) || []
    const preview = cuotaPreview()

    // ─── Render ───────────────────────────────────────────────────
    return (
        <div style={{ padding: '24px 28px', maxWidth: 1100, margin: '0 auto' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                <div>
                    <h1 style={{ fontSize: '1.4rem', fontWeight: 700, margin: 0 }}>🏗️ Activos Fijos</h1>
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 3 }}>NIIF PYMES Sección 17 · Decreto 18455-H</p>
                </div>
                <button onClick={() => { setShowForm(true); setForm(EMPTY) }}
                    style={{ background: '#7c3aed', color: '#fff', border: 'none', borderRadius: 8, padding: '9px 18px', fontWeight: 600, cursor: 'pointer', fontSize: '0.87rem' }}>
                    + Nuevo Activo
                </button>
            </div>

            {/* Banner Mass-Add */}
            {aperturaLoading && <div style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 10, padding: '12px 16px', fontSize: '0.82rem', color: '#fbbf24', marginBottom: 16 }}>⏳ Buscando cuentas de activos en tu apertura...</div>}
            {pendingApertura.length > 0 && (
                <div style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.4)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
                    <div style={{ fontWeight: 700, color: '#fbbf24', fontSize: '0.85rem', marginBottom: 10 }}>⚡ {pendingApertura.length} cuenta(s) de activos detectadas en tu apertura</div>
                    {pendingApertura.map(line => (
                        <div key={line.line_id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                            <span style={{ fontFamily: 'monospace', fontSize: '0.82rem', color: 'var(--primary)', fontWeight: 700, minWidth: 80 }}>{line.account_code}</span>
                            <span style={{ fontSize: '0.82rem', flex: 1 }}>{line.description || 'Sin descripción'}</span>
                            <span style={{ fontFamily: 'monospace', fontSize: '0.82rem', fontWeight: 700, color: '#10b981' }}>{fmt(line.debit)}</span>
                            <button onClick={() => prefillFromLine(line)} style={{ background: '#fbbf24', color: '#000', border: 'none', borderRadius: 6, padding: '5px 12px', fontWeight: 700, cursor: 'pointer', fontSize: '0.75rem' }}>Registrar ▶</button>
                        </div>
                    ))}
                    {aperturaData?.dep_acum_lines?.length > 0 && (
                        <div style={{ marginTop: 10, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            Dep. acumulada: {aperturaData.dep_acum_lines.map(l => `${l.account_code} (${fmt(l.credit)})`).join(' · ')}
                        </div>
                    )}
                </div>
            )}

            {/* Lista de activos */}
            {loading && <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>⏳ Cargando activos...</div>}
            {!loading && assets.length === 0 && !showForm && (
                <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)' }}>
                    <div style={{ fontSize: '3rem', marginBottom: 12 }}>🏗️</div>
                    <p>No hay activos registrados · Registra uno o importa desde la apertura</p>
                </div>
            )}
            {assets.length > 0 && !showForm && (
                <div>
                    <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Período depreciación:</span>
                        <input type="month" value={depPeriod} onChange={e => setDepPeriod(e.target.value)}
                            style={{ border: '1px solid var(--border-color)', borderRadius: 6, padding: '4px 8px', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.82rem' }} />
                    </div>
                    <div style={{ display: 'grid', gap: 12 }}>
                        {assets.map(a => (
                            <div key={a.id} style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: 12, alignItems: 'center' }}>
                                <div>
                                    <div style={{ fontWeight: 700 }}>{a.nombre}</div>
                                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>
                                        <span style={{ fontFamily: 'monospace' }}>{a.account_code}</span>
                                        {a.tasa_anual && <span style={{ marginLeft: 8, color: '#fbbf24' }}>Tasa fiscal: {a.tasa_anual}%</span>}
                                    </div>
                                    {a.numero_serie && <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>#{a.numero_serie}</div>}
                                </div>
                                <div>
                                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 2 }}>Costo Histórico</div>
                                    <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '0.85rem' }}>{fmt(a.costo_historico)}</div>
                                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Neto: {fmt(a.valor_neto_contable)}</div>
                                </div>
                                <div>
                                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 2 }}>
                                        Cuota Mensual {a.tasa_anual ? '(constante)' : '(saldo)'}
                                    </div>
                                    <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '0.85rem', color: '#10b981' }}>{fmt(a.cuota_mensual)}</div>
                                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{a.meses_restantes} meses restantes</div>
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end' }}>
                                    <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '2px 8px', borderRadius: 20, background: `${ESTADO_COLOR[a.estado]}25`, color: ESTADO_COLOR[a.estado] }}>{a.estado}</span>
                                    {a.estado === 'ACTIVO' && a.cuota_mensual > 0 && (
                                        <button disabled={depLoading === a.id} onClick={() => depreciate(a.id)}
                                            style={{ background: '#7c3aed', color: '#fff', border: 'none', borderRadius: 6, padding: '5px 12px', fontSize: '0.73rem', fontWeight: 600, cursor: 'pointer', opacity: depLoading === a.id ? 0.6 : 1 }}>
                                            {depLoading === a.id ? '...' : '📐 Depreciar'}
                                        </button>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Formulario de registro */}
            {showForm && (
                <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 14, padding: 24 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                        <h2 style={{ fontSize: '1rem', fontWeight: 700, margin: 0 }}>📝 Registrar Activo Fijo</h2>
                        <button onClick={() => { setShowForm(false); setFormErr(null) }} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.2rem' }}>✕</button>
                    </div>

                    {formErr && <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid #ef4444', borderRadius: 8, padding: '10px 14px', color: '#ef4444', fontSize: '0.82rem', marginBottom: 16 }}>{formErr}</div>}

                    {/* Toggle modo */}
                    <div style={{ display: 'flex', gap: 8, marginBottom: 20, background: 'rgba(255,255,255,0.04)', borderRadius: 10, padding: 4 }}>
                        {[['TASA', '📋 Modo Tasa Fiscal', 'Recomendado para empresas migradas'],
                        ['NIIF', '📐 Modo NIIF Detallado', 'Activos nuevos o con estudio técnico']
                        ].map(([val, label, sub]) => (
                            <button key={val} onClick={() => setForm(f => ({ ...f, modo: val }))}
                                style={{
                                    flex: 1, padding: '10px 12px', border: 'none', borderRadius: 8, cursor: 'pointer',
                                    background: form.modo === val ? 'var(--primary)' : 'transparent',
                                    color: form.modo === val ? '#fff' : 'var(--text-muted)',
                                    fontWeight: form.modo === val ? 700 : 400,
                                    transition: 'all 0.15s',
                                    textAlign: 'left',
                                }}>
                                <div style={{ fontSize: '0.82rem' }}>{label}</div>
                                <div style={{ fontSize: '0.68rem', opacity: 0.8, marginTop: 2 }}>{sub}</div>
                            </button>
                        ))}
                    </div>

                    {/* Info general */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                        <div>
                            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Categoría *</label>
                            <select value={form.categoria} onChange={e => handleCategoriaChange(e.target.value)}
                                style={{ width: '100%', padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem' }}>
                                {CATEGORIAS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                            </select>
                        </div>
                        <div>
                            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Nombre del activo *</label>
                            <input value={form.nombre} onChange={e => setForm(f => ({ ...f, nombre: e.target.value }))} placeholder="Toyota Hilux 2024"
                                style={{ width: '100%', padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                        </div>
                        <div>
                            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Número de serie / placa</label>
                            <input value={form.numero_serie} onChange={e => setForm(f => ({ ...f, numero_serie: e.target.value }))} placeholder="ABC-123"
                                style={{ width: '100%', padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                        </div>
                        <div>
                            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Proveedor</label>
                            <input value={form.proveedor} onChange={e => setForm(f => ({ ...f, proveedor: e.target.value }))} placeholder="Toyota de Costa Rica S.A."
                                style={{ width: '100%', padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                        </div>
                    </div>

                    {/* Cuentas GL */}
                    <div style={{ marginTop: 16, background: 'rgba(99,102,241,0.06)', borderRadius: 10, padding: 14 }}>
                        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10, letterSpacing: '0.05em' }}>MAPEO CONTABLE (3 cuentas requeridas)</div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                            {[
                                { field: 'account_code', label: 'Cuenta Costo *', ph: '1.2.1.04 (ej. Vehículos)' },
                                { field: 'dep_acum_code', label: 'Dep. Acumulada ⚠️ *', ph: '1.2.X.XX — verificar catálogo' },
                                { field: 'dep_gasto_code', label: 'Gasto Depreciación ⚠️ *', ph: '5.2.X.XX — verificar catálogo' },
                            ].map(({ field, label, ph }) => (
                                <div key={field}>
                                    <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>{label}</label>
                                    <input value={form[field]} onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))} placeholder={ph}
                                        style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Fechas y costo */}
                    <div style={{ marginTop: 16, background: 'rgba(16,185,129,0.06)', borderRadius: 10, padding: 14 }}>
                        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10, letterSpacing: '0.05em' }}>VALORACIÓN NIIF PYMES SEC. 17</div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Fecha adquisición *</label>
                                <input type="date" value={form.fecha_adquisicion} onChange={e => setForm(f => ({ ...f, fecha_adquisicion: e.target.value }))}
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Fecha disponible para uso * <span style={{ color: '#fbbf24' }}>← dep. inicia aquí (NIIF)</span></label>
                                <input type="date" value={form.fecha_disponible} onChange={e => setForm(f => ({ ...f, fecha_disponible: e.target.value }))}
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Costo histórico (₡) *</label>
                                <input type="number" value={form.costo_historico} onChange={e => setForm(f => ({ ...f, costo_historico: e.target.value }))} placeholder="13555935"
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Valor residual (₡)</label>
                                <input type="number" value={form.valor_residual} onChange={e => setForm(f => ({ ...f, valor_residual: e.target.value }))} placeholder="0"
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                        </div>
                    </div>

                    {/* Modo Tasa Fiscal */}
                    {form.modo === 'TASA' && (
                        <div style={{ marginTop: 16, background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.2)', borderRadius: 10, padding: 14 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                                <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#fbbf24', letterSpacing: '0.05em' }}>MODO TASA FISCAL — DECRETO 18455-H</div>
                                <TasasCRTooltip />
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                                <div>
                                    <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Tasa anual de depreciación (%) *</label>
                                    <input type="number" step="0.5" value={form.tasa_anual}
                                        onChange={e => setForm(f => ({ ...f, tasa_anual: e.target.value }))}
                                        placeholder="10"
                                        style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                                    <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 4 }}>
                                        Pre-llena según categoría · Hover en "📋 Tasas CR" para la tabla completa
                                    </div>
                                </div>
                                <div>
                                    <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Dep. acumulada al inicio (₡)</label>
                                    <input type="number" value={form.dep_acum_apertura}
                                        onChange={e => setForm(f => ({ ...f, dep_acum_apertura: e.target.value }))}
                                        placeholder="4424872.13"
                                        style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                                    <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 4 }}>
                                        Del asiento de apertura — el sistema infiere meses usados automáticamente
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Modo NIIF Detallado */}
                    {form.modo === 'NIIF' && (
                        <div style={{ marginTop: 16, background: 'rgba(99,102,241,0.06)', borderRadius: 10, padding: 14 }}>
                            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: 12, letterSpacing: '0.05em' }}>MODO NIIF DETALLADO — ESTUDIO TÉCNICO</div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                                <div>
                                    <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Vida útil total (meses) *</label>
                                    <input type="number" value={form.vida_util_meses}
                                        onChange={e => setForm(f => ({ ...f, vida_util_meses: e.target.value }))} placeholder="60"
                                        style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                                </div>
                                <div>
                                    <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Meses ya depreciados al inicio</label>
                                    <input type="number" value={form.meses_usados_apertura}
                                        onChange={e => setForm(f => ({ ...f, meses_usados_apertura: e.target.value }))} placeholder="20"
                                        style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                                </div>
                                <div>
                                    <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Dep. acumulada al inicio (₡)</label>
                                    <input type="number" value={form.dep_acum_apertura}
                                        onChange={e => setForm(f => ({ ...f, dep_acum_apertura: e.target.value }))} placeholder="0"
                                        style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Preview cuota */}
                    {preview && (
                        <div style={{ marginTop: 16, background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.3)', borderRadius: 10, padding: '12px 16px', display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
                            <div>
                                <div style={{ fontSize: '0.7rem', color: '#10b981', fontWeight: 700, letterSpacing: '0.05em' }}>
                                    CUOTA MENSUAL {preview.constante ? '(CONSTANTE — tasa fiscal)' : '(saldo residual)'}
                                </div>
                                <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#10b981', fontFamily: 'monospace' }}>{fmt(preview.cuota)}</div>
                            </div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.7 }}>
                                {preview.constante ? (
                                    <>
                                        Vida útil fiscal: {preview.vidaUtil} meses ({Math.round(preview.vidaUtil / 12)} años)<br />
                                        Cuota no varía — misma durante toda la vida útil
                                    </>
                                ) : (
                                    <>
                                        {preview.meses} meses restantes<br />
                                        Total a depreciar: {fmt(preview.cuota * preview.meses)}
                                    </>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Botones */}
                    <div style={{ display: 'flex', gap: 10, marginTop: 20, justifyContent: 'flex-end' }}>
                        <button onClick={() => { setShowForm(false); setFormErr(null) }}
                            style={{ padding: '9px 18px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.85rem' }}>
                            Cancelar
                        </button>
                        <button onClick={saveAsset} disabled={saving}
                            style={{ padding: '9px 22px', borderRadius: 7, border: 'none', background: '#7c3aed', color: '#fff', fontWeight: 700, cursor: 'pointer', fontSize: '0.85rem', opacity: saving ? 0.7 : 1 }}>
                            {saving ? 'Guardando...' : '✅ Registrar Activo'}
                        </button>
                    </div>
                </div>
            )}
        </div>
    )
}
