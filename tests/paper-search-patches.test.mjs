import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import test from 'node:test';

import { searchMultipleSources } from '../node_modules/paper-search-cli/dist/capabilities/metadata-search/MultiSourceSearchService.js';
import { ArxivSearcher } from '../node_modules/paper-search-cli/dist/platforms/ArxivSearcher.js';
import { GoogleScholarSearcher } from '../node_modules/paper-search-cli/dist/platforms/GoogleScholarSearcher.js';
import { downloadWithFallback } from '../node_modules/paper-search-cli/dist/capabilities/pdf-discovery/OpenAccessFallbackService.js';
import { DownloadWithFallbackSchema } from '../node_modules/paper-search-cli/dist/capabilities/pdf-discovery/schemas.js';

const delay = (milliseconds, value = []) => new Promise((resolve) => setTimeout(resolve, milliseconds, value));

test('arXiv receives a source-specific timeout budget', async () => {
  const previous = process.env.PAPER_SEARCH_ARXIV_SOURCE_TIMEOUT_MS;
  process.env.PAPER_SEARCH_ARXIV_SOURCE_TIMEOUT_MS = '80';
  try {
    const searchers = { arxiv: { search: () => delay(30) } };
    const result = await searchMultipleSources(searchers, 'test', 'arxiv', {}, 10);
    assert.equal(result.failed_sources.length, 0);
    assert.equal(result.source_results.arxiv, 0);
  } finally {
    if (previous === undefined) delete process.env.PAPER_SEARCH_ARXIV_SOURCE_TIMEOUT_MS;
    else process.env.PAPER_SEARCH_ARXIV_SOURCE_TIMEOUT_MS = previous;
  }
});

test('other sources retain the normal timeout budget', async () => {
  const searchers = { crossref: { search: () => delay(30) } };
  const result = await searchMultipleSources(searchers, 'test', 'crossref', {}, 10);
  assert.deepEqual(result.failed_sources, ['crossref']);
  assert.match(result.errors.crossref, /timed out after 10ms/);
});

test('arXiv cooldown waits without holding the global lock', async () => {
  const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), 'paper-search-arxiv-test-'));
  const previous = process.env.PAPER_SEARCH_CACHE_DIR;
  process.env.PAPER_SEARCH_CACHE_DIR = cacheDir;
  try {
    const searcher = new ArxivSearcher();
    const cooldownMs = 120;
    fs.writeFileSync(
      path.join(cacheDir, 'arxiv-rate-limit.json'),
      JSON.stringify({ cooldownUntil: Date.now() + cooldownMs }),
      'utf8',
    );
    const startedAt = Date.now();
    const waiting = searcher.waitForGlobalExportApiSlot();
    await delay(25);
    assert.equal(fs.existsSync(path.join(cacheDir, 'arxiv-rate-limit.lock')), false);
    await waiting;
    assert.ok(Date.now() - startedAt >= 90);
    const state = JSON.parse(fs.readFileSync(path.join(cacheDir, 'arxiv-rate-limit.json'), 'utf8'));
    assert.equal(typeof state.lastRequestAt, 'number');
    assert.equal('cooldownUntil' in state, false);
  } finally {
    if (previous === undefined) delete process.env.PAPER_SEARCH_CACHE_DIR;
    else process.env.PAPER_SEARCH_CACHE_DIR = previous;
    fs.rmSync(cacheDir, { recursive: true, force: true });
  }
});

test('Google Scholar SerpApi fixture maps to normalized paper fields', () => {
  const searcher = new GoogleScholarSearcher();
  const paper = searcher.parseSerpApiResult({
    result_id: 'fixture-result',
    title: 'A fixture paper',
    link: 'https://example.org/paper',
    snippet: 'A bounded abstract snippet.',
    publication_info: {
      summary: 'A Author, B Author - Journal of Fixtures, 2026 - example.org',
      authors: [{ name: 'A Author' }, { name: 'B Author' }],
    },
    resources: [{ file_format: 'PDF', link: 'https://example.org/paper.pdf' }],
    inline_links: {
      cited_by: { total: 17, cites_id: 'cites-fixture' },
      versions: { cluster_id: 'cluster-fixture' },
    },
  });
  assert.equal(paper.paperId, 'fixture-result');
  assert.equal(paper.title, 'A fixture paper');
  assert.deepEqual(paper.authors, ['A Author', 'B Author']);
  assert.equal(paper.year, 2026);
  assert.equal(paper.citationCount, 17);
  assert.equal(paper.pdfUrl, 'https://example.org/paper.pdf');
  assert.equal(paper.extra.backend, 'serpapi');
});

test('configured SerpApi key selects the managed Google Scholar backend', async () => {
  const previousKey = process.env.SERPAPI_API_KEY;
  process.env.SERPAPI_API_KEY = 'fixture-key';
  try {
    const searcher = new GoogleScholarSearcher();
    let selected = false;
    searcher.searchViaSerpApi = async () => {
      selected = true;
      return [];
    };
    await searcher.search('fixture');
    assert.equal(selected, true);
  } finally {
    if (previousKey === undefined) delete process.env.SERPAPI_API_KEY;
    else process.env.SERPAPI_API_KEY = previousKey;
  }
});

test('download_with_fallback schema preserves caller-supplied pdfUrl', () => {
  const parsed = DownloadWithFallbackSchema.parse({
    source: 'crossref',
    paperId: '10.1234/example',
    pdfUrl: 'https://example.org/example.pdf',
    useSciHub: false,
  });
  assert.equal(parsed.pdfUrl, 'https://example.org/example.pdf');
  assert.equal(parsed.useSciHub, false);
});

test('caller-supplied pdfUrl is attempted before source-native download', async () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'paper-search-pdfurl-test-'));
  let primaryCalled = false;
  const payload = Buffer.from('%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n');
  const server = http.createServer((req, res) => {
    res.writeHead(200, {
      'content-type': 'application/pdf',
      'content-length': String(payload.length),
    });
    res.end(payload);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  try {
    const result = await downloadWithFallback(
      {
        crossref: {
          getCapabilities: () => ({ download: true }),
          downloadPdf: async () => {
            primaryCalled = true;
            throw new Error('primary should not be reached');
          },
        },
      },
      {
        source: 'crossref',
        paperId: '10.1234/example',
        title: 'Example',
        pdfUrl: `http://127.0.0.1:${address.port}/paper.pdf`,
        savePath: tempDir,
        useSciHub: false,
      },
    );
    assert.equal(result.status, 'ok');
    assert.equal(result.attempts[0].stage, 'supplied_pdf_url');
    assert.equal(result.attempts[0].status, 'ok');
    assert.equal(primaryCalled, false);
    assert.equal(fs.existsSync(result.path), true);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});
