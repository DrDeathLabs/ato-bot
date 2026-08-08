export const CYBER_ASSISTANT_EVENT = 'open-cyber-assistant'

export function openCyberAssistant(detail = {}) {
  window.dispatchEvent(new CustomEvent(CYBER_ASSISTANT_EVENT, { detail }))
}
