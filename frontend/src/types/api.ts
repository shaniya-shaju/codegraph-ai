// TypeScript types mirroring the backend's response models exactly (field
// names/shapes) — see backend/app/domain/**/models.py,
// backend/app/rag/answer_models.py, backend/app/domain/impact/models.py,
// backend/app/api/routes/*.py. Kept in one file since these are pure data
// shapes shared across every feature; `Record<string, unknown>` is used
// instead of `any` for genuinely dynamic metadata (see Prompt 11 "API
// Types": "Avoid `any`.").

// --- health / readiness -----------------------------------------------

export type DependencyStatusValue = 'READY' | 'DEGRADED' | 'UNAVAILABLE' | 'NOT_LOADED' | 'UNKNOWN'

export interface DependencyState {
  status: DependencyStatusValue
  detail: string | null
  // Only meaningfully populated for "llm"/"embedding_provider" — null on
  // every other dependency — see Prompt 11.5 "Setup wizard / diagnostic
  // endpoint".
  model: string | null
  provider: string | null
}

export interface LivenessResponse {
  status: string
  service: string
}

export interface ReadinessResponse {
  status: 'ready' | 'degraded' | 'unavailable'
  dependencies: Record<string, DependencyState>
}

// --- repositories --------------------------------------------------------

export type RepositorySourceType = 'zip_upload' | 'git_url' | 'local_path'

export interface LanguageStats {
  total_files: number
  total_bytes: number
  python_files: number
  binary_files_skipped: number
  languages: Record<string, number>
}

export interface Repository {
  repository_id: string
  name: string
  source_type: string
  source_location: string
  status: string
  default_branch: string | null
  commit_sha: string | null
  file_count: number | null
  error_message: string | null
  file_stats: LanguageStats | null
  created_at: string | null
  last_indexed_at: string | null
}

// --- analysis state --------------------------------------------------------

export type SubsystemStatus =
  | 'NOT_STARTED'
  | 'PENDING'
  | 'RUNNING'
  | 'READY'
  | 'FAILED'
  | 'STALE'

export type OverallStatus =
  | 'NOT_STARTED'
  | 'PENDING'
  | 'RUNNING'
  | 'READY'
  | 'PARTIAL'
  | 'FAILED'
  | 'STALE'

export type AnalysisStage =
  | 'IMPORT'
  | 'SCAN'
  | 'PARSE'
  | 'BUILD_GRAPH'
  | 'BUILD_VECTOR_INDEX'
  | 'FINALIZE'
  | 'DONE'

export interface AnalysisState {
  repository_id: string
  overall_status: OverallStatus
  parser_status: SubsystemStatus
  graph_status: SubsystemStatus
  vector_status: SubsystemStatus
  current_stage: AnalysisStage
  progress_percentage: number
  job_id: string | null
  files_total: number | null
  files_processed: number | null
  files_failed: number | null
  graph_node_count: number | null
  graph_relationship_count: number | null
  vector_chunk_count: number | null
  warnings: string[]
  errors: string[]
  started_at: string | null
  updated_at: string
  completed_at: string | null
  graph_updated_at: string | null
  vector_updated_at: string | null
  repository_revision: string | null
  graph_current: boolean
  vector_current: boolean
  parse_duration_ms: number | null
  graph_build_duration_ms: number | null
  vector_index_duration_ms: number | null
  total_duration_ms: number | null
}

export interface AnalyzeResponse {
  job_id: string
  repository_id: string
  status: 'running' | 'already_running' | 'current'
}

export interface AnalysisProgressEvent {
  repository_id: string
  job_id: string
  stage: string
  status: string
  progress_percentage: number
  message: string | null
  files_processed: number | null
  files_total: number | null
  created_at?: number
}

export interface DeleteRepositoryResult {
  repository_id: string
  status: 'deleted' | 'partially_cleaned'
  cleaned: string[]
  errors: string[]
}

export interface SourceSnippet {
  repository_id: string
  file_path: string
  start_line: number
  end_line: number
  total_lines: number
  content: string
  truncated: boolean
}

// --- graph -----------------------------------------------------------------

export type NodeLabel =
  | 'Repository'
  | 'Directory'
  | 'File'
  | 'Module'
  | 'Class'
  | 'Function'
  | 'Method'
  | 'Parameter'
  | 'ExternalDependency'
  | 'APIEndpoint'

export type RelationshipType =
  | 'CONTAINS'
  | 'DEFINES'
  | 'IMPORTS'
  | 'CALLS'
  | 'HAS_PARAMETER'
  | 'EXTENDS'
  | 'REFERENCES'
  | 'HANDLED_BY'
  | 'DEPENDS_ON'

