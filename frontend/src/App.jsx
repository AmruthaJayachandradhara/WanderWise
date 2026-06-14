import { useStream } from "./hooks/useStream";
import { ChatInput } from "./components/ChatInput";
import { MessageList } from "./components/MessageList";
import "./App.css";

export default function App() {
  const { messages, status, sendQuery } = useStream();
  const isStreaming = status === "streaming";

  return (
    <div className="app">
      <header className="app-header">
        <h1>WanderWise ✈️</h1>
        <p>AI travel planning — Phase 1 skeleton</p>
      </header>

      <main className="app-main">
        <MessageList messages={messages} />
      </main>

      <footer className="app-footer">
        <ChatInput onSend={sendQuery} disabled={isStreaming} />
        {isStreaming && <p className="status">Thinking…</p>}
      </footer>
    </div>
  );
}
