"use client";

import { createElement, useEffect, useState, type ReactNode } from "react";

// Each legal text's single source is its static page (public/privacy.html, public/terms.html). Its <main> is rebuilt
// here as React elements from an allow-list of tags (no innerHTML), so it can be read and scrolled inside the sign-in
// consent box.

const TAGS = new Set(["h2", "p", "ul", "li", "a", "strong", "em", "div", "table", "thead", "tbody", "tr", "th", "td"]);
const CLASSES: Record<string, string> = {
  h2: "mb-1.5 mt-4 first:mt-0 text-sm font-semibold text-[var(--text-primary)]",
  p: "mb-2",
  ul: "mb-2 list-disc space-y-1 pl-5",
  a: "text-[var(--accent)] underline underline-offset-2",
  strong: "font-semibold text-[var(--text-primary)]",
  div: "overflow-x-auto",
  table: "mb-2 w-full border-collapse",
  th: "border-b border-[var(--border)] px-2 py-1.5 text-left align-top font-semibold text-[var(--text-primary)]",
  td: "border-b border-[var(--border)] px-2 py-1.5 text-left align-top",
};

function safeHref(href: string | null): string | undefined {
  if (!href) return undefined;
  return /^(https?:|mailto:|\/|#)/i.test(href) ? href : undefined;
}

function toReact(node: Node, key: number): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent;
  if (node.nodeType !== Node.ELEMENT_NODE) return null;
  const el = node as Element;
  const tag = el.tagName.toLowerCase();
  if (tag === "h1") return null; // the consent box already carries the title
  const children = Array.from(el.childNodes).map(toReact);
  if (!TAGS.has(tag)) return children; // unknown wrapper: keep its text, drop the tag
  const props: Record<string, unknown> = { key, className: CLASSES[tag] };
  if (tag === "a") Object.assign(props, { href: safeHref(el.getAttribute("href")), target: "_blank", rel: "noopener" });
  return createElement(tag, props, ...children);
}

export type LegalDoc = { src: string; title: string };

export const PRIVACY_POLICY: LegalDoc = { src: "/privacy.html", title: "Privacy Policy" };
export const TERMS_OF_SERVICE: LegalDoc = { src: "/terms.html", title: "Terms of Service" };

export default function LegalText({ doc, className = "" }: { doc: LegalDoc; className?: string }) {
  const [content, setContent] = useState<ReactNode>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setContent(null);
    setFailed(false);
    fetch(doc.src)
      .then((res) => (res.ok ? res.text() : Promise.reject(new Error(String(res.status)))))
      .then((html) => {
        const main = new DOMParser().parseFromString(html, "text/html").querySelector("main");
        if (!main) throw new Error("no legal text");
        if (live) setContent(Array.from(main.childNodes).map(toReact));
      })
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [doc.src]);

  return (
    <div
      tabIndex={0}
      aria-label={doc.title}
      className={`overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-3 text-xs leading-relaxed text-[var(--text-secondary)] ${className}`}
    >
      {failed ? (
        <p>
          The {doc.title} couldn&apos;t be loaded here.{" "}
          <a href={doc.src} target="_blank" rel="noopener" className={CLASSES.a}>
            Open the {doc.title}
          </a>{" "}
          to read it.
        </p>
      ) : (
        content ?? <p>Loading the {doc.title}…</p>
      )}
    </div>
  );
}
