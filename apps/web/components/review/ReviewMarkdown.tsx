import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ReviewMarkdownProps {
  content: string;
  className?: string;
}

export function stripHtmlComments(content: string): string {
  return content.replace(/<!--[\s\S]*?-->/g, "").trim();
}

export function ReviewMarkdown({ content, className }: ReviewMarkdownProps) {
  const cleanedContent = stripHtmlComments(content);

  if (!cleanedContent) {
    return null;
  }

  return (
    <div className={className}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="text-xl font-bold mt-0 mb-3 text-foreground">{children}</h1>,
          h2: ({ children }) => <h2 className="text-base font-semibold mt-4 mb-2">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-semibold mt-3 mb-1">{children}</h3>,
          p: ({ children }) => <p className="text-sm leading-relaxed mb-3 text-foreground/90">{children}</p>,
          ul: ({ children }) => <ul className="list-disc list-inside text-sm mb-3 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal list-inside text-sm mb-3 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="text-sm text-foreground/90">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          table: ({ children }) => (
            <div className="overflow-x-auto my-4 rounded-md border border-border">
              <table className="w-full text-xs border-collapse">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted/70">{children}</thead>,
          tbody: ({ children }) => <tbody className="divide-y divide-border">{children}</tbody>,
          tr: ({ children }) => <tr className="align-top">{children}</tr>,
          th: ({ children }) => <th className="border border-border px-3 py-2 text-left font-medium text-foreground">{children}</th>,
          td: ({ children }) => <td className="border border-border px-3 py-2 align-top text-foreground/90">{children}</td>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-amber-400/50 pl-4 my-3 text-muted-foreground italic text-sm">
              {children}
            </blockquote>
          ),
          code: ({ children }) => <code className="bg-muted px-1 rounded text-xs font-mono">{children}</code>,
        }}
      >
        {cleanedContent}
      </ReactMarkdown>
    </div>
  );
}