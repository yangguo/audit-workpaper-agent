import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import type { AnalysisSection } from "./types";

const markdownComponents: any = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mt-2 text-sm leading-7 text-slate-700">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
      {children}
    </ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-slate-700">
      {children}
    </ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li>{children}</li>
  ),
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h4 className="mt-4 text-base font-semibold text-slate-900">{children}</h4>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h4 className="mt-4 text-base font-semibold text-slate-900">{children}</h4>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h5 className="mt-3 text-sm font-semibold text-slate-900">{children}</h5>
  ),
  h4: ({ children }: { children?: React.ReactNode }) => (
    <h6 className="mt-3 text-sm font-semibold text-slate-900">{children}</h6>
  ),
  code: ({
    className,
    children,
  }: {
    className?: string;
    children?: React.ReactNode;
  }) => {
    const isCodeBlock = /language-/.test(className || "");
    return (
      <code
        className={
          isCodeBlock
            ? "font-mono text-xs text-white"
            : "rounded bg-slate-100 px-1 py-0.5 text-xs font-medium text-slate-800"
        }
      >
        {children}
      </code>
    );
  },
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3">
      {children}
    </pre>
  ),
  table: ({ children }: { children?: React.ReactNode }) => (
    <table className="mt-2 w-full border-collapse text-sm text-slate-700">
      {children}
    </table>
  ),
  th: ({ children }: { children?: React.ReactNode }) => (
    <th className="border bg-slate-100 px-2 py-1 text-left font-semibold">
      {children}
    </th>
  ),
  td: ({ children }: { children?: React.ReactNode }) => (
    <td className="border px-2 py-1">{children}</td>
  ),
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="mt-2 border-l-4 border-slate-300 pl-3 text-sm italic text-slate-600">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-4 border-slate-200" />,
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href}
      className="text-sm text-primary underline underline-offset-2"
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
    </a>
  ),
};

export function AnalysisResultPanel({
  sections,
  runningMessage,
  errorMessage,
}: {
  sections: AnalysisSection[];
  runningMessage?: string;
  errorMessage?: string;
}) {
  return (
    <section className="rounded-2xl border bg-white p-5">
      <h2 className="text-base font-semibold">分析结果</h2>
      {errorMessage ? (
        <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {errorMessage}
          <p className="mt-2 text-muted-foreground">
            可重试当前任务，或修改输入材料后重新发起。
          </p>
        </div>
      ) : null}
      {runningMessage ? (
        <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-700">
          {runningMessage}
        </div>
      ) : null}
      <div className="mt-4 space-y-5">
        {sections.map((section) => (
          <article key={section.title}>
            <h3 className="text-sm font-semibold text-slate-900">
              {section.title}
            </h3>
            <div className="markdown-body">
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex]}
                components={markdownComponents}
              >
                {section.body}
              </ReactMarkdown>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
