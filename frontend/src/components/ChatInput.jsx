import { useState } from "react";

export function ChatInput({ onSend, disabled }) {
  const [value, setValue] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!value.trim() || disabled) return;
    onSend(value.trim());
    setValue("");
  };

  return (
    <form onSubmit={handleSubmit} className="chat-input-form">
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Ask about the weather anywhere…"
        disabled={disabled}
        className="chat-input"
      />
      <button type="submit" disabled={disabled || !value.trim()} className="chat-send-btn">
        Send
      </button>
    </form>
  );
}
