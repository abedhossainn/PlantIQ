import type { Conversation } from "@/types";

// Strip inline citation references appended by the LLM, e.g. [Doc Title, Page 21]
export function stripInlineCitations(content: string): string {
  return content.replace(/\s*\[[^\]]*,\s*Page[s]?\s+[\d\u2013-]+[^\]]*\]/gi, "").trim();
}

export function formatConversationTimestamp(value?: string | null): string {
  if (!value) return "No messages yet";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Recently updated";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function getConversationDisplayTitle(conversation: Conversation): string {
  const title = conversation.title?.trim();
  if (title && title !== "New Conversation") {
    return title;
  }

  const preview = conversation.lastMessagePreview?.trim();
  if (preview) {
    return preview.length > 64 ? `${preview.slice(0, 61).trimEnd()}...` : preview;
  }

  return "New Conversation";
}

export function getInitials(name: string): string {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase();
}
