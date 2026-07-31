---
description: Set Wringer up on this machine by executing SETUP.md step by step
---

Set up Wringer on this machine by executing this repository's runbook.

1. Read `SETUP.md` in the repository root, in full, before running anything.
2. Execute its numbered steps **in order**. After each step, run that step's
   verify command and check the output against what SETUP.md says correct
   output looks like.
3. Do not move to the next step until the current step's verification passes.
   Do not batch steps, do not improvise an alternative approach, and do not
   skip a verification because a step obviously worked.
4. If a verify command's output does not match, **stop** and report: the step
   number, the command you ran, the output you got, and the output SETUP.md
   expected. Do not retry blindly and do not work around it.
5. Honour SETUP.md's stop conditions. In particular: **do not install
   container runtimes, Docker, Apple `container`, or system packages.**
   Report what is missing, give the human the command, and wait.

**The API key is the human's to type, into `wring`'s own prompt. Never ask
for it, read it, store it, echo it, write it into a file, put it on a
command line, or relay it anywhere.** Do not read `~/.zshrc`, `~/.bashrc`,
`.env`, or any credential store; do not run `env | grep KEY`; do not offer
to export it. If the human pastes a key to you anyway, do not use it — tell
them to run the launch command themselves and to rotate that key.

Stop at SETUP.md step 9 and hand back. That step tells you exactly what to
print for the human, and the launch command is theirs to run, not yours.

Finish with a short report: which steps ran, the verification output for
each, and anything that is still the human's to do.
