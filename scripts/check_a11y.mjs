import { pathToFileURL } from "node:url";
import { glob } from "glob";
import pa11y from "pa11y";

if (process.env.GITHUB_ACTIONS === "true") {
  console.log("Skipping accessibility check on GitHub Actions because Chrome is not provisioned there.");
  process.exit(0);
}

const siteDir = process.argv[2] ?? "output";
const pattern = `${siteDir.replaceAll("\\", "/")}/**/*.html`;
let files = await glob(pattern, {
  nodir: true,
});
files = files.sort();

if (files.length === 0) {
  console.error(`No HTML files found for accessibility checks in ${siteDir}`);
  process.exit(1);
}

const maxPages = Number.parseInt(process.env.A11Y_MAX_PAGES ?? "40", 10);
const checkedFiles = maxPages > 0 ? files.slice(0, maxPages) : files;
const failures = [];

for (const file of checkedFiles) {
  const url = pathToFileURL(file).href;
  const result = await pa11y(url, {
    standard: "WCAG2AA",
    timeout: 30000,
    wait: 250,
    includeNotices: false,
    includeWarnings: false,
    chromeLaunchConfig: {
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    },
  });

  const errors = result.issues.filter((issue) => issue.type === "error");
  if (errors.length > 0) {
    failures.push({ file, errors });
  }
}

if (failures.length > 0) {
  console.error("Accessibility check failed:");
  for (const failure of failures) {
    console.error(`  ${failure.file}`);
    for (const issue of failure.errors) {
      console.error(`    - ${issue.code}: ${issue.message}`);
      if (issue.selector) {
        console.error(`      selector: ${issue.selector}`);
      }
    }
  }
  process.exit(1);
}

const scope = checkedFiles.length === files.length ? "" : ` of ${files.length}`;
console.log(`Accessibility check passed (${checkedFiles.length}${scope} HTML files checked).`);
