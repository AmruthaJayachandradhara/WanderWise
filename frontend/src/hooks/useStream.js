import { useCallback, useState } from "react";
import { streamChat, resumeChat } from "../api/chat";

/**
 * Manages a streaming chat session, including the Phase 4 confirmation gate:
 * a run can pause mid-stream awaiting the user's approve/decline decision
 * on high-risk actions (booking, sending the drafted email) before it
 * completes with the final itinerary.
 *
 * Returns:
 *   messages            — array of { role, text, meta?, interrupt? } objects
 *   status              — "idle" | "streaming" | "awaiting_confirmation" | "done" | "error"
 *   sendQuery           — function to start a new query
 *   respondToConfirmation — function(approved: bool) to resume a paused run
 */
export function useStream() {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState("idle");

  const appendMessage = (msg) =>
    setMessages((prev) => [...prev, msg]);

  const updateLast = (patch) =>
    setMessages((prev) => {
      const updated = [...prev];
      const last = { ...updated[updated.length - 1], ...patch };
      updated[updated.length - 1] = last;
      return updated;
    });

  const consumeStream = useCallback(async (iterator) => {
    for await (const { event, data } of iterator) {
      if (event === "progress") {
        setMessages((prev) => {
          const updated = [...prev];
          const last = { ...updated[updated.length - 1] };
          last.progress = [...(last.progress || []), data.node];
          last.text = `Processing: ${last.progress.join(" → ")}…`;
          updated[updated.length - 1] = last;
          return updated;
        });
      } else if (event === "interrupt") {
        updateLast({
          text: "Review the actions below before I proceed.",
          progress: undefined,
          interrupt: {
            threadId: data.thread_id,
            pendingActions: data.pending_actions || [],
            emailDraft: data.email_draft,
          },
        });
        setStatus("awaiting_confirmation");
        return;
      } else if (event === "done") {
        updateLast({
          text: data.summary || "(no summary)",
          progress: undefined,
          interrupt: undefined,
          meta: {
            location: data.location,
            routerTier: data.router_tier,
            assembleTier: data.assemble_tier,
            degraded: data.degraded,
            confirmations: data.confirmations || [],
            calendarIcs: data.calendar_ics,
            emailDraft: data.email_draft,
            emailStatus: data.email_status,
          },
        });
        setStatus("done");
      }
    }
  }, []);

  const sendQuery = useCallback(async (query) => {
    if (!query.trim()) return;

    appendMessage({ role: "user", text: query });
    setStatus("streaming");

    // Placeholder assistant message updated as progress arrives
    appendMessage({ role: "assistant", text: "", progress: [] });

    try {
      await consumeStream(streamChat(query));
    } catch (err) {
      updateLast({ text: `Error: ${err.message}`, error: true });
      setStatus("error");
    }
  }, [consumeStream]);

  const respondToConfirmation = useCallback(async (approved) => {
    const last = messages[messages.length - 1];
    const threadId = last?.interrupt?.threadId;
    if (!threadId) return;

    updateLast({
      interrupt: undefined,
      text: approved ? "Booking approved — finalising your itinerary…" : "Declined — wrapping up without booking…",
    });
    setStatus("streaming");

    try {
      await consumeStream(resumeChat(threadId, approved));
    } catch (err) {
      updateLast({ text: `Error: ${err.message}`, error: true });
      setStatus("error");
    }
  }, [messages, consumeStream]);

  return { messages, status, sendQuery, respondToConfirmation };
}
