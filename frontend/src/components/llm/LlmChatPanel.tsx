import { useState } from "react";
import { Icon } from "../ui/Icon";

interface ChatMessage {
  role: "user" | "assistant" | "error";
  text: string;
}

interface LlmChatPanelProps {
  onSend: (query: string) => Promise<string>;
  placeholder?: string;
}

const SUMMARY_QUERY = "Résume ce contenu en quelques phrases, en français.";

/**
 * Chat/analyse LLM à la demande. `onSend` porte la logique de ce qui est envoyé
 * (une page ou un lot) — ce composant ne gère que la conversation. Une nouvelle
 * collecte doit remonter ce composant avec une `key` différente côté parent pour
 * repartir d'une conversation vide.
 */
export function LlmChatPanel({ onSend, placeholder = "Poser une question sur ce contenu..." }: LlmChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  async function send(query: string) {
    if (!query.trim() || sending) return;
    setSending(true);
    setMessages((prev) => [...prev, { role: "user", text: query }]);
    try {
      const response = await onSend(query);
      setMessages((prev) => [...prev, { role: "assistant", text: response }]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "error", text: err instanceof Error ? err.message : "Erreur inconnue" },
      ]);
    } finally {
      setSending(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const query = input;
    setInput("");
    void send(query);
  }

  return (
    <div className="rounded-lg border border-outline-variant bg-surface-container p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="flex items-center gap-2 font-headline-md text-headline-md text-on-surface">
          <Icon name="smart_toy" className="text-primary" />
          Analyse LLM
        </h3>
        <button
          onClick={() => void send(SUMMARY_QUERY)}
          disabled={sending}
          className="flex items-center gap-2 rounded border border-outline-variant px-3 py-1.5 text-body-sm text-on-surface-variant transition-colors hover:bg-surface-bright disabled:opacity-50"
        >
          <Icon name="summarize" className="text-16" />
          Résumer
        </button>
      </div>

      <div className="custom-scrollbar mb-3 max-h-80 min-h-24 space-y-3 overflow-y-auto">
        {messages.length === 0 && (
          <p className="text-body-sm text-on-surface-variant">
            Pose une question sur le contenu extrait, ou clique sur "Résumer".
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={msg.role === "user" ? "text-right" : "text-left"}>
            <div
              className={`inline-block max-w-[85%] whitespace-pre-wrap rounded px-3 py-2 text-body-sm ${
                msg.role === "user"
                  ? "bg-primary/20 text-on-surface"
                  : msg.role === "error"
                    ? "border border-error/40 bg-error-container/20 text-error"
                    : "border border-outline-variant bg-background text-on-surface-variant"
              }`}
            >
              {msg.text}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex items-center gap-2 text-body-sm text-on-surface-variant">
            <Icon name="progress_activity" className="animate-spin text-16" />
            Le modèle réfléchit...
          </div>
        )}
      </div>

      <form onSubmit={(e) => void handleSubmit(e)} className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          disabled={sending}
          className="flex-1 rounded border border-outline-variant bg-background px-3 py-2 text-body-sm outline-none focus:border-primary disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="rounded bg-primary px-4 py-2 text-body-sm font-bold text-on-primary transition-all hover:opacity-90 disabled:opacity-50"
        >
          <Icon name="send" className="text-18" />
        </button>
      </form>
    </div>
  );
}
