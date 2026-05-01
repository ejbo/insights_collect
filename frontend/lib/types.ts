export type Report = {
  id: number;
  title: string;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  focus_topics: string[];
  time_range_start: string;
  time_range_end: string;
  md_path?: string | null;
  outline_json_path?: string | null;
  pdf_path?: string | null;
  total_cost_usd: number;
  total_tokens: number;
  error?: string | null;
  created_at: string;
  finished_at?: string | null;
};

export type ProviderCredentialView = {
  provider: string;
  api_key: string;          // plaintext (local-self-use)
  has_key: boolean;
  base_url?: string | null;
  default_model?: string | null;
  enabled: boolean;
  last_tested_at?: string | null;
  test_status?: string | null;
  test_message?: string | null;
};

export type ReportTemplate = {
  id: number;
  name: string;
  kind: "md_report" | "ppt_outline" | "section";
  prompt_template: string;
  description?: string | null;
  jinja_vars?: Record<string, any> | null;
  is_default: boolean;
  is_builtin: boolean;
  version: number;
  created_at: string;
  updated_at: string;
};

export type Stats = {
  experts: number;
  viewpoints: number;
  events: number;
  sources: number;
  topics: number;
  reports: number;
};

export type AgentRun = {
  id: number;
  report_id: number;
  graph_node: string;
  state_out: Record<string, any> | null;
  tokens: number;
  cost_usd: number;
  started_at: string;
  finished_at: string | null;
  error: string | null;
};

export type GraphMeta = {
  nodes: { name: string; label: string }[];
};

export type ClaudeOptions = {
  effort: "low" | "medium" | "high" | "xhigh" | "max";
  max_uses: number;
  max_fetches: number;
  task_budget_tokens: number | null;
  thinking_display: "summarized" | "omitted";
  enable_web_search: boolean;
  enable_web_fetch: boolean;
  allowed_domains?: string[] | null;
  blocked_domains?: string[] | null;
  user_location_country?: string | null;
  model?: string | null;
};

export type GrokOptions = {
  model: string | null;
  allowed_x_handles?: string[] | null;
  excluded_x_handles?: string[] | null;
  enable_image_understanding: boolean;
  enable_video_understanding: boolean;
  enable_dual_pass: boolean;
  max_candidate_handles: number;
};

export type GeminiOptions = {
  model: string | null;
  thinking_budget: number;          // -1 dynamic, 0 off, 128-32768 fixed
  temperature: number | null;
  max_output_tokens: number;
  enable_search: boolean;
  user_location_country?: string | null;
  max_search_queries: number;       // soft cap on google_search invocations
  max_grounding_chunks: number;     // cap on grounding_chunks persisted as SearchHits
};

export type QwenOptions = {
  model: string | null;
  enable_search: boolean;
  enable_thinking: boolean;
  search_strategy: "agent" | "agent_max";
  max_output_tokens: number;
};

export type ExpertSummary = {
  id: number;
  name: string;
  name_zh?: string | null;
  bio?: string | null;
  affiliations?: string[] | null;
  profile_urls?: string[] | null;
  domains?: string[] | null;
  updated_at: string;
  viewpoint_count: number;
  last_claim_at?: string | null;
};

export type ExpertDetail = ExpertSummary & {
  source_domains: { domain: string; count: number }[];
};

export type ExpertViewpoint = {
  id: number;
  expert_id: number;
  event_id?: number | null;
  source_id?: number | null;
  claim_who_role?: string | null;
  claim_when?: string | null;
  claim_where?: string | null;
  claim_what: string;
  claim_quote?: string | null;
  claim_medium?: string | null;
  claim_source_url?: string | null;
  claim_why_context?: string | null;
  claim_lang: string;
  confidence: number;
  ingested_at: string;
  source_domain?: string | null;
};

export type SearchHit = {
  id: number;
  report_id: number;
  provider_call_id: number | null;
  provider: string;
  kind: "web_search" | "web_fetch" | "citation" | "x_post";
  query: string | null;
  url: string | null;
  title: string | null;
  snippet: string | null;
  source_domain: string | null;
  page_age: string | null;
  citations: any[] | null;
  extra: { media_type?: "video" | "image" | "text" } | null;
  created_at: string;
};
