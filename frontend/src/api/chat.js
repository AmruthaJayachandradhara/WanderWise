/**
 * Sends a chat query and returns an EventSource-like async iterator
 * that yields parsed SSE events from the backend.
 *
 * Each yielded value is { event, data } where data is already JSON-parsed.
 */
export async function* streamChat(query, userId = null) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, user_id: userId }),
  });
  yield* parseSSE(response);
}

/**
 * Resumes a run paused at the confirmation gate (Phase 4 human-in-the-loop
 * booking/email gate) with the user's approve/decline decision. Streams the
 * remaining progress/done events the same way streamChat does.
 */
export async function* resumeChat(threadId, approved) {
  const response = await fetch("/api/chat/resume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, approved }),
  });
  yield* parseSSE(response);
}

async function* parseSSE(response) {
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop(); // keep incomplete last line

    let currentEvent = "message";
    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        const raw = line.slice(5).trim();
        try {
          yield { event: currentEvent, data: JSON.parse(raw) };
        } catch {
          yield { event: currentEvent, data: raw };
        }
        currentEvent = "message";
      }
    }
  }
}
