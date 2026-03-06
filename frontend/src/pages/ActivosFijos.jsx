import { useState, useCallback, useEffect } from 'react'
import { useApp } from '../context/AppContext'

// ─── Helpers ─────────────────────────────────────────────────────
const fmt = (n) => {
    if (n == null || n === '') return '—'
    return new Intl.NumberFormat('es-CR', { style: 'currency', currency: 'CRC', minimumFractionDigits: 2 }).format(n)
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

// ─── Empty Form ────────────────────────────────────────────────────
const EMPTY = {
    categoria: 'VEHICULO', nombre: '', descripcion: '',
    numero_serie: '', ubicacion: '', proveedor: '', numero_factura: '',
    account_code: '', dep_acum_code: '', dep_gasto_code: '',
    fecha_adquisicion: '', fecha_disponible: '',
    costo_historico: '', valor_residual: '0',
    vida_util_meses: '', metodo_depreciacion: 'LINEA_RECTA',
    dep_acum_apertura: '0', meses_usados_apertura: '0',
    apertura_line_id: null,
}

export default function ActivosFijos() {
    const { state } = useApp()
    const { apiUrl, token } = state

    const [assets, setAssets] = useState([])
    const [loading, setLoading] = useState(false)
    const [aperturaData, setAperturaData] = useState(null)
    const [aperturaLoading, setAperturaLoading] = useState(false)

    const [showForm, setShowForm] = useState(false)
    const [form, setForm] = useState(EMPTY)
    const [saving, setSaving] = useState(false)
    const [formErr, setFormErr] = useState(null)

    const [depPeriod, setDepPeriod] = useState(() => new Date().toISOString().slice(0, 7))
    const [depLoading, setDepLoading] = useState(null) // asset id en proceso

    // ── Cargar activos ────────────────────────────────────────────
    const loadAssets = useCallback(async () => {
        if (!token) return
        setLoading(true)
        try {
            const r = await fetch(`${apiUrl}/assets`, { headers: { Authorization: `Bearer ${token}` } })
            if (r.ok) setAssets((await r.json()).assets || [])
        } finally { setLoading(false) }
    }, [apiUrl, token])

    // ── Detectar desde apertura (Mass-Add) ───────────────────────
    const loadFromApertura = useCallback(async () => {
        if (!token || aperturaData) return
        setAperturaLoading(true)
        try {
            const r = await fetch(`${apiUrl}/assets/from-apertura`, {
                headers: { Authorization: `Bearer ${token}` }
            })
            if (r.ok) setAperturaData(await r.json())
        } finally { setAperturaLoading(false) }
    }, [apiUrl, token, aperturaData])

    useEffect(() => {
        loadAssets()
        loadFromApertura()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    // ── Preview cuota mensual en tiempo real ──────────────────────
    const cuotaPreview = () => {
        const ch = parseFloat(form.costo_historico) || 0
        const vr = parseFloat(form.valor_residual) || 0
        const daa = parseFloat(form.dep_acum_apertura) || 0
        const vu = parseInt(form.vida_util_meses) || 0
        const mu = parseInt(form.meses_usados_apertura) || 0
        if (!ch || !vu) return null
        const base = Math.max((ch - vr) - daa, 0)
        const meses = Math.max(vu - mu, 0)
        if (!meses) return null
        return base / meses
    }

    // ── Pre-llenar formulario desde línea de apertura ─────────────
    const prefillFromLine = (line) => {
        setForm({
            ...EMPTY,
            account_code: line.account_code,
            dep_acum_code: line.suggested_dep_acum || '',
            dep_gasto_code: '5301.01', // sugerencia estándar
            costo_historico: String(line.debit || ''),
            apertura_line_id: line.line_id,
            fecha_adquisicion: line.entry_date?.slice(0, 10) || '',
            fecha_disponible: line.entry_date?.slice(0, 10) || '',
        })
        setShowForm(true)
    }

    // ── Guardar activo ────────────────────────────────────────────
    const saveAsset = async () => {
        setFormErr(null)
        setSaving(true)
        try {
            const body = {
                ...form,
                costo_historico: parseFloat(form.costo_historico),
                valor_residual: parseFloat(form.valor_residual) || 0,
                vida_util_meses: parseInt(form.vida_util_meses),
                dep_acum_apertura: parseFloat(form.dep_acum_apertura) || 0,
                meses_usados_apertura: parseInt(form.meses_usados_apertura) || 0,
            }
            const r = await fetch(`${apiUrl}/assets`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            })
            const data = await r.json()
            if (!r.ok) { setFormErr(data.detail || 'Error guardando activo'); return }
            setShowForm(false)
            setForm(EMPTY)
            setAperturaData(null) // refrescar from-apertura
            await loadAssets()
            await loadFromApertura()
        } finally { setSaving(false) }
    }

    // ── Generar depreciación ──────────────────────────────────────
    const depreciate = async (assetId) => {
        setDepLoading(assetId)
        try {
            const r = await fetch(`${apiUrl}/assets/${assetId}/depreciate?period=${depPeriod}`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${token}` }
            })
            const data = await r.json()
            if (!r.ok) alert(data.detail || 'Error generando depreciación')
            else alert(`✅ Asiento DRAFT generado — ₡${data.cuota?.toLocaleString('es-CR')} para ${data.period}\nRevisa y aprueba en el Libro Diario.`)
        } finally { setDepLoading(null) }
    }

    const pendingApertura = aperturaData?.costo_lines?.filter(l => !l.already_registered) || []
    const cuota = cuotaPreview()

    return (
        <div style={{ padding: '24px 28px', maxWidth: 1100, margin: '0 auto' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
                <div>
                    <h1 style={{ fontSize: '1.4rem', fontWeight: 700, margin: 0 }}>🏗️ Activos Fijos</h1>
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 3 }}>
                        NIIF PYMES Sección 17 · Depreciación automática
                    </p>
                </div>
                <button
                    onClick={() => { setShowForm(true); setForm(EMPTY) }}
                    style={{
                        background: 'var(--primary)', color: '#fff',
                        border: 'none', borderRadius: 8, padding: '9px 18px',
                        fontWeight: 600, cursor: 'pointer', fontSize: '0.87rem',
                    }}
                >+ Nuevo Activo</button>
            </div>

            {/* Banner Mass-Add desde apertura */}
            {aperturaLoading && (
                <div style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 10, padding: '12px 16px', fontSize: '0.82rem', color: '#fbbf24', marginBottom: 16 }}>
                    ⏳ Buscando cuentas de activos en tu apertura...
                </div>
            )}
            {pendingApertura.length > 0 && (
                <div style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.4)', borderRadius: 10, padding: 16, marginBottom: 20 }}>
                    <div style={{ fontWeight: 700, color: '#fbbf24', fontSize: '0.85rem', marginBottom: 10 }}>
                        ⚡ {pendingApertura.length} cuenta(s) de activos detectadas en tu apertura
                    </div>
                    {pendingApertura.map(line => (
                        <div key={line.line_id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                            <span style={{ fontFamily: 'monospace', fontSize: '0.82rem', color: 'var(--primary)', fontWeight: 700, minWidth: 80 }}>{line.account_code}</span>
                            <span style={{ fontSize: '0.82rem', flex: 1 }}>{line.description || 'Sin descripción'}</span>
                            <span style={{ fontFamily: 'monospace', fontSize: '0.82rem', fontWeight: 700, color: '#10b981' }}>{fmt(line.debit)}</span>
                            <button
                                onClick={() => prefillFromLine(line)}
                                style={{ background: '#fbbf24', color: '#000', border: 'none', borderRadius: 6, padding: '5px 12px', fontWeight: 700, cursor: 'pointer', fontSize: '0.75rem' }}
                            >Registrar ▶</button>
                        </div>
                    ))}
                    {aperturaData?.dep_acum_lines?.length > 0 && (
                        <div style={{ marginTop: 10, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                            Dep. acumulada detectada: {aperturaData.dep_acum_lines.map(l => `${l.account_code} (${fmt(l.credit)})`).join(' · ')}
                        </div>
                    )}
                </div>
            )}

            {/* Lista de activos */}
            {loading && <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>⏳ Cargando activos...</div>}

            {!loading && assets.length === 0 && !showForm && (
                <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)' }}>
                    <div style={{ fontSize: '3rem', marginBottom: 12 }}>🏗️</div>
                    <p>No hay activos fijos registrados aún</p>
                    <p style={{ fontSize: '0.8rem', marginTop: 4 }}>Registra un activo o importa desde tu asiento de apertura</p>
                </div>
            )}

            {assets.length > 0 && !showForm && (
                <div>
                    <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Depreciación período:</span>
                        <input
                            type="month" value={depPeriod}
                            onChange={e => setDepPeriod(e.target.value)}
                            style={{ border: '1px solid var(--border-color)', borderRadius: 6, padding: '4px 8px', background: 'var(--bg-card)', color: 'var(--text-primary)', fontSize: '0.82rem' }}
                        />
                        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>— Genera asiento DRAFT para el contador</span>
                    </div>

                    <div style={{ display: 'grid', gap: 12 }}>
                        {assets.map(a => (
                            <div key={a.id} style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: 12, alignItems: 'center' }}>
                                <div>
                                    <div style={{ fontWeight: 700, fontSize: '0.9rem' }}>{a.nombre}</div>
                                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>
                                        {CATEGORIAS.find(c => c.value === a.categoria)?.label} · <span style={{ fontFamily: 'monospace' }}>{a.account_code}</span>
                                    </div>
                                    {a.numero_serie && <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>#{a.numero_serie}</div>}
                                </div>
                                <div>
                                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 2 }}>Costo Histórico</div>
                                    <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '0.85rem' }}>{fmt(a.costo_historico)}</div>
                                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Neto: {fmt(a.valor_neto_contable)}</div>
                                </div>
                                <div>
                                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 2 }}>Cuota Mensual</div>
                                    <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '0.85rem', color: '#10b981' }}>{fmt(a.cuota_mensual)}</div>
                                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{a.meses_restantes} meses restantes</div>
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end' }}>
                                    <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '2px 8px', borderRadius: 20, background: `${ESTADO_COLOR[a.estado]}25`, color: ESTADO_COLOR[a.estado] }}>
                                        {a.estado}
                                    </span>
                                    {a.estado === 'ACTIVO' && a.cuota_mensual > 0 && (
                                        <button
                                            disabled={depLoading === a.id}
                                            onClick={() => depreciate(a.id)}
                                            style={{ background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: 6, padding: '5px 12px', fontSize: '0.73rem', fontWeight: 600, cursor: 'pointer', opacity: depLoading === a.id ? 0.6 : 1 }}
                                        >
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

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                        {/* Categoría */}
                        <div>
                            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Categoría *</label>
                            <select value={form.categoria} onChange={e => setForm({ ...form, categoria: e.target.value })}
                                style={{ width: '100%', padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem' }}>
                                {CATEGORIAS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                            </select>
                        </div>
                        {/* Nombre */}
                        <div>
                            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Nombre del activo *</label>
                            <input value={form.nombre} onChange={e => setForm({ ...form, nombre: e.target.value })} placeholder="Toyota Hilux 2024"
                                style={{ width: '100%', padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                        </div>
                        {/* Número serie */}
                        <div>
                            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Número de serie / placa</label>
                            <input value={form.numero_serie} onChange={e => setForm({ ...form, numero_serie: e.target.value })} placeholder="ABC-123"
                                style={{ width: '100%', padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                        </div>
                        {/* Proveedor */}
                        <div>
                            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Proveedor</label>
                            <input value={form.proveedor} onChange={e => setForm({ ...form, proveedor: e.target.value })} placeholder="Toyota de Costa Rica S.A."
                                style={{ width: '100%', padding: '8px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                        </div>
                    </div>

                    {/* Cuentas GL */}
                    <div style={{ marginTop: 16, background: 'rgba(99,102,241,0.06)', borderRadius: 10, padding: 14 }}>
                        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10, letterSpacing: '0.05em' }}>MAPEO CONTABLE (3 cuentas requeridas)</div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                            {[
                                { field: 'account_code', label: 'Cuenta Costo *', ph: '1201.04' },
                                { field: 'dep_acum_code', label: 'Dep. Acumulada *', ph: '1202.03' },
                                { field: 'dep_gasto_code', label: 'Gasto Depreciación *', ph: '5301.01' },
                            ].map(({ field, label, ph }) => (
                                <div key={field}>
                                    <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>{label}</label>
                                    <input value={form[field]} onChange={e => setForm({ ...form, [field]: e.target.value })} placeholder={ph}
                                        style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Valoración NIIF */}
                    <div style={{ marginTop: 16, background: 'rgba(16,185,129,0.06)', borderRadius: 10, padding: 14 }}>
                        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10, letterSpacing: '0.05em' }}>VALORACIÓN NIIF PYMES SEC. 17</div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Fecha adquisición *</label>
                                <input type="date" value={form.fecha_adquisicion} onChange={e => setForm({ ...form, fecha_adquisicion: e.target.value })}
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Fecha disponible para uso * <span style={{ color: '#fbbf24' }}>← NIIF: depreciación inicia aquí</span></label>
                                <input type="date" value={form.fecha_disponible} onChange={e => setForm({ ...form, fecha_disponible: e.target.value })}
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Costo histórico (₡) *</label>
                                <input type="number" value={form.costo_historico} onChange={e => setForm({ ...form, costo_historico: e.target.value })} placeholder="13555935"
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Valor residual (₡)</label>
                                <input type="number" value={form.valor_residual} onChange={e => setForm({ ...form, valor_residual: e.target.value })} placeholder="0"
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Vida útil total (meses) *</label>
                                <input type="number" value={form.vida_util_meses} onChange={e => setForm({ ...form, vida_util_meses: e.target.value })} placeholder="60"
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Método de depreciación *</label>
                                <select value={form.metodo_depreciacion} onChange={e => setForm({ ...form, metodo_depreciacion: e.target.value })}
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem' }}>
                                    {METODOS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                                </select>
                            </div>
                        </div>
                    </div>

                    {/* Estado apertura */}
                    <div style={{ marginTop: 16, background: 'rgba(251,191,36,0.06)', borderRadius: 10, padding: 14 }}>
                        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10, letterSpacing: '0.05em' }}>ESTADO AL REGISTRAR (si viene de apertura)</div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Dep. acumulada al inicio (₡)</label>
                                <input type="number" value={form.dep_acum_apertura} onChange={e => setForm({ ...form, dep_acum_apertura: e.target.value })} placeholder="4424872.13"
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                            <div>
                                <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Meses ya depreciados al inicio</label>
                                <input type="number" value={form.meses_usados_apertura} onChange={e => setForm({ ...form, meses_usados_apertura: e.target.value })} placeholder="20"
                                    style={{ width: '100%', padding: '7px 10px', borderRadius: 7, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: '0.85rem', boxSizing: 'border-box' }} />
                            </div>
                        </div>
                    </div>

                    {/* Preview cuota */}
                    {cuota !== null && (
                        <div style={{ marginTop: 16, background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.3)', borderRadius: 10, padding: '12px 16px', display: 'flex', gap: 24, alignItems: 'center' }}>
                            <div>
                                <div style={{ fontSize: '0.7rem', color: '#10b981', fontWeight: 700, letterSpacing: '0.05em' }}>CUOTA MENSUAL ESTIMADA</div>
                                <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#10b981', fontFamily: 'monospace' }}>{fmt(cuota)}</div>
                            </div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                                × {Math.max(parseInt(form.vida_util_meses || 0) - parseInt(form.meses_usados_apertura || 0), 0)} meses restantes<br />
                                = {fmt(cuota * Math.max(parseInt(form.vida_util_meses || 0) - parseInt(form.meses_usados_apertura || 0), 0))} total a depreciar
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
                            style={{ padding: '9px 22px', borderRadius: 7, border: 'none', background: 'var(--primary)', color: '#fff', fontWeight: 700, cursor: 'pointer', fontSize: '0.85rem', opacity: saving ? 0.7 : 1 }}>
                            {saving ? 'Guardando...' : '✅ Registrar Activo'}
                        </button>
                    </div>
                </div>
            )}
        </div>
    )
}
