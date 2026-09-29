#!/usr/bin/env node

import {
  chmod,
  lstat,
  readFile,
  readdir,
  rename,
  unlink,
  writeFile
} from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

import {
  localizeHtmlWithStats
} from "../site/src/lib/html-localizer.ts";

async function htmlFiles(root) {
  const files = [];
  const entries = await readdir(root, { withFileTypes: true });
  for (const entry of entries) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) files.push(...(await htmlFiles(path)));
    else if (entry.isFile() && entry.name.endsWith(".html")) files.push(path);
  }
  return files.sort();
}

const removeIfPresent = async (path) => {
  try {
    await unlink(path);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
};

export async function localizeDirectory(root, locale) {
  const resolvedRoot = resolve(root);
  const files = await htmlFiles(resolvedRoot);
  const stats = {
    fileCount: files.length,
    changedFileCount: 0,
    translatedTextCount: 0,
    translatedAttributeCount: 0
  };
  const transactionId = `${process.pid}-${randomUUID()}`;
  const prepared = [];

  try {
    for (const path of files) {
      const source = await readFile(path, "utf8");
      const localized = localizeHtmlWithStats(source, locale);
      stats.translatedTextCount += localized.stats.translatedTextCount;
      stats.translatedAttributeCount +=
        localized.stats.translatedAttributeCount;
      if (localized.html === source) continue;
      stats.changedFileCount += 1;
      const temporary = join(
        dirname(path),
        `.${basename(path)}.localize-${transactionId}.tmp`
      );
      const backup = join(
        dirname(path),
        `.${basename(path)}.localize-${transactionId}.bak`
      );
      const sourceStat = await lstat(path);
      await writeFile(temporary, localized.html, "utf8");
      await chmod(temporary, sourceStat.mode);
      prepared.push({ path, temporary, backup, committed: false });
    }

    for (const entry of prepared) {
      await rename(entry.path, entry.backup);
      try {
        await rename(entry.temporary, entry.path);
        entry.committed = true;
      } catch (error) {
        await rename(entry.backup, entry.path);
        throw error;
      }
    }
  } catch (error) {
    for (const entry of [...prepared].reverse()) {
      if (entry.committed) {
        await rename(entry.backup, entry.path);
      }
      await removeIfPresent(entry.temporary);
      await removeIfPresent(entry.backup);
    }
    throw error;
  }

  for (const entry of prepared) {
    await removeIfPresent(entry.backup);
    await removeIfPresent(entry.temporary);
  }
  return stats;
}

function parseArgs(argv) {
  const args = [...argv];
  const root = args.shift();
  let locale = "en";
  while (args.length) {
    const argument = args.shift();
    if (argument === "--locale") {
      locale = args.shift() ?? "";
      continue;
    }
    throw new Error(`unknown argument: ${argument}`);
  }
  if (!root) {
    throw new Error(
      "usage: localize_site_output.mjs <output-directory> [--locale en]"
    );
  }
  if (!locale) throw new Error("--locale requires a value");
  return { root, locale };
}

const entryPath = process.argv[1] ? resolve(process.argv[1]) : "";
if (entryPath === fileURLToPath(import.meta.url)) {
  try {
    const args = parseArgs(process.argv.slice(2));
    const stats = await localizeDirectory(args.root, args.locale);
    console.log(JSON.stringify(stats));
  } catch (error) {
    console.error(`HTML localization failed: ${error.message}`);
    process.exitCode = 1;
  }
}
