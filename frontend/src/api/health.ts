import { apiRequest } from './client'
import type { LivenessResponse, ReadinessResponse } from '../types/api'

export function getLiveness(signal?: AbortSignal): Promise<LivenessResponse> {
  return apiRequest<LivenessResponse>('/health/live', { signal })
}

export function getReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  return apiRequest<ReadinessResponse>('/health/ready', { signal })
}
