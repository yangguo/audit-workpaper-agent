import { useStreamContext } from "@/providers/Stream";
import { getContentString } from "../utils";
import { MarkdownText } from "../markdown-text";

function AssistantMessageLoading() {
  return (
    <div className="mr-auto flex items-start gap-2">
      <div className="bg-muted flex h-8 items-center gap-1 rounded-2xl px-4 py-2">
        <div className="bg-foreground/50 h-1.5 w-1.5 animate-[pulse_1.5s_ease-in-out_infinite] rounded-full"></div>
        <div className="bg-foreground/50 h-1.5 w-1.5 animate-[pulse_1.5s_ease-in-out_0.5s_infinite] rounded-full"></div>
        <div className="bg-foreground/50 h-1.5 w-1.5 animate-[pulse_1.5s_ease-in-out_1s_infinite] rounded-full"></div>
      </div>
    </div>
  );
}

function ToolCallDisplay({
  toolCalls,
}: {
  toolCalls: Array<{ name: string; id: string; args: Record<string, unknown> }>;
}) {
  return (
    <div className="my-2 space-y-2">
      {toolCalls.map((tc) => (
        <div
          key={tc.id}
          className="border border-border rounded-lg overflow-hidden bg-muted/30"
        >
          <div className="flex items-center gap-2 bg-muted px-3 py-1.5 text-xs font-medium text-muted-foreground">
            <svg className="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
            </svg>
            Tool: {tc.name}
          </div>
          {Object.keys(tc.args).length > 0 && (
            <div className="px-3 py-2 text-xs">
              <table className="w-full border-collapse">
                <tbody>
                  {Object.entries(tc.args).map(([key, value]) => (
                    <tr key={key} className="border-b border-border/50 last:border-0">
                      <td className="py-1 pr-3 font-medium text-muted-foreground whitespace-nowrap align-top">{key}</td>
                      <td className="py-1 break-all">{typeof value === "string" ? value : JSON.stringify(value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function AssistantMessage({
  message,
  isLoading,
}: {
  message: { id: string; type: string; content: string; tool_calls?: Array<{ name: string; id: string; args: Record<string, unknown> }> } | undefined;
  isLoading: boolean;
}) {
  if (!message) {
    return <AssistantMessageLoading />;
  }

  const contentString = typeof message.content === "string" ? message.content : getContentString(message.content as any);
  const hasToolCalls = message.tool_calls && message.tool_calls.length > 0;

  if (message.type === "tool") {
    return null;
  }

  return (
    <div className="group mr-auto flex w-full items-start gap-2">
      <div className="flex w-full flex-col gap-2">
        {contentString.length > 0 && (
          <div className="py-1">
            <MarkdownText>{contentString}</MarkdownText>
          </div>
        )}
        {hasToolCalls && <ToolCallDisplay toolCalls={message.tool_calls!} />}
      </div>
    </div>
  );
}

export { AssistantMessageLoading };
