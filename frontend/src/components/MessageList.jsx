export function MessageList({ messages }) {
  return (
    <div className="message-list">
      {messages.map((msg, i) => (
        <div key={i} className={`message message-${msg.role}`}>
          <span className="message-role">{msg.role === "user" ? "You" : "WanderWise"}</span>
          <p className="message-text">{msg.text}</p>

          {/* Debug: show which tiers ran — makes routing visible in the demo */}
          {msg.meta && (
            <div className="message-meta">
              <span>📍 {msg.meta.location}</span>
              <span> · router: {msg.meta.routerTier}</span>
              <span> · assemble: {msg.meta.assembleTier}</span>
              {msg.meta.degraded && <span className="degraded"> · ⚠ degraded</span>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
