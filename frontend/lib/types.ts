export type KeyStatus = "active" | "cooling_down" | "exhausted" | "invalid" | "disabled";
export type JobStatusName = "queued" | "running" | "waiting_quota" | "done" | "failed" | "cancelled";
export type Strategy = "fill_first" | "round_robin" | "least_used";
export type SaveMode = "off" | "normal" | "aggressive";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface User {
  id: string;
  email: string;
  role: string;
  created_at: string;
}

export interface ProviderKey {
  id: string;
  label: string;
  key_hint: string;
  status: KeyStatus;
  priority: number;
  cooldown_until: string | null;
  reset_at: string | null;
  tokens_used_today: number;
  daily_token_quota: number | null;
  last_used_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface Provider {
  id: string;
  name: string;
  display_name: string;
  base_url: string | null;
  rotation_strategy: Strategy;
  created_at: string;
  keys: ProviderKey[];
  status_counts: Record<KeyStatus, number>;
  usable_keys: number;
}

export interface Model {
  id: string;
  provider: string;
  provider_display: string;
  model_name: string;
  display_name: string;
  tier: "strong" | "cheap";
  is_enabled: boolean;
  cost_in: number;
  cost_out: number;
  context_window: number;
  favorite: boolean;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  instructions: string;
  default_model: string;
  is_enabled: boolean;
  created_at: string;
}

export interface Chat {
  id: string;
  title: string;
  default_model: string;
  mode: string;
  agent_id: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  model_used: string | null;
  tokens_in: number;
  tokens_out: number;
  tokens_saved: number;
  cached: boolean;
  created_at: string;
}

export interface Job {
  id: string;
  chat_id: string;
  model_requested: string;
  model_used: string | null;
  status: JobStatusName;
  partial_output: string;
  error: string | null;
  attempts: number;
  tokens_saved: number;
  retry_at: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result_message_id: string | null;
}

export interface UserSettings {
  save_mode: SaveMode;
  max_tokens: number;
  allow_fallback: boolean;
  fallback_order: string[];
  favorite_models: string[];
  system_prompt: string;
  notify_telegram_chat_id: string;
  notify_webpush: boolean;
  vapid_public_key: string;
  telegram_enabled: boolean;
}

export interface UsageTotals {
  tokens_in: number;
  tokens_out: number;
  tokens_saved: number;
  cost: number;
  requests: number;
  cache_hits: number;
  cache_hit_rate: number;
  saving_pct: number;
}

export interface UsageSummary {
  days: number;
  total: UsageTotals;
  per_day: (UsageTotals & { day: string })[];
  per_provider: (UsageTotals & { provider: string })[];
  per_key: (UsageTotals & { key_id: string; label: string; key_hint: string; provider: string })[];
}
