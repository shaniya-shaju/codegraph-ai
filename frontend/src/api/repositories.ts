import { apiRequest } from './client'
import type { DeleteRepositoryResult, Repository } from '../types/api'

export function listRepositories(signal?: AbortSignal): Promise<Repository[]> {
  return apiRequest<Repository[]>('/repositories', { signal })
}

export function getRepository(repositoryId: string, signal?: AbortSignal): Promise<Repository> {
  return apiRequest<Repository>(`/repositories/${repositoryId}`, { signal })
}

export function uploadRepository(name: string, file: File): Promise<Repository> {
  const formData = new FormData()
  formData.set('name', name)
  formData.set('file', file)
  return apiRequest<Repository>('/repositories/upload', {
    method: 'POST',
    formData,
    // Import runs the full synchronous analysis pipeline inline — allow
    // considerably longer than the default interactive-request timeout.
    timeoutMs: 180_000,
  })
}

export function cloneRepository(
  name: string,
  gitUrl: string,
  branch?: string,
): Promise<Repository> {
  return apiRequest<Repository>('/repositories/clone', {
    method: 'POST',
    json: { name, git_url: gitUrl, branch: branch || undefined },
    timeoutMs: 180_000,
  })
}

export function deleteRepository(repositoryId: string): Promise<DeleteRepositoryResult> {
  return apiRequest<DeleteRepositoryResult>(`/repositories/${repositoryId}`, {
    method: 'DELETE',
  })
}
