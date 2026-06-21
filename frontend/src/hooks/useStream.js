import { useCallback, useState } from "react";
import { streamChat } from "../api/chat";

/**
 * Manages a streaming chat session.
 *
 * Returns:
 *   messages  — array of { role, text, meta? } objects
 *   status    — "idle" | "streaming" | "done" | "error"
 *   sendQuery — function to start a new query
 */
export function useStream() {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState("idle");

  const appendMessage = (msg) =>
    setMessages((prev) => [...prev, msg]);

  const sendQuery = useCallback(async (query) => {
    if (!query.trim()) return;

    appendMessage({ role: "user", text: query });
    setStatus("streaming");

    // Placeholder assistant message updated as progress arrives
    appendMessage({ role: "assistant", text: "", progress: [] });

    try {
      for await (const { event, data } of streamChat(query)) {
        if (event === "progress") {
          setMessages((prev) => {
            const updated = [...prev];
            const last = { ...updated[updated.length - 1] };
            last.progress = [...(last.progress || []), data.node];
            last.text = `Processing: ${last.progress.join(" → ")}…`;
            updated[updated.length - 1] = last;
            return updated;
          });
        } else if (event === "done") {
          setMessages((prev) => {
            const updated = [...prev];
            const last = { ...updated[updated.length - 1] };
            last.text = data.summary || "(no summary)";
            last.progress = undefined;
            last.meta = {
              location: data.location,
              routerTier: data.router_tier,
              assembleTier: data.assemble_tier,
              degraded: data.degraded,
            };
            updated[updated.length - 1] = last;
            return updated;
          });
          setStatus("done");
        }
      }
    } catch (err) {
      setMessages((prev) => {
        const updated = [...prev];
        const last = { ...updated[updated.length - 1] };
        last.text = `Error: ${err.message}`;
        last.error = true;
        updated[updated.length - 1] = last;
        return updated;
      });
      setStatus("error");
    }
  }, []);

  return { messages, status, sendQuery };
}
