import type { VoiceContextType } from "@humeai/voice-react";

export type TranscriptLine = { id: string; role: "You" | "Assistant"; text: string; interim: boolean };

export function transcriptLines(messages: VoiceContextType["messages"]): TranscriptLine[] {
  const lines = new Map<string, TranscriptLine>();
  for (const [index, message] of messages.entries()) {
    // The published quickstart contains an inverted filter. Include these events.
    if (message.type !== "user_message" && message.type !== "assistant_message") continue;
    const text = message.message.content?.trim();
    if (!text) continue;
    // SDK history already replaces provisional user transcripts in place. Identity
    // deduplication also avoids duplicate assistant audio/transcript events without
    // removing legitimate repeated phrases in separate turns.
    const id = message.type === "assistant_message"
      ? `assistant:${message.id || index}`
      : `user:${message.time.begin}`;
    lines.set(id, {
      id,
      role: message.type === "user_message" ? "You" : "Assistant",
      text,
      interim: message.type === "user_message" && message.interim,
    });
  }
  return Array.from(lines.values());
}

export const DEMO_TRANSCRIPT: TranscriptLine[] = [
  { id: "demo-1", role: "You", text: "Hello! I’m checking my setup before the hackathon.", interim: false },
  { id: "demo-2", role: "Assistant", text: "Let’s take it one step at a time. What would you like to test first?", interim: false },
  { id: "demo-3", role: "You", text: "I’d like to see both sides of the conversation here.", interim: false },
  { id: "demo-4", role: "Assistant", text: "This sample shows how your transcript will look. A real session still needs a microphone and a configured Hume account.", interim: false },
];
