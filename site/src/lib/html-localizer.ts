import { translateUiText, translateUiTitle } from "./ui-text-localizer.ts";

export type HtmlLocalizationStats = {
  translatedTextCount: number;
  translatedAttributeCount: number;
};

const SKIPPED_CONTENT_TAGS = new Set(["script", "style", "code", "pre"]);
const LOCALIZED_ATTRIBUTES = "aria-label|placeholder|title|alt";
const QUOTED_ATTRIBUTE_PATTERN = new RegExp(
  `(\\s(?:${LOCALIZED_ATTRIBUTES})\\s*=\\s*)(["'])([\\s\\S]*?)\\2`,
  "gi"
);
const UNQUOTED_ATTRIBUTE_PATTERN = new RegExp(
  `(\\s(?:${LOCALIZED_ATTRIBUTES})\\s*=\\s*)(?!["'])([^\\s"'=<>]+)`,
  "gi"
);
const entityValues: Record<string, string> = {
  amp: "&",
  apos: "'",
  gt: ">",
  lt: "<",
  nbsp: "\u00a0",
  quot: '"'
};

const decodeHtml = (value: string) =>
  value.replace(
    /&(#x[\da-f]+|#\d+|amp|apos|gt|lt|nbsp|quot);/gi,
    (entity, key: string) => {
      if (key[0] !== "#") {
        return entityValues[key.toLowerCase()] ?? entity;
      }
      const hexadecimal = key[1]?.toLowerCase() === "x";
      const codePoint = Number.parseInt(
        key.slice(hexadecimal ? 2 : 1),
        hexadecimal ? 16 : 10
      );
      try {
        return Number.isFinite(codePoint)
          ? String.fromCodePoint(codePoint)
          : entity;
      } catch {
        return entity;
      }
    }
  );

const escapeText = (value: string) =>
  value.replaceAll("&", "&amp;").replaceAll("<", "&lt;");

const escapeAttribute = (value: string, quote: string | null) => {
  let escaped = value.replaceAll("&", "&amp;").replaceAll("<", "&lt;");
  if (quote === '"') escaped = escaped.replaceAll('"', "&quot;");
  if (quote === "'") escaped = escaped.replaceAll("'", "&#39;");
  return escaped;
};

const scanTagEnd = (html: string, start: number) => {
  let quote = "";
  for (let index = start + 1; index < html.length; index += 1) {
    const character = html[index];
    if (quote) {
      if (character === quote) quote = "";
      continue;
    }
    if (character === '"' || character === "'") {
      quote = character;
      continue;
    }
    if (character === ">") return index + 1;
  }
  return html.length;
};

const localizeAttributes = (
  tag: string,
  stats: HtmlLocalizationStats
) => {
  const withQuotedAttributes = tag.replace(
    QUOTED_ATTRIBUTE_PATTERN,
    (match, prefix: string, quote: string, rawValue: string) => {
      const decoded = decodeHtml(rawValue);
      const translated = translateUiText(decoded);
      if (translated === decoded) return match;
      stats.translatedAttributeCount += 1;
      return `${prefix}${quote}${escapeAttribute(translated, quote)}${quote}`;
    }
  );
  return withQuotedAttributes.replace(
    UNQUOTED_ATTRIBUTE_PATTERN,
    (match, prefix: string, rawValue: string) => {
      const decoded = decodeHtml(rawValue);
      const translated = translateUiText(decoded);
      if (translated === decoded) return match;
      stats.translatedAttributeCount += 1;
      return `${prefix}"${escapeAttribute(translated, '"')}"`;
    }
  );
};

export function localizeHtmlWithStats(
  html: string,
  locale: string
): { html: string; stats: HtmlLocalizationStats } {
  const stats: HtmlLocalizationStats = {
    translatedTextCount: 0,
    translatedAttributeCount: 0
  };
  if (locale !== "en") return { html, stats };

  let output = "";
  let cursor = 0;
  let rawTag: string | null = null;
  let inTitle = false;
  const lowerHtml = html.toLowerCase();
  while (cursor < html.length) {
    if (rawTag) {
      const closingIndex = lowerHtml.indexOf(`</${rawTag}`, cursor);
      if (closingIndex < 0) {
        output += html.slice(cursor);
        break;
      }
      output += html.slice(cursor, closingIndex);
      cursor = closingIndex;
    }

    const tagStart = html.indexOf("<", cursor);
    if (tagStart < 0) {
      const rawText = html.slice(cursor);
      const decoded = decodeHtml(rawText);
      const translated = inTitle
        ? translateUiTitle(decoded)
        : translateUiText(decoded);
      if (translated !== decoded) {
        stats.translatedTextCount += 1;
        output += escapeText(translated);
      } else {
        output += rawText;
      }
      break;
    }

    if (tagStart > cursor) {
      const rawText = html.slice(cursor, tagStart);
      const decoded = decodeHtml(rawText);
      const translated = inTitle
        ? translateUiTitle(decoded)
        : translateUiText(decoded);
      if (translated !== decoded) {
        stats.translatedTextCount += 1;
        output += escapeText(translated);
      } else {
        output += rawText;
      }
    }

    if (html.startsWith("<!--", tagStart)) {
      const commentEnd = html.indexOf("-->", tagStart + 4);
      const end = commentEnd < 0 ? html.length : commentEnd + 3;
      output += html.slice(tagStart, end);
      cursor = end;
      continue;
    }

    const tagEnd = scanTagEnd(html, tagStart);
    const rawTagSource = html.slice(tagStart, tagEnd);
    const tagMatch = rawTagSource.match(
      /^<\s*(\/?)\s*([a-zA-Z][\w:-]*)/
    );
    if (!tagMatch) {
      output += rawTagSource;
      cursor = tagEnd;
      continue;
    }
    const closing = Boolean(tagMatch[1]);
    const tagName = tagMatch[2].toLowerCase();
    const selfClosing = /\/\s*>$/.test(rawTagSource);
    output +=
      closing || SKIPPED_CONTENT_TAGS.has(tagName)
        ? rawTagSource
        : localizeAttributes(rawTagSource, stats);
    cursor = tagEnd;

    if (closing) {
      if (tagName === "title") inTitle = false;
      if (rawTag === tagName) rawTag = null;
    } else if (!selfClosing) {
      if (tagName === "title") inTitle = true;
      if (SKIPPED_CONTENT_TAGS.has(tagName)) rawTag = tagName;
    }
  }
  return { html: output, stats };
}

export function localizeHtml(html: string, locale: string): string {
  return localizeHtmlWithStats(html, locale).html;
}
