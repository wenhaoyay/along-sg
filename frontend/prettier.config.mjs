/** @type {import("prettier").Config} */
const config = {
  // Matches `line-length = 100` in the backend's ruff config, so one number
  // governs the whole repository rather than each half drifting.
  printWidth: 100,

  // The repository has no .gitattributes and core.autocrlf is on, so Git hands
  // Windows a CRLF working copy. Prettier's default of "lf" would then report
  // every checked-out file as unformatted and turn `format:check` red on a
  // fresh clone. "auto" takes each file as it finds it; Git still normalises to
  // LF in the index, so the committed bytes are identical either way.
  endOfLine: "auto",

  // Everything else is left at Prettier's defaults on purpose - double quotes,
  // semicolons, trailing commas and two-space indentation are already what
  // this codebase does, so adopting the defaults keeps the reformat to
  // line-wrapping instead of a rewrite of every line in the frontend.

  overrides: [
    {
      // Markdown line breaks are sometimes deliberate; reflowing prose would
      // rewrite documents that are not code.
      files: "*.md",
      options: { proseWrap: "preserve" },
    },
  ],
};

export default config;