export type SymbolMatchType = 'exact_name' | 'exact_qualified_name' | 'prefix' | 'contains'

export interface GraphNode {
  id: string
  repository_id: string
  label: NodeLabel
  name: string
  qualified_name: string | null
  file_path: string | null
  start_line: number | null
  end_line: number | null
  properties: Record<string, unknown>
}

export interface GraphEdge {
  id: string
  repository_id: string
  source_id: string
  target_id: string
  relationship_type: RelationshipType
  properties: Record<string, unknown>
}

export interface GraphSubgraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  truncated: boolean
  traversal_depth: number
  result_limit: number
}

export interface SymbolSearchResult {
  symbol_id: string
  symbol_type: NodeLabel
  name: string
  qualified_name: string | null
  file_path: string | null
  start_line: number | null
  end_line: number | null
  match_type: SymbolMatchType
}

export interface GraphStatistics {
  repository_id: string
  node_counts: Record<string, number>
  relationship_counts: Record<string, number>
  unresolved_call_count: number
  parse_error_count: number
}

// --- hybrid retrieval --------------------------------------------------------

export type RetrievalMode = 'vector' | 'graph' | 'hybrid'

export type QueryIntent =
  | 'code_location'
  | 'code_explanation'
  | 'caller_lookup'
  | 'callee_lookup'
  | 'dependency_lookup'
  | 'impact_analysis'
  | 'architecture'
  | 'api_lookup'
  | 'inheritance_lookup'
  | 'general_code_question'
  | 'unknown'

export type SymbolResolutionStatus = 'exact' | 'unique' | 'ambiguous' | 'not_found'

export type EvidenceSource = 'vector' | 'graph' | 'symbol' | 'api'

export type EvidenceType =
  | 'code_chunk'
  | 'symbol'
  | 'call_relationship'
  | 'dependency_relationship'
  | 'inheritance_relationship'
  | 'api_endpoint'
  | 'module'
  | 'file'
  | 'graph_statistic'

export interface ScoreComponents {
  vector: number
  exact: number
  graph: number
  intent: number
}

export interface RetrievalEvidence {
  id: string
  repository_id: string
  evidence_type: EvidenceType
  symbol_id: string | null
  qualified_name: string | null
  file_path: string | null
  start_line: number | null
  end_line: number | null
  content: string
  source: EvidenceSource
  vector_score: number | null
  graph_distance: number | null
  exact_match_score: number | null
  relationship_type: string | null
  metadata: Record<string, unknown>
}

export interface RankedEvidence {
  evidence: RetrievalEvidence
  hybrid_score: number
  score_components: ScoreComponents
  sources: EvidenceSource[]
}

export interface ResolvedSymbol {
  symbol_id: string
  symbol_type: NodeLabel
  name: string
  qualified_name: string | null
  file_path: string | null
  start_line: number | null
  end_line: number | null
  match_type: SymbolMatchType
  confidence: number
}

export interface SymbolResolution {
  query: string
  resolved_symbol: ResolvedSymbol | null
  candidates: ResolvedSymbol[]
  status: SymbolResolutionStatus
}

export interface QueryAnalysis {
  raw_question: string
  normalized_question: string
  primary_intent: QueryIntent
  secondary_intents: QueryIntent[]
  symbols: string[]
  file_paths: string[]
  module_names: string[]
  class_names: string[]
  function_names: string[]
  api_routes: string[]
  requested_depth: number | null
  requires_vector_search: boolean
  requires_graph_search: boolean
  requires_exact_symbol_search: boolean
  confidence: number | null
  analysis_strategy: string
}

export interface RetrievalDiagnostics {
  retrieval_duration_ms: number
  vector_duration_ms: number
  graph_duration_ms: number
  analysis_duration_ms: number
  fallbacks_used: string[]
  warnings: string[]
}

export interface HybridRetrievalResult {
  repository_id: string
  question: string
  analysis: QueryAnalysis
  resolved_symbols: SymbolResolution[]
  evidence: RankedEvidence[]
  total_vector_candidates: number
  total_graph_candidates: number
  total_symbol_candidates: number
  deduplicated_count: number
  returned_count: number
  truncated: boolean
  diagnostics: RetrievalDiagnostics
}

// --- grounded question answering --------------------------------------------

export type AnswerConfidence = 'HIGH' | 'MEDIUM' | 'LOW' | 'INSUFFICIENT_EVIDENCE'

