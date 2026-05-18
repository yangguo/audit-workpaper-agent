type MessageContent = string | Array<{ type: string; text?: string; [key: string]: unknown }>;

export function getContentString(content: MessageContent): string {
  if (typeof content === "string") return content;
  const texts = content
    .filter((c): c is { type: "text"; text: string } => c.type === "text")
    .map((c) => c.text);
  return texts.join(" ");
}
