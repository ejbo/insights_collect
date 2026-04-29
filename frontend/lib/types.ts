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
