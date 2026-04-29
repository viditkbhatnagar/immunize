// Fix for node-cjs-esm-mismatch.
//
// Same module API as repro.mjs (default-exports `readFirstLine`), but
// uses `import` consistently — appropriate for a .mjs file or a package
// with `"type": "module"`.

import fs from "fs";
import path from "path";

export function readFirstLine(filename) {
  const text = fs.readFileSync(filename, "utf8");
  return text.split(path.sep)[0];
}