export interface CodeCitation {
  citation_id: string
  file_path: string | null
  start_line: number | null
  end_line: number | null
  symbol_id: string | null
  qualified_name: string | null
  evidence_type: EvidenceType
}

export interface ResolvedSymbolReference {
  query: string
  qualified_name: string | null
  symbol_id: string | null
  file_path: string | null
  start_line: number | null
  end_line: number | null
  status: SymbolResolutionStatus
}

export interface QueryResponse {
  answer: string
  citations: CodeCitation[]
  confidence_level: AnswerConfidence
  confidence_reason: string
  retrieval_mode: string
  primary_intent: string
  resolved_symbols: ResolvedSymbolReference[]
  limitations: string[]
  abstained: boolean
  conversation_id: string | null
}

// --- change-impact analysis --------------------------------------------------

export type ImpactTargetType = 'FUNCTION' | 'METHOD' | 'CLASS' | 'API_ENDPOINT'

export type ImpactType =
  | 'DIRECT_CALLER'
  | 'TRANSITIVE_CALLER'
  | 'CALLEE'
  | 'DEPENDENCY'
  | 'INHERITING_CLASS'
  | 'BASE_CLASS'
  | 'API_ENDPOINT'
  | 'FILE'
  | 'MODULE'
  | 'TEST_REFERENCE'

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type ImpactSignalType =
  | 'DIRECT_CALLER_COUNT'
  | 'TRANSITIVE_DEPENDENT_COUNT'
  | 'AFFECTED_FILE_COUNT'
  | 'AFFECTED_MODULE_COUNT'
  | 'PUBLIC_API_EXPOSURE'
  | 'CROSS_MODULE_DEPENDENCY'
  | 'EXTERNAL_DEPENDENCY_INTERACTION'
  | 'INHERITANCE_IMPACT'
  | 'GRAPH_CENTRALITY'
  | 'RELATED_TEST_SIGNAL'

export type TestRelationshipStatus =
  | 'KNOWN_RELATED_TESTS'
  | 'NO_KNOWN_TEST_REFERENCES'
  | 'UNKNOWN'

export interface ImpactTarget {
  symbol_id: string
  qualified_name: string | null
  name: string
  target_type: ImpactTargetType
  file_path: string | null
  start_line: number | null
  end_line: number | null
}

export interface ImpactedSymbol {
  symbol_id: string
  qualified_name: string | null
  symbol_type: string
  file_path: string | null
  start_line: number | null
  end_line: number | null
  impact_type: ImpactType
  distance: number
  reason: string
  path: string[]
  relationship_path: string[]
}

export interface ImpactedEndpoint {
  endpoint_id: string
  http_method: string
  route_path: string
  handler_symbol_id: string
  handler_qualified_name: string | null
  distance_from_target: number
  impact_reason: string
}

export interface ImpactedFile {
  file_path: string
  affected_symbol_count: number
  minimum_distance: number
  impact_types: ImpactType[]
  impacted_symbol_ids: string[]
}

export interface ImpactedModule {
  module_name: string
  affected_symbol_count: number
  minimum_distance: number
  impacted_symbol_ids: string[]
}

export interface ImpactSignal {
  signal_type: ImpactSignalType
  raw_value: number
  normalized_value: number
  contribution: number
  explanation: string
}

export interface ImpactDiagnostics {
  analysis_duration_ms: number
  nodes_visited: number
  edges_traversed: number
  paths_examined: number
  cycles_detected: number
  truncated_reason: string | null
}

export interface ImpactAnalysisResult {
  repository_id: string
  target: ImpactTarget
  risk_score: number
  risk_level: RiskLevel
  risk_signals: ImpactSignal[]
  direct_callers: ImpactedSymbol[]
  transitive_dependents: ImpactedSymbol[]
  downstream_dependencies: ImpactedSymbol[]
  affected_endpoints: ImpactedEndpoint[]
  affected_files: ImpactedFile[]
  affected_modules: ImpactedModule[]
  inheritance_impacts: ImpactedSymbol[]
  inheriting_classes: ImpactedSymbol[]
  base_classes: ImpactedSymbol[]
  related_tests: ImpactedSymbol[]
  test_relationship_status: TestRelationshipStatus
  traversal_depth: number
  total_impacted_symbols: number
  truncated: boolean
  limitations: string[]
  diagnostics: ImpactDiagnostics
}

export interface ImpactExplanationResponse {
  result: ImpactAnalysisResult
  explanation: string
  warnings: string[]
}

// --- error contract ----------------------------------------------------------

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    retryable: boolean
    details: Record<string, unknown>
  }
  request_id?: string
}
