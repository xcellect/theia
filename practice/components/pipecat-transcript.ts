export type PipecatLine = { id: string; role: "You" | "Assistant"; text: string; interim: boolean };
export type PipecatTranscriptEvent =
  | { type: "user"; text: string; final: boolean; id: string }
  | { type: "bot"; text: string; id: string };

// Partial recognition replaces the current utterance; TTS progress updates
// replace their segment instead of duplicating each sentence in the transcript.
export function updatePipecatTranscript(lines: PipecatLine[], event: PipecatTranscriptEvent): PipecatLine[] {
  const text = event.text.trim().slice(0, 8_000);
  if (!text) return lines;
  const id = `${event.type}:${event.id}`;
  const line: PipecatLine = { id, role: event.type === "user" ? "You" : "Assistant", text, interim: event.type === "user" && !event.final };
  const index = lines.findIndex((item) => item.id === id);
  const next = index < 0 ? [...lines, line] : lines.map((item, at) => at === index ? line : item);
  return next.slice(-200);
}
