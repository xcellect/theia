import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Compile just the pure helper so tests work on Node >=20.9 without experimental
// native TS execution or React. TypeScript 7 removed the old transpileModule API.
const directory = await mkdtemp(join(tmpdir(), "voice-transcript-test-"));
let compiled;
let pipecatCompiled;
try {
  await writeFile(join(directory, "tsconfig.json"), JSON.stringify({
    compilerOptions: { module: "ESNext", target: "ES2022", moduleResolution: "bundler", skipLibCheck: true, strict: true, rootDir: fileURLToPath(new URL("../components", import.meta.url)), outDir: directory },
    files: ["transcript.ts", "pipecat-transcript.ts"].map(name => fileURLToPath(new URL(`../components/${name}`, import.meta.url))),
  }));
  execFileSync(process.execPath, [fileURLToPath(new URL("../node_modules/typescript/bin/tsc", import.meta.url)), "--project", join(directory, "tsconfig.json")], { stdio: "pipe" });
  compiled = await readFile(join(directory, "transcript.js"), "utf8");
  pipecatCompiled = await readFile(join(directory, "pipecat-transcript.js"), "utf8");
} finally {
  await rm(directory, { recursive: true, force: true });
}
const { transcriptLines, DEMO_TRANSCRIPT } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const { updatePipecatTranscript } = await import(`data:text/javascript;base64,${Buffer.from(pipecatCompiled).toString("base64")}`);

const user = (text, begin, end, interim = false) => ({ type: "user_message", time: { begin, end }, interim, message: { role: "user", content: text } });
const assistant = (text, id) => ({ type: "assistant_message", id, message: { role: "assistant", content: text } });

test("includes both actual transcript event types in order and ignores control messages", () => {
  const lines = transcriptLines([
    { type: "socket_connected" }, user("Hello", 0, 100),
    { type: "chat_metadata", chatId: "demo-chat" }, assistant("Hi there", "a-1"),
    { type: "assistant_end" }, { type: "user_interruption" },
  ]);
  assert.deepEqual(lines.map(({ role, text }) => ({ role, text })), [{ role: "You", text: "Hello" }, { role: "Assistant", text: "Hi there" }]);
});

test("deduplicates an assistant identity without appending the same response", () => {
  assert.equal(transcriptLines([assistant("Hello", "a-1"), assistant("Hello", "a-1")]).length, 1);
});

test("replaces provisional user text by the final text for the same utterance", () => {
  const lines = transcriptLines([user("I would", 10, 100, true), user("I would like", 10, 150, true), user("I would like to test.", 10, 200)]);
  assert.deepEqual(lines, [{ id: "user:10", role: "You", text: "I would like to test.", interim: false }]);
});

test("preserves repeated phrases in separate user and assistant turns", () => {
  const lines = transcriptLines([user("Yes", 0, 10), assistant("Okay", "a-1"), user("Yes", 30, 40), assistant("Okay", "a-2")]);
  assert.equal(lines.length, 4);
  assert.equal(new Set(lines.map(({ id }) => id)).size, 4);
});

test("skips empty text and preserves distinct assistant messages without IDs", () => {
  assert.equal(transcriptLines([user("  ", 0, 10), assistant("First"), assistant("Second")]).length, 2);
});

test("sample transcript is deterministic and explicitly refers to a sample", () => {
  assert.equal(DEMO_TRANSCRIPT.length, 4);
  assert.match(DEMO_TRANSCRIPT.at(-1).text, /sample/);
  assert.ok(DEMO_TRANSCRIPT.every(({ id }) => id.startsWith("demo-")));
});

test("Pipecat interim text becomes final and preserves the next repeated utterance", () => {
  let lines = updatePipecatTranscript([], { type: "user", id: "1", text: "hello", final: false });
  lines = updatePipecatTranscript(lines, { type: "user", id: "1", text: "hello there", final: true });
  assert.equal(lines.length, 1);
  assert.equal(lines[0].text, "hello there");
  assert.equal(lines[0].interim, false);
  lines = updatePipecatTranscript(lines, { type: "user", id: "2", text: "hello there", final: true });
  assert.equal(lines.length, 2);
});

test("Pipecat bot segment updates do not duplicate speech or collide with user identities", () => {
  let lines = updatePipecatTranscript([], { type: "user", id: "1", text: "hi", final: true });
  lines = updatePipecatTranscript(lines, { type: "bot", id: "1", text: "Hello" });
  lines = updatePipecatTranscript(lines, { type: "bot", id: "1", text: "Hello there." });
  assert.deepEqual(lines.map(line => line.text), ["hi", "Hello there."]);
  assert.deepEqual(lines.map(line => line.role), ["You", "Assistant"]);
});

test("Pipecat transcript bounds history and individual messages", () => {
  let lines = [];
  for (let id = 0; id < 205; id++) lines = updatePipecatTranscript(lines, { type: "bot", id: String(id), text: "x".repeat(9000) });
  assert.equal(lines.length, 200);
  assert.equal(lines[0].id, "bot:5");
  assert.equal(lines[0].text.length, 8000);
  assert.deepEqual(updatePipecatTranscript(lines, { type: "bot", id: "ignored", text: "  " }), lines);
});
