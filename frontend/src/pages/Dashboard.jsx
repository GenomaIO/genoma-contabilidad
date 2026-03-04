import { useApp } from '../context/AppContext'

export default function Dashboard() {
    const { state } = useApp()

    const stats = [
        { label: 'Activos', value: '—', icon: '🏦', color: 'var(--info)' },
        { label: 'Pasivos', value: '—', icon: '📋', color: 'var(--warning)' },
        { label: 'Patrimonio', value: '—', icon: '💎', color: 'var(--success)' },
        { label: 'Resultado', value: '—', icon: '📈', color: 'var(--accent-light)' },
    ]

    return (
        <div>
            {/* Encabezado */}
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>
                        Resumen Contable
                    </h2>
                    <p className="text-sm text-muted" style={{ marginTop: 2 }}>
                        Vista general del período activo
                    </p>
                </div>
                {state.apiStatus !== 'ok' && (
                    <span className="badge badge-warning">⚠️ Sin conexión API</span>
                )}
            </div>

            {/* Stats grid — tablet 4 col, mobile 2 col */}
            <div className="grid-4 mb-4">
                {stats.map(stat => (
                    <div key={stat.label} className="card" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                        <div style={{
                            width: 44, height: 44, borderRadius: 10,
                            background: `color-mix(in srgb, ${stat.color} 15%, transparent)`,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontSize: '1.25rem', flexShrink: 0,
                        }}>
                            {stat.icon}
                        </div>
                        <div>
                            <div className="text-xs text-muted">{stat.label}</div>
                            <div style={{ fontSize: '1.1rem', fontWeight: 700, marginTop: 2 }}>
                                {stat.value}
                            </div>
                        </div>
                    </div>
                ))}
            </div>

            {/* Últimas entradas + Próximas tareas */}
            <div className="grid-2">
                <div className="card">
                    <div className="flex items-center justify-between mb-4">
                        <span className="card-title">📒 Últimos Asientos</span>
                        <button className="btn btn-ghost text-xs">Ver todos</button>
                    </div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', textAlign: 'center', padding: '24px 0' }}>
                        No hay asientos en este período
                    </div>
                </div>

                <div className="card">
                    <div className="flex items-center justify-between mb-4">
                        <span className="card-title">✅ Tareas Pendientes</span>
                        <span className="badge badge-accent">0</span>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {[
                            { label: 'Importar saldo apertura', done: false },
                            { label: 'Sincronizar con Facturador', done: false },
                            { label: 'Revisar catálogo de cuentas', done: false },
                        ].map(task => (
                            <div key={task.label} className="flex items-center gap-2 text-sm" style={{
                                padding: '8px 10px',
                                borderRadius: 8,
                                background: 'var(--bg-3)',
                                color: task.done ? 'var(--text-muted)' : 'var(--text-secondary)',
                                textDecoration: task.done ? 'line-through' : 'none',
                            }}>
                                <span>{task.done ? '✅' : '⬜'}</span>
                                {task.label}
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Status API */}
            <div className="card mt-4" style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '12px 16px',
                border: `1px solid ${state.apiStatus === 'ok' ? 'var(--success)' : 'var(--danger)'}`,
                background: state.apiStatus === 'ok' ? 'var(--success-bg)' : 'var(--danger-bg)',
            }}>
                <div style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: state.apiStatus === 'ok' ? 'var(--success)' : 'var(--danger)',
                    flexShrink: 0,
                }} />
                <span className="text-sm">
                    {state.apiStatus === 'checking' && '⏳ Verificando conexión con el servidor...'}
                    {state.apiStatus === 'ok' && '🟢 Servidor conectado y base de datos operativa'}
                    {state.apiStatus === 'error' && '🔴 Sin conexión con el servidor. Verificar Render.'}
                </span>
            </div>
        </div>
    )
}
