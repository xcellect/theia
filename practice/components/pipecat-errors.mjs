import messages from "./pipecat-error-messages.json";

/** The browser never renders provider exception messages or response bodies. */
export const UNKNOWN_PIPECAT_ERROR = "The Pipecat session stopped. Check the Python server terminal for its provider error code, then start a new session.";

export const PIPECAT_ERROR_MESSAGES = Object.freeze(messages);

/**
 * Decode only the backend's allowlisted marker from an RTVI error event.
 * The SDK callback receives RTVIMessage, with the error in data.error. Error
 * descriptions following the marker are ignored, even if a provider leaked one.
 * @param {unknown} event
 * @returns {string}
 */
export function pipecatErrorMessage(event) {
  if (!event || typeof event !== "object" || !("type" in event) || event.type !== "error" || !("data" in event)) return UNKNOWN_PIPECAT_ERROR;
  const data = event.data;
  if (!data || typeof data !== "object" || !("error" in data) || typeof data.error !== "string") return UNKNOWN_PIPECAT_ERROR;
  const match = /^\[PIPECAT:(DEEPGRAM|SAMBANOVA|HUME|PIPELINE|GENERALCOMPUTE|GRADIUM_STT|GRADIUM_TTS):(AUTH|QUOTA|MODEL|VOICE|TIMEOUT|NETWORK|UNKNOWN)\](?:$| )/.exec(data.error);
  if (!match) return UNKNOWN_PIPECAT_ERROR;
  const code = `${match[1]}:${match[2]}`;
  return Object.prototype.hasOwnProperty.call(PIPECAT_ERROR_MESSAGES, code)
    ? PIPECAT_ERROR_MESSAGES[/** @type {keyof typeof PIPECAT_ERROR_MESSAGES} */ (code)]
    : UNKNOWN_PIPECAT_ERROR;
}
