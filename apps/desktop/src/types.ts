export interface Word {
  id: string;
  text: string;
  start_ms: number;
  end_ms: number;
  confidence: number | null;
}
export interface Segment {
  id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  raw_text: string;
  speaker: string;
  words: Word[];
  alignment_status: "valid" | "dirty" | "incomplete";
  speaker_group?: string | null;
  speaker_source?: "model" | "manual";
  needs_confirmation?: boolean;
  review_reasons?: string[];
}
export interface Transcript {
  schema_version: number;
  duration_ms: number;
  language: string;
  segments: Segment[];
}
export interface Cue {
  id: string;
  segment_id: string;
  text: string;
  char_start: number;
  char_end: number;
  start_ms: number;
  end_ms: number;
  timing_status: string;
  manual_override: boolean;
}
export interface Track {
  revision: number;
  source_revision: number;
  max_chars: number;
  cues: Cue[];
}
export interface ProjectSummary {
  id: string;
  title: string;
  filename: string;
  duration_ms: number;
  revision: number;
  created: number;
  updated: number;
  has_transcript: boolean;
  summary_at?: number | null;
}
export interface SpeakerGroup {
  label: string;
  name: string;
  name_source: "auto" | "voiceprint" | "manual";
  seconds: number;
  segments: number;
  match_reason: string | null;
  similarity: number | null;
  similarity_percent?: number | null;
  excerpt_count: number;
  speaker_id: string | null;
}
export interface SpeakerSummary {
  groups: SpeakerGroup[];
  needs_review: number;
  created: number;
  speaker_count: number | null;
  observed: number;
  ignored_groups: number;
}
export interface Person {
  id: string;
  name: string;
  samples: number;
  enabled: boolean;
  seconds: number;
  created: number;
}
export interface SummaryCitation {
  segment_id: string;
  start_ms: number;
  end_ms: number;
  quote: string;
}
export interface SummaryItem {
  id: string;
  kind: "summary" | "decision" | "action";
  text: string;
  owner: string | null;
  deadline: string | null;
  commitment_quote: string | null;
  citations: SummaryCitation[];
}
export interface SummaryResult {
  items: SummaryItem[];
  model: string;
  source_revision: number;
  generated: number;
  chunk_count: number;
  covered_segments: number;
  total_segments: number;
}
export interface Project extends ProjectSummary {
  summary: SummaryResult | null;
  summary_stale: boolean;
  speaker_summary: SpeakerSummary | null;
  transcript: Transcript | null;
  captions: Track | null;
  captions_stale: boolean;
  media_path: string;
  media_info: { has_video: boolean };
  warnings: { cue_id: string; reasons: string[] }[];
}
export interface Job {
  id: string;
  project_id: string;
  title: string;
  status: string;
  stage: string;
  attempt: number;
  processed_ms: number | null;
  preview?: { start_ms: number; end_ms: number; text: string }[];
  error: string | null;
  created: number;
  started: number | null;
}
export interface ModelStatus {
  available: boolean;
  runtime_available: boolean;
  model: { name: string; path: string; size_bytes: number; engine: string } | null;
  speaker_model: { name: string; voiceprint?: boolean } | null;
  diarization_available: boolean;
  summary_available: boolean;
  summary_model: { name: string; present: boolean } | null;
  summary_server: boolean;
}
export interface AppStatus {
  version: string;
  data_dir: string;
  models: ModelStatus;
  glossary: string;
  hardware: {
    cores: number;
    memory_gb: number;
    cuda: boolean;
    apple_silicon: boolean;
    concurrent_stages: boolean;
  };
}
