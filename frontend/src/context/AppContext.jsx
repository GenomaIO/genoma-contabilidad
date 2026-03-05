/**
 * AppContext — Multi-tenant state global
 * NO hardcoded tenant IDs · Todo desde JWT o env
 *
 * authLoading: true hasta que el useEffect de hidratación termina.
 * Esto evita la race condition donde ProtectedRoute redirige antes
 * de que el token del URL sea procesado.
 */
import { createContext, useContext, useReducer, useEffect } from 'react'

const AppContext = createContext(null)

const initialState = {
    theme: localStorage.getItem('gc_theme') || 'dark',
    sidebarOpen: false,
    user: null,
    tenant: null,
    period: null,
    authLoading: true,   // ← guard contra race condition en ProtectedRoute
    apiStatus: 'checking',
}

function reducer(state, action) {
    switch (action.type) {
        case 'SET_THEME':
            localStorage.setItem('gc_theme', action.payload)
            return { ...state, theme: action.payload }

        case 'TOGGLE_SIDEBAR':
            return { ...state, sidebarOpen: !state.sidebarOpen }

        case 'SET_SIDEBAR':
            return { ...state, sidebarOpen: action.payload }

        case 'SET_USER':
            return { ...state, user: action.payload }

        case 'SET_TENANT':
            return { ...state, tenant: action.payload }

        case 'SET_PERIOD':
            return { ...state, period: action.payload }

        case 'SET_API_STATUS':
            return { ...state, apiStatus: action.payload }

        case 'AUTH_READY':
            // Se despacha cuando la hidratación de token termina (con o sin usuario)
            return { ...state, authLoading: false }

        case 'LOGOUT':
            localStorage.removeItem('gc_token')
            return { ...initialState, authLoading: false, theme: state.theme, apiStatus: state.apiStatus }

        default:
            return state
    }
}

function parseJwtPayload(token) {
    try {
        const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
        return JSON.parse(atob(base64))
    } catch {
        return null
    }
}

export function AppProvider({ children }) {
    const [state, dispatch] = useReducer(reducer, initialState)

    useEffect(() => {
        document.documentElement.setAttribute('data-theme', state.theme)
    }, [state.theme])

    // ── Hidratación: URL ?token= → localStorage → Estado ──────────
    // Al terminar siempre despacha AUTH_READY para liberar el guard.
    useEffect(() => {
        const params = new URLSearchParams(window.location.search)
        const urlToken = params.get('token')
        let activeToken = null

        if (urlToken) {
            localStorage.setItem('gc_token', urlToken)
            activeToken = urlToken
            window.history.replaceState({}, document.title, window.location.pathname)
        } else {
            activeToken = localStorage.getItem('gc_token')
        }

        if (activeToken) {
            const payload = parseJwtPayload(activeToken)
            if (payload && payload.exp * 1000 > Date.now()) {
                dispatch({
                    type: 'SET_USER',
                    payload: {
                        user_id: payload.sub,
                        nombre: payload.nombre,
                        tenant_id: payload.tenant_id,
                        tenant_type: payload.tenant_type,
                        role: payload.role,
                        partner_id: payload.partner_id || null,
                    }
                })
            } else {
                localStorage.removeItem('gc_token')
            }
        }

        // Siempre liberar el guard — con o sin usuario
        dispatch({ type: 'AUTH_READY' })
    }, [])

    useEffect(() => {
        const apiUrl = import.meta.env.VITE_API_URL || ''
        fetch(`${apiUrl}/health`)
            .then(r => r.json())
            .then(data => {
                dispatch({ type: 'SET_API_STATUS', payload: data.status === 'ok' ? 'ok' : 'error' })
            })
            .catch(() => dispatch({ type: 'SET_API_STATUS', payload: 'error' }))
    }, [])

    const toggleTheme = () => {
        dispatch({ type: 'SET_THEME', payload: state.theme === 'dark' ? 'light' : 'dark' })
    }

    return (
        <AppContext.Provider value={{ state, dispatch, toggleTheme }}>
            {children}
        </AppContext.Provider>
    )
}

export const useApp = () => {
    const ctx = useContext(AppContext)
    if (!ctx) throw new Error('useApp must be used inside AppProvider')
    return ctx
}
