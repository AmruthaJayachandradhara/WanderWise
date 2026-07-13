function ConfirmationGate({ interrupt, onRespond }) {
  const { pendingActions, emailDraft } = interrupt;
  return (
    <div className="confirmation-gate">
      <p className="confirmation-gate-title">⏸ Confirmation needed before booking</p>
      {pendingActions.length > 0 && (
        <ul className="pending-actions">
          {pendingActions.map((action, i) => (
            <li key={i}>{action.description || action.action_type}</li>
          ))}
        </ul>
      )}
      {emailDraft && (
        <div className="email-draft">
          <p className="email-draft-subject">✉ {emailDraft.subject}</p>
          <p className="email-draft-body">{emailDraft.body}</p>
        </div>
      )}
      <div className="confirmation-gate-actions">
        <button className="approve-btn" onClick={() => onRespond(true)}>Approve</button>
        <button className="decline-btn" onClick={() => onRespond(false)}>Decline</button>
      </div>
    </div>
  );
}

function ReservationsAndActions({ meta }) {
  const { confirmations, calendarIcs, emailStatus } = meta;
  const hasConfirmations = confirmations && confirmations.length > 0;
  if (!hasConfirmations && !calendarIcs && (!emailStatus || emailStatus === "none")) {
    return null;
  }
  return (
    <div className="reservations">
      {hasConfirmations && (
        <ul className="confirmations-list">
          {confirmations.map((c, i) => (
            <li key={i}>
              ✅ {c.booking_type}: {c.description} — <code>{c.confirmation_id}</code>
            </li>
          ))}
        </ul>
      )}
      {calendarIcs && <p className="action-note">📅 Calendar hold created</p>}
      {emailStatus === "approved" && <p className="action-note">✉ Itinerary email approved</p>}
      {emailStatus === "discarded" && <p className="action-note">✉ Itinerary email discarded</p>}
    </div>
  );
}

export function MessageList({ messages, onRespondToConfirmation }) {
  return (
    <div className="message-list">
      {messages.map((msg, i) => (
        <div key={i} className={`message message-${msg.role}`}>
          <span className="message-role">{msg.role === "user" ? "You" : "WanderWise"}</span>
          <p className="message-text">{msg.text}</p>

          {msg.interrupt && (
            <ConfirmationGate interrupt={msg.interrupt} onRespond={onRespondToConfirmation} />
          )}

          {msg.meta && <ReservationsAndActions meta={msg.meta} />}

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
