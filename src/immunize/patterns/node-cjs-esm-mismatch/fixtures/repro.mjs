// Repro for node-cjs-esm-mismatch.
//
// The .mjs extension forces Node to load this file as an ES Module, but
// the body uses CommonJS `require()` for `fs`. Node throws:
//
//   ReferenceError: require is not defined in ES module scope
//
// The fix is to replace the require() call with an `import` statement.

const fs = require("fs");
import path from "path";

export function readFirstLine(filename) {
  const text = fs.readFileSync(filename, "utf8");
  return text.split(path.sep)[0];
}
