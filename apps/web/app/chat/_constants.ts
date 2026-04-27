export interface ChatDiscoveryPreferences {
  conversationSearch: string;
  conversationWorkspaceFilter: string;
  showPinnedOnly: boolean;
}

export const DEFAULT_CONVERSATION_WORKSPACE_FILTER = "all";

export const WORKSPACE_OPTIONS = [
  "Power Block",
  "Pre Treatment",
  "Liquefaction",
  "OSBL (Outside Battery Limits)",
  "Maintenance",
  "Instrumentation",
  "DCS (Distributed Control System)",
  "Electrical",
  "Mechanical",
];

export function getChatDiscoveryPreferencesKey(userId: string): string {
  return `chat_discovery_preferences:${userId}`;
}
