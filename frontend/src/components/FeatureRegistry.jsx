import { createContext, useContext } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const FeatureRegistryContext = createContext({ enabled: {}, features: [], loaded: false })

export function FeatureRegistryProvider({ children }) {
  const query = useQuery({
    queryKey: ['runtime-features'],
    queryFn: () => api.get('/meta/features').then((response) => response.data),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const value = {
    enabled: query.data?.enabled || {},
    features: query.data?.features || [],
    loaded: query.isSuccess,
  }

  return <FeatureRegistryContext.Provider value={value}>{children}</FeatureRegistryContext.Provider>
}

export function useFeature(key) {
  const registry = useContext(FeatureRegistryContext)
  return Boolean(registry.loaded && registry.enabled[key])
}
