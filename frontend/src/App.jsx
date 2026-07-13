import { useStream } from "./hooks/useStream";
import { ChatInput } from "./components/ChatInput";
import { MessageList } from "./components/MessageList";
import "./App.css";

export default function App() {
  const { messages, status, sendQuery, respondToConfirmation } = useStream();
  const isStreaming = status === "streaming";
  const isAwaitingConfirmation = status === "awaiting_confirmation";

  return (
    <div className="app">
      <header className="app-header">
        <h1>WanderWise ✈️</h1>
        <p>AI travel planning with real booking, calendar holds &amp; drafted email</p>
      </header>

      <main className="app-main">
        <MessageList messages={messages} onRespondToConfirmation={respondToConfirmation} />
      </main>

      <footer className="app-footer">
        <ChatInput onSend={sendQuery} disabled={isStreaming || isAwaitingConfirmation} />
        {isStreaming && <p className="status">Thinking…</p>}
        {isAwaitingConfirmation && <p className="status">Waiting for your confirmation above…</p>}
      </footer>
    </div>
  );
}
