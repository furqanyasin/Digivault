"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";

export function CopySnippet({ snippet, siteId }: { snippet: string; siteId: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="space-y-2">
      <div className="relative rounded-md bg-muted border">
        <pre className="p-4 text-xs font-mono overflow-x-auto whitespace-pre-wrap break-all">
          {snippet}
        </pre>
        <Button
          size="sm"
          variant="ghost"
          className="absolute top-2 right-2 h-7 gap-1"
          onClick={handleCopy}
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied!" : "Copy"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Site ID: <code className="bg-muted px-1 rounded font-mono">{siteId}</code>
      </p>
    </div>
  );
}
