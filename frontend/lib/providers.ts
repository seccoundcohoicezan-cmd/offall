export const PROVIDER_META: Record<string, { label: string; color: string; short: string }> = {
  anthropic: { label: "Claude", color: "#e8774a", short: "C" },
  openai: { label: "OpenAI", color: "#10a37f", short: "O" },
  gemini: { label: "Gemini", color: "#4f7cff", short: "G" },
  groq: { label: "Groq", color: "#f55036", short: "Q" },
  openrouter: { label: "OpenRouter", color: "#8b5cf6", short: "R" },
  mistral: { label: "Mistral", color: "#ff8c1a", short: "M" },
  ollama: { label: "Ollama", color: "#94a3b8", short: "L" },
  "9router": { label: "9Router", color: "#0ea5e9", short: "9" },
  openai_compatible: { label: "OpenAI-compatible", color: "#64748b", short: "AI" },
  mock: { label: "Mock", color: "#22d3ee", short: "D" },
};

export const PROVIDER_OPTIONS = [
  { value: "anthropic", label: "Claude (Anthropic)" },
  { value: "openai", label: "OpenAI" },
  { value: "gemini", label: "Google Gemini" },
  { value: "groq", label: "Groq" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "mistral", label: "Mistral" },
  { value: "ollama", label: "Ollama (lokal)" },
  { value: "9router", label: "9Router (satu endpoint, banyak model)" },
  { value: "openai_compatible", label: "OpenAI-compatible (custom endpoint)" },
  { value: "mock", label: "Mock (demo, tanpa biaya)" },
];

/** Gateways whose model list comes from the endpoint itself (sync / add by hand). */
export const CUSTOM_MODEL_PROVIDERS = new Set(["9router", "openai_compatible"]);
export const KEYLESS_PROVIDERS = new Set(["ollama", "9router", "openai_compatible"]);
/** Providers where the user must point OFALL at an address (gateway / self-hosted). */
export const URL_PROVIDERS = new Set(["9router", "openai_compatible", "ollama"]);
