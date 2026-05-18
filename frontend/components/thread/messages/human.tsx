import { getContentString } from "../utils";
import { cn } from "@/lib/utils";
import { MultimodalPreview } from "@/components/thread/MultimodalPreview";

export function HumanMessage({
  message,
}: {
  message: { id: string; type: string; content: string | Array<{ type: string; text?: string; metadata?: { name?: string } }> };
  isLoading: boolean;
}) {
  const contentString = getContentString(message.content);

  // Extract file blocks from content array
  const fileBlocks = Array.isArray(message.content)
    ? message.content.filter((c: any) => c.type === "text" && c.metadata?.name)
    : [];

  return (
    <div className="group ml-auto flex items-center gap-2">
      <div className="flex flex-col gap-2">
        {/* Render attached files */}
        {fileBlocks.length > 0 && (
          <div className="flex flex-wrap items-end justify-end gap-2">
            {fileBlocks.map((block: any, idx: number) => (
              <MultimodalPreview
                key={idx}
                block={block}
                size="md"
              />
            ))}
          </div>
        )}
        {contentString && (
          <p className="bg-muted ml-auto w-fit rounded-3xl px-4 py-2 text-right whitespace-pre-wrap">
            {contentString}
          </p>
        )}
      </div>
    </div>
  );
}
