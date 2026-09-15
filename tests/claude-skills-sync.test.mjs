import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { syncSkills } from '../scripts/sync-claude-skills.mjs';

function tempProject() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'claude-skills-sync-'));
  return {
    root,
    sourceRoot: path.join(root, '.agents', 'skills'),
    targetRoot: path.join(root, '.claude', 'skills'),
  };
}

function writeSkill(sourceRoot, name) {
  const dir = path.join(sourceRoot, name);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'SKILL.md'), `---\nname: ${name}\ndescription: temporary test skill ${name}\n---\n`, 'utf8');
  return dir;
}

test('links every source skill into .claude/skills', () => {
  const { sourceRoot, targetRoot } = tempProject();
  const alpha = writeSkill(sourceRoot, 'alpha');
  const beta = writeSkill(sourceRoot, 'beta');

  const report = syncSkills({ sourceRoot, targetRoot });

  assert.equal(report.ok, true);
  assert.equal(fs.realpathSync(path.join(targetRoot, 'alpha')), fs.realpathSync(alpha));
  assert.equal(fs.realpathSync(path.join(targetRoot, 'beta')), fs.realpathSync(beta));
});

test('a second run is idempotent and reports unchanged links', () => {
  const { sourceRoot, targetRoot } = tempProject();
  writeSkill(sourceRoot, 'alpha');
  syncSkills({ sourceRoot, targetRoot });

  const second = syncSkills({ sourceRoot, targetRoot });

  assert.deepEqual(
    second.results.map((entry) => entry.action).sort(),
    ['unchanged'],
  );
});

test('recreates a missing link on the next run', () => {
  const { sourceRoot, targetRoot } = tempProject();
  writeSkill(sourceRoot, 'alpha');
  syncSkills({ sourceRoot, targetRoot });
  fs.rmSync(path.join(targetRoot, 'alpha'));

  const again = syncSkills({ sourceRoot, targetRoot });

  assert.equal(again.results[0].action, 'linked');
});

test('converts an old copied mirror into a link', () => {
  const { sourceRoot, targetRoot } = tempProject();
  const alpha = writeSkill(sourceRoot, 'alpha');
  fs.mkdirSync(path.join(targetRoot, 'alpha'), { recursive: true });
  fs.writeFileSync(path.join(targetRoot, 'alpha', 'SKILL.md'), 'stale copy\n', 'utf8');

  const report = syncSkills({ sourceRoot, targetRoot });

  assert.equal(report.results[0].action, 'replaced-copied-mirror-with-link');
  assert.equal(fs.realpathSync(path.join(targetRoot, 'alpha')), fs.realpathSync(alpha));
  assert.equal(fs.readFileSync(path.join(targetRoot, 'alpha', 'SKILL.md'), 'utf8').includes('temporary test skill alpha'), true);
});

test('removes stale or dangling links into the source tree and keeps unmanaged entries', () => {
  const { sourceRoot, targetRoot } = tempProject();
  writeSkill(sourceRoot, 'alpha');
  writeSkill(sourceRoot, 'beta');
  fs.mkdirSync(path.join(targetRoot, 'notes'), { recursive: true });
  fs.writeFileSync(path.join(targetRoot, 'notes', 'README.md'), 'not a skill\n', 'utf8');
  syncSkills({ sourceRoot, targetRoot });

  fs.rmSync(path.join(sourceRoot, 'beta'), { recursive: true, force: true });
  writeSkill(sourceRoot, 'gamma');
  const report = syncSkills({ sourceRoot, targetRoot });

  const removed = report.results.find((entry) => entry.skill === 'beta');
  assert.match(removed.action, /^removed-(stale|dangling)-link$/);
  assert.deepEqual(
    fs.readdirSync(targetRoot).sort(),
    ['alpha', 'gamma', 'notes'],
  );
  assert.equal(report.results.find((entry) => entry.skill === 'notes').action, 'left-unmanaged-entry');
});

test('fails when the source directory is missing', () => {
  assert.throws(
    () => syncSkills({ sourceRoot: path.join(os.tmpdir(), `definitely-missing-${Date.now()}`), targetRoot: os.tmpdir() }),
    /Skill source directory not found/,
  );
});
