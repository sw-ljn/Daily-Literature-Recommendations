// Mirror the cross-tool skills in .agents/skills/ into .claude/skills/ so
// Claude Code (which only scans .claude/skills/) runs the exact same skill
// files as Hermes and Codex. Each mirror entry is a directory junction on
// Windows (no admin rights needed) or a relative symlink elsewhere, so both
// locations share one source of truth. The generated .claude/skills/
// directory is ignored by Git and must never be edited directly; re-run this
// script (or `npm run sync:skills`) after adding or renaming a skill.
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

const projectRoot = path.resolve(import.meta.dirname, '..');
const defaultSourceRoot = path.join(projectRoot, '.agents', 'skills');
const defaultTargetRoot = path.join(projectRoot, '.claude', 'skills');

export function syncSkills({ sourceRoot = defaultSourceRoot, targetRoot = defaultTargetRoot } = {}) {
  if (fs.statSync(sourceRoot, { throwIfNoEntry: false })?.isDirectory() !== true) {
    throw new Error(`Skill source directory not found: ${sourceRoot}`);
  }

  const skillNames = fs
    .readdirSync(sourceRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .filter((name) => fs.statSync(path.join(sourceRoot, name, 'SKILL.md'), { throwIfNoEntry: false })?.isFile());
  if (skillNames.length === 0) {
    throw new Error(`No skill containing SKILL.md found under ${sourceRoot}`);
  }

  fs.mkdirSync(targetRoot, { recursive: true });

  const isWindows = process.platform === 'win32';
  const results = [];

  const isLink = (candidate) => fs.lstatSync(candidate, { throwIfNoEntry: false })?.isSymbolicLink() === true;
  const realTarget = (dir) => {
    try {
      return fs.realpathSync(dir);
    } catch {
      return null;
    }
  };
  const linkResolvesTo = (linkPath, targetDir) => {
    if (!isLink(linkPath)) {
      return false;
    }
    const resolvedLink = realTarget(linkPath);
    const resolvedTarget = realTarget(targetDir);
    return resolvedLink !== null && resolvedLink === resolvedTarget;
  };
  const createLink = (targetDir, linkPath) => {
    const linkTarget = isWindows ? targetDir : path.relative(path.dirname(linkPath), targetDir);
    fs.symlinkSync(linkTarget, linkPath, isWindows ? 'junction' : 'dir');
  };
  const removePath = (victim) => fs.rmSync(victim, { recursive: true, force: true });

  for (const name of skillNames) {
    const sourceDir = path.join(sourceRoot, name);
    const linkPath = path.join(targetRoot, name);
    if (fs.lstatSync(linkPath, { throwIfNoEntry: false }) === undefined) {
      createLink(sourceDir, linkPath);
      results.push({ skill: name, action: 'linked', status: 'ok' });
      continue;
    }
    if (linkResolvesTo(linkPath, sourceDir)) {
      results.push({ skill: name, action: 'unchanged', status: 'ok' });
      continue;
    }
    if (isLink(linkPath)) {
      removePath(linkPath);
      createLink(sourceDir, linkPath);
      results.push({ skill: name, action: 'relinked-broken-or-foreign-link', status: 'ok' });
      continue;
    }
    if (fs.statSync(linkPath, { throwIfNoEntry: false })?.isDirectory()) {
      if (fs.statSync(path.join(linkPath, 'SKILL.md'), { throwIfNoEntry: false })?.isFile()) {
        removePath(linkPath);
        createLink(sourceDir, linkPath);
        results.push({ skill: name, action: 'replaced-copied-mirror-with-link', status: 'ok' });
      } else {
        results.push({ skill: name, action: 'skipped-unmanaged-directory', status: 'left-untouched' });
      }
      continue;
    }
    removePath(linkPath);
    createLink(sourceDir, linkPath);
    results.push({ skill: name, action: 'replaced-file-with-link', status: 'ok' });
  }

  const realSourceRoot = realTarget(sourceRoot);
  const managedByThisScript = (resolved) =>
    realSourceRoot !== null && (resolved === realSourceRoot || resolved.startsWith(realSourceRoot + path.sep));
  for (const entry of fs.readdirSync(targetRoot, { withFileTypes: true })) {
    if (skillNames.includes(entry.name)) {
      continue;
    }
    const victim = path.join(targetRoot, entry.name);
    if (!isLink(victim)) {
      results.push({ skill: entry.name, action: 'left-unmanaged-entry', status: 'left-untouched' });
      continue;
    }
    const resolved = realTarget(victim);
    if (resolved === null || managedByThisScript(resolved)) {
      removePath(victim);
      results.push({
        skill: entry.name,
        action: resolved === null ? 'removed-dangling-link' : 'removed-stale-link',
        status: 'ok',
      });
    } else {
      results.push({ skill: entry.name, action: 'left-unmanaged-link', status: 'left-untouched' });
    }
  }

  return { ok: true, sourceRoot, targetRoot, results };
}

function main() {
  try {
    process.stdout.write(`${JSON.stringify(syncSkills())}\n`);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
