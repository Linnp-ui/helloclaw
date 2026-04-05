import api from './index'

export interface MemoryEntry {
  date: string
  filename: string
  content: string
  preview: string
}

export interface MemoryListResponse {
  memories: MemoryEntry[]
  total: number
}

export interface TopicInfo {
  filename: string
  title: string
  tags: string[]
  relevance: number
  created: string
  preview: string
}

export interface TopicListResponse {
  topics: TopicInfo[]
  total: number
}

export interface TopicResponse {
  filename: string
  title: string
  tags: string[]
  content: string
}

export interface SearchResult {
  session_id: string
  date: string
  role: string
  content: string
  tokens: number
}

export interface SearchResponse {
  results: SearchResult[]
  total: number
  query: string
}

export interface ArchiveStats {
  total_files: number
  total_records: number
  years: string[]
  by_role: { user: number; assistant: number; tool: number }
}

export interface HotIndexStats {
  total: number
  categories: { preference: number; decision: number; entity: number; fact: number }
  size_bytes: number
  last_updated: string
}

export const memoryApi = {
  list: async () => {
    return api.get<MemoryListResponse>('/memory/list')
  },
  get: async (filename: string) => {
    return api.get<{ filename: string; date: string; content: string }>(`/memory/${filename}`)
  },
  stats: async () => {
    return api.get('/memory/stats')
  },
  
  // Hot 层
  getHotStats: async () => {
    return api.get<HotIndexStats>('/memory/hot/stats')
  },
  
  // Warm 层 - 话题
  listTopics: async (q?: string, maxTopics: number = 5) => {
    const params = new URLSearchParams()
    if (q) params.append('q', q)
    params.append('max_topics', String(maxTopics))
    return api.get<TopicListResponse>(`/memory/topics?${params.toString()}`)
  },
  getTopic: async (filename: string) => {
    return api.get<TopicResponse>(`/memory/topics/${filename}`)
  },
  
  // Cold 层 - 归档与搜索
  archiveSessions: async () => {
    return api.post('/memory/archive')
  },
  search: async (q: string, year?: string, role?: string, limit: number = 50) => {
    const params = new URLSearchParams()
    params.append('q', q)
    if (year) params.append('year', year)
    if (role) params.append('role', role)
    params.append('limit', String(limit))
    return api.get<SearchResponse>(`/memory/search?${params.toString()}`)
  },
  getArchiveStats: async () => {
    return api.get<ArchiveStats>('/memory/archive/stats')
  },
}