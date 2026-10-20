const { spawnSync } = require("node:child_process");
const path = require("node:path");

const python = process.env.SEC_STUDIO_PYTHON || process.env.PYTHON ||
  (process.platform === "win32" ? "py" : "python3");
const result = spawnSync(python, [path.join(__dirname, "build_engine.py")], {
  cwd: __dirname,
  stdio: "inherit",
  shell: process.platform === "win32"
});
if (result.error) {
  console.error(`Unable to run Python (${python}): ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
