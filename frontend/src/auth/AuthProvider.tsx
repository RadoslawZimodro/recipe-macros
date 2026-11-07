import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { api, ApiError, setSessionLostHandler } from '../api/client'
import type { User } from '../api/types'
import { ME_KEY } from './meKey'

interface Credentials {
  email: string
  password: string
}

interface AuthState {
  /** null = not logged in; undefined while the first check is running. */
  user: User | null | undefined
  login: (credentials: Credentials) => Promise<User>
  register: (credentials: Credentials) => Promise<User>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  // 401 here simply means "nobody is logged in", not an error to retry.
  const me = useQuery({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await api.get<User>('/auth/me')
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    retry: false,
    staleTime: Infinity,
  })

  const forgetEverything = useCallback(() => {
    // Another user must never see the previous one's cached data.
    queryClient.clear()
    queryClient.setQueryData(ME_KEY, null)
  }, [queryClient])

  useEffect(() => {
    setSessionLostHandler(forgetEverything)
    return () => setSessionLostHandler(null)
  }, [forgetEverything])

  const loginMutation = useMutation({
    mutationFn: (credentials: Credentials) => api.post<User>('/auth/login', credentials),
    onSuccess: (user) => {
      queryClient.clear()
      queryClient.setQueryData(ME_KEY, user)
    },
  })
  const registerMutation = useMutation({
    mutationFn: (credentials: Credentials) => api.post<User>('/auth/register', credentials),
    onSuccess: (user) => {
      queryClient.clear()
      queryClient.setQueryData(ME_KEY, user)
    },
  })
  const logoutMutation = useMutation({
    mutationFn: () => api.post<void>('/auth/logout'),
    onSettled: forgetEverything,
  })

  const { mutateAsync: login } = loginMutation
  const { mutateAsync: register } = registerMutation
  const { mutateAsync: logout } = logoutMutation

  const value = useMemo<AuthState>(
    () => ({
      user: me.isPending ? undefined : (me.data ?? null),
      login,
      register,
      logout,
    }),
    [me.isPending, me.data, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
