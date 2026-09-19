"use client";

import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

export default function ResearchMarkdown({ text, onSource }: { text: string; onSource?: (id: string) => void }) {
  return <div className="research-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={(url) => url.startsWith("source://") ? url : defaultUrlTransform(url)} components={{
    a({ href, children }) {
      const sourceMatch = href?.match(/(?:source:\/\/|#source-|\/sources\/)([^/?#]+)/);
      if (sourceMatch && onSource) return <button className="research-citation" onClick={() => onSource(decodeURIComponent(sourceMatch[1]))}>{children}</button>;
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
    },
    table({ children }) { return <div className="research-table-scroll"><table>{children}</table></div>; },
  }}>{text}</ReactMarkdown></div>;
}
