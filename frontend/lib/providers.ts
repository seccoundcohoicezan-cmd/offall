export const PROVIDER_META: Record<string, { label: string; color: string; short: string }> = {
  anthropic: { label: "Claude", color: "#e8774a", short: "C" },
  openai: { label: "OpenAI", color: "#10a37f", short: "O" },
  gemini: { label: "Gemini", color: "#4f7cff", short: "G" },
  groq: { label: "Groq", color: "#f55036", short: "Q" },
  openrouter: { label: "OpenRouter", color: "#8b5cf6", short: "R" },
  mistral: { label: "Mistral", color: "#ff8c1a", short: "M" },
  ollama: { label: "Ollama", color: "#94a3b8", short: "L" },
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
  { value: "mock", label: "Mock (demo, tanpa biaya)" },
];
