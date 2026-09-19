import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// Next bundles the JSON import for the browser. Inline that same table for the
// Node test runner, retaining Node 20.9 support across JSON import syntax changes.
const messages = JSON.parse(await readFile(new URL("../components/pipecat-error-messages.json", import.meta.url), "utf8"));
const source = (await readFile(new URL("../components/pipecat-errors.mjs", import.meta.url), "utf8"))
  .replace('import messages from "./pipecat-error-messages.json";', `const messages = ${JSON.stringify(messages)};`);
const { pipecatErrorMessage, UNKNOWN_PIPECAT_ERROR } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

const event = (error) => ({ id: "error-1", label: "rtvi-ai", type: "error", data: { error, fatal: true } });

test("Pipecat provider errors identify the setting the user can correct", () => {
  assert.equal(pipecatErrorMessage(event("[PIPECAT:DEEPGRAM:AUTH]")), "Deepgram STT rejected the API key or permissions. Check DEEPGRAM_API_KEY and account access, then restart Pipecat.");
  assert.equal(pipecatErrorMessage(event("[PIPECAT:SAMBANOVA:MODEL]")), "SambaNova could not use the configured model. Check SAMBANOVA_MODEL and model access, then restart Pipecat.");
  assert.equal(pipecatErrorMessage(event("[PIPECAT:HUME:VOICE]")), "Hume TTS could not use the selected voice. Choose a TTS voice ID accessible to this account, update HUME_VOICE_ID, and restart Pipecat.");
});

test("Pipecat billing failures explicitly direct the user to billing and remaining credits", () => {
  const result = pipecatErrorMessage(event("[PIPECAT:SAMBANOVA:QUOTA] HTTP 402 body that must be ignored"));
  assert.equal(result, "SambaNova reported a billing, credit, quota, or rate limit. Check billing, remaining credits, and limits in the provider dashboard, then retry.");
  assert.doesNotMatch(result, /HTTP 402|body/);
});

test("Pipecat browser descriptions match the complete shared terminal message table", () => {
  assert.equal(Object.keys(messages).length, 49);
  for (const [code, message] of Object.entries(messages)) {
    assert.equal(pipecatErrorMessage(event(`[PIPECAT:${code}] untrusted suffix`)), message);
  }
});

test("Gradium and General Compute errors point to their own configuration without leaking provider text", () => {
  const raw = "secret-new-provider-value HTTP response body";
  for (const [code, setting] of [
    ["GENERALCOMPUTE:AUTH", "GENERALCOMPUTE_API_KEY"],
    ["GENERALCOMPUTE:MODEL", "GENERALCOMPUTE_MODEL"],
    ["GRADIUM_STT:AUTH", "GRADIUM_API_KEY"],
    ["GRADIUM_TTS:AUTH", "GRADIUM_API_KEY"],
    ["GRADIUM_TTS:VOICE", "GRADIUM_VOICE_ID"],
  ]) {
    const result = pipecatErrorMessage(event(`[PIPECAT:${code}] ${raw}`));
    assert.ok(result.includes(setting));
    assert.doesNotMatch(result, /secret-new-provider-value|response body|SAMBANOVA|DEEPGRAM|HUME_API_KEY/);
  }
  assert.match(pipecatErrorMessage(event("[PIPECAT:GENERALCOMPUTE:QUOTA]")), /General Compute.*billing.*remaining credits/);
  assert.equal(pipecatErrorMessage(event("[PIPECAT:GRADIUM:AUTH]")), UNKNOWN_PIPECAT_ERROR);
});

test("Pipecat error descriptions come from fixed messages, never the provider suffix", () => {
  const raw = "Bearer secret-test-value <script>alert('provider-response')</script>";
  const result = pipecatErrorMessage(event(`[PIPECAT:HUME:VOICE] ${raw}`));
  assert.match(result, /HUME_VOICE_ID/);
  assert.doesNotMatch(result, /secret-test-value|script|provider-response|Bearer/);
  assert.equal(pipecatErrorMessage(event(raw)), UNKNOWN_PIPECAT_ERROR);
  assert.equal(pipecatErrorMessage(event(`${raw} [PIPECAT:HUME:VOICE]`)), UNKNOWN_PIPECAT_ERROR);
});

test("Pipecat rejects unknown or malformed error codes rather than guessing a provider", () => {
  for (const value of [
    "[PIPECAT:OPENAI:AUTH]",
    "[PIPECAT:HUME:SECRET]",
    "[PIPECAT:__proto__:AUTH]",
    "[PIPECAT:hume:VOICE]",
    " [PIPECAT:HUME:VOICE]",
    "[PIPECAT:HUME:VOICE]unseparated-provider-text",
    "[PIPECAT:HUME:VOICE]\nraw-response",
    "PIPECAT:HUME:VOICE",
  ]) assert.equal(pipecatErrorMessage(event(value)), UNKNOWN_PIPECAT_ERROR);
});

test("Pipecat only accepts the SDK's RTVI error event data.error field", () => {
  const code = "[PIPECAT:HUME:VOICE]";
  for (const value of [null, undefined, 1, "raw provider secret", new Error(code), [], {},
    { error: code }, { type: "error", data: null }, { type: "error", data: { error: {} } },
    { type: "error", data: { message: code } }, { type: "error-response", data: { error: code } },
    { type: "server-message", data: { error: code } },
  ]) assert.equal(pipecatErrorMessage(value), UNKNOWN_PIPECAT_ERROR);
});
