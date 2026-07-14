import { readFile } from "node:fs/promises";
import { glob } from "glob";
import postcss from "postcss";
import DoIUse from "doiuse/lib/DoIUse.js";

const siteDir = process.argv[2] ?? "output";
const pattern = `${siteDir.replaceAll("\\", "/")}/**/*.css`;
const supportedBrowsers =
  "> 0.5%, last 2 versions, Firefox ESR, not dead, not op_mini all, not kaios 2.5, not kaios 3.0-3.1, not and_qq 14.9, not and_uc 15.5";
const files = await glob(pattern, { nodir: true });

if (files.length === 0) {
  console.error(`No CSS files found for browser-support checks in ${siteDir}`);
  process.exit(1);
}

const usages = [];

for (const file of files) {
  const css = await readFile(file, "utf8");
  await postcss([
    new DoIUse({
      browsers: supportedBrowsers,
      onFeatureUsage: (usage) => usages.push(`${file}:${usage.message}`),
    }),
  ]).process(css, { from: file });
}

if (usages.length > 0) {
  console.error("Browser support check failed:");
  for (const usage of usages) {
    console.error(`  - ${usage}`);
  }
  process.exit(1);
}

console.log(`Browser support check passed (${files.length} CSS files checked).`);
