import type { Components } from "react-markdown";

export const SEVERITY_COLORS: Record<string, string> = {
  critical: "text-red-400 bg-red-400/10 border-red-400/30",
  high: "text-orange-400 bg-orange-400/10 border-orange-400/30",
  medium: "text-amber-400 bg-amber-400/10 border-amber-400/30",
  low: "text-zinc-400 bg-zinc-400/10 border-zinc-400/20",
};

/** Remove HTML comments embedded by the pipeline before rendering */
export function stripHtmlComments(content: string): string {
  return content.replace(/<!--[\s\S]*?-->/g, "").trim();
}

export const MARKDOWN_COMPONENTS: Partial<Components> = {
  h1({ children }) { return <h1 className="text-xl font-bold mt-0 mb-3 text-foreground">{children}</h1>; },
  h2({ children }) { return <h2 className="text-base font-semibold mt-4 mb-2">{children}</h2>; },
  h3({ children }) { return <h3 className="text-sm font-semibold mt-3 mb-1">{children}</h3>; },
  p({ children }) { return <p className="text-sm leading-relaxed mb-3 text-foreground/90">{children}</p>; },
  ul({ children }) { return <ul className="list-disc list-inside text-sm mb-3 space-y-1">{children}</ul>; },
  ol({ children }) { return <ol className="list-decimal list-inside text-sm mb-3 space-y-1">{children}</ol>; },
  li({ children }) { return <li className="text-sm text-foreground/90">{children}</li>; },
  strong({ children }) { return <strong className="font-semibold text-foreground">{children}</strong>; },
  table({ children }) {
    return (
      <div className="overflow-x-auto my-4">
        <table className="w-full text-xs border-collapse border border-border">{children}</table>
      </div>
    );
  },
  th({ children }) { return <th className="border border-border px-3 py-1.5 bg-muted text-left font-medium">{children}</th>; },
  td({ children }) { return <td className="border border-border px-3 py-1.5">{children}</td>; },
  blockquote({ children }) {
    return (
      <blockquote className="border-l-4 border-amber-400/50 pl-4 my-3 text-muted-foreground italic text-sm">
        {children}
      </blockquote>
    );
  },
  code({ children }) {
    return <code className="bg-muted px-1 rounded text-xs font-mono">{children}</code>;
  },
};
