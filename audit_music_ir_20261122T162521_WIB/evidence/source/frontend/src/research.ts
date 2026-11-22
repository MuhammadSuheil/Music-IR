import type { RankingPolicy, Track } from './lib'

export type DecisionRow = {
  track_id: string; title: string; artist: string; sources: Record<string, number>
  rank_before_reranking: number | null; final_rank: number | null; displayed: boolean
  disposition: 'ranked' | 'audio_filtered' | 'intent_filtered' | 'candidate_limit' | 'not_retrieved' | 'not_in_corpus'
  displayed_group?: string | null
  theme_evidence?: Track['theme_evidence'] | null
  ordering_values?: { score: number | null; popularity: number | null; rrf: number; track_id: string }
  score: number | null; contributions: Record<string, number>; features: Record<string, number>
  failed_constraints: { feature: string; operator: string; bound: number; value: number | null }[]
}
export type Decisions = {
  ranking?: RankingPolicy
  query_plan: { planned_type: string; effective_type: string; text_query: string; semantic_query: string | null }
  stages: { corpus: number; sources: Record<string, number>; retrieved_unique: number; audio_filtered: number; selected_candidates: number; displayed: number }
  timings_ms: Record<string, number>; audio_weight: number; text_weights: Record<string, number>
  manifest: { corpus_sha256: string; implementation_sha256: string; model_name: string; model_revision: string }
  candidates: DecisionRow[]; target: DecisionRow | null; score_note: string
}
export type BenchmarkQuery = {
  query_id: string; query: string; category: string; split: 'dev' | 'test'; group_id: string
  intent_note: string; review_status: 'draft' | 'approved'; pool_count: number; judged_count: number; conflicts: number
}
export type BenchmarkSummary = {
  queries: BenchmarkQuery[]; total: number; approved: number; judgments: number; dataset_sha256: string
  note: string; rubric: Record<string, string>
}
export type ReviewTrack = Track & { lyrics: string; judgment: { grade: number; notes: string } | null }
export type CandidatePool = { query: BenchmarkQuery; candidates: ReviewTrack[]; prepared: boolean; note?: string }
export type ExportBundle = { queries_jsonl: string; qrels_csv: string; manifest: Record<string, unknown> }

export function download(name: string, content: string, mime = 'application/json') {
  const url = URL.createObjectURL(new Blob([content], { type: mime + ';charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url; link.download = name
  document.body.appendChild(link); link.click(); link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
