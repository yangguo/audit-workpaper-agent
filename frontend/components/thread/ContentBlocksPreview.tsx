import React from "react";
import { MultimodalPreview } from "./MultimodalPreview";

interface ContentBlock {
  type: string;
  text?: string;
  metadata?: { name?: string; filename?: string };
}

interface ContentBlocksPreviewProps {
  blocks: ContentBlock[];
  onRemove: (index: number) => void;
}

export const ContentBlocksPreview: React.FC<ContentBlocksPreviewProps> = ({
  blocks,
  onRemove,
}) => {
  if (blocks.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 p-3.5 pb-0">
      {blocks.map((block, idx) => (
        <MultimodalPreview
          key={idx}
          block={block}
          removable
          onRemove={() => onRemove(idx)}
          size="sm"
        />
      ))}
    </div>
  );
};
