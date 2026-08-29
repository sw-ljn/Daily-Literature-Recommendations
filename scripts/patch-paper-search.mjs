import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const projectRoot = path.resolve(import.meta.dirname, '..');

function patchFile(relativePath, before, after, marker) {
  const filePath = path.join(projectRoot, relativePath);
  const source = fs.readFileSync(filePath, 'utf8');
  if (source.includes(marker)) {
    return { relativePath, status: 'already-patched' };
  }
  if (!source.includes(before)) {
    throw new Error(`Cannot patch ${relativePath}: expected paper-search-cli 0.3.4 source was not found.`);
  }
  fs.writeFileSync(filePath, source.replace(before, after), 'utf8');
  return { relativePath, status: 'patched' };
}

const multiSourceBefore = `export async function searchMultipleSources(searchers, query, sources, options, sourceTimeoutMs = TIMEOUTS.SOURCE_TASK) {
    const selected = parseSourceList(sources, searchers);
    const settled = await Promise.allSettled(selected.map(async (source) => {
        const searcher = searchers[source];
        const results = await withTimeout(searcher.search(query, options), sourceTimeoutMs, \`${'${source}'} search timed out after ${'${sourceTimeoutMs}'}ms\`);
        return { source, results };
    }));`;

const multiSourceAfter = `function sourceTaskTimeoutMs(source, defaultTimeoutMs) {
    if (source !== 'arxiv') {
        return defaultTimeoutMs;
    }
    const configured = Number.parseInt(process.env.PAPER_SEARCH_ARXIV_SOURCE_TIMEOUT_MS || '', 10);
    if (Number.isFinite(configured) && configured >= defaultTimeoutMs) {
        return configured;
    }
    return Math.max(defaultTimeoutMs, 60000);
}
export async function searchMultipleSources(searchers, query, sources, options, sourceTimeoutMs = TIMEOUTS.SOURCE_TASK) {
    const selected = parseSourceList(sources, searchers);
    const settled = await Promise.allSettled(selected.map(async (source) => {
        const searcher = searchers[source];
        const effectiveTimeoutMs = sourceTaskTimeoutMs(source, sourceTimeoutMs);
        const results = await withTimeout(searcher.search(query, options), effectiveTimeoutMs, \`${'${source}'} search timed out after ${'${effectiveTimeoutMs}'}ms\`);
        return { source, results };
    }));`;

const arxivBefore = `    async waitForGlobalExportApiSlot() {
        await this.withArxivRateLimitLock(async () => {
            const paths = this.getArxivRateLimitPaths();
            const state = this.readArxivRateLimitState(paths.statePath);
            const now = Date.now();
            if (state.cooldownUntil && state.cooldownUntil > now) {
                throw this.createArxivCooldownError(state.cooldownUntil - now);
            }
            const waitMs = Math.max(0, (state.lastRequestAt || 0) + ARXIV_EXPORT_API_INTERVAL_MS - now);
            if (waitMs > 0) {
                await this.sleep(waitMs);
            }
            const lastRequestAt = Date.now();
            const nextState = { ...state, lastRequestAt };
            if (nextState.cooldownUntil && nextState.cooldownUntil <= lastRequestAt) {
                delete nextState.cooldownUntil;
            }
            this.writeArxivRateLimitState(paths.statePath, nextState);
        });
    }`;

const arxivAfter = `    async waitForGlobalExportApiSlot() {
        while (true) {
            const waitMs = await this.withArxivRateLimitLock(async () => {
                const paths = this.getArxivRateLimitPaths();
                const state = this.readArxivRateLimitState(paths.statePath);
                const now = Date.now();
                if (state.cooldownUntil && state.cooldownUntil > now) {
                    return state.cooldownUntil - now;
                }
                const intervalWaitMs = Math.max(0, (state.lastRequestAt || 0) + ARXIV_EXPORT_API_INTERVAL_MS - now);
                if (intervalWaitMs > 0) {
                    return intervalWaitMs;
                }
                const lastRequestAt = Date.now();
                const nextState = { ...state, lastRequestAt };
                if (nextState.cooldownUntil && nextState.cooldownUntil <= lastRequestAt) {
                    delete nextState.cooldownUntil;
                }
                this.writeArxivRateLimitState(paths.statePath, nextState);
                return 0;
            });
            if (waitMs <= 0) {
                return;
            }
            await this.sleep(waitMs);
        }
    }`;

const googleFieldsBefore = `export class GoogleScholarSearcher extends PaperSource {
    scholarUrl = 'https://scholar.google.com/scholar';`;

const googleFieldsAfter = `export class GoogleScholarSearcher extends PaperSource {
    scholarUrl = 'https://scholar.google.com/scholar';
    serpApiUrl = 'https://serpapi.com/search.json';
    serpApiKey = (process.env.SERPAPI_API_KEY || '').trim();`;

const googleSearchBefore = `    async search(query, options = {}) {
        logDebug(\`Google Scholar Search: query="${'${query}'}"\`);
        try {
            const papers = [];`;

const googleSearchAfter = `    async search(query, options = {}) {
        logDebug(\`Google Scholar Search: query="${'${query}'}"\`);
        try {
            const requestedBackend = (process.env.PAPER_SEARCH_GOOGLE_SCHOLAR_BACKEND || 'auto').trim().toLowerCase();
            if (this.serpApiKey) {
                return await this.searchViaSerpApi(query, options);
            }
            if (requestedBackend === 'serpapi') {
                throw new Error('Google Scholar SerpApi backend requires SERPAPI_API_KEY. Configure it locally; direct HTML fallback is disabled.');
            }
            const papers = [];`;

const googleMethodsAnchor = `    async downloadPdf(paperId, options) {`;

const googleMethodsReplacement = `    async searchViaSerpApi(query, options = {}) {
        const papers = [];
        const maxResults = Math.max(1, options.maxResults || 10);
        let start = 0;
        while (papers.length < maxResults) {
            const pageSize = Math.min(20, maxResults - papers.length);
            const params = {
                engine: 'google_scholar',
                q: query,
                start,
                num: pageSize,
                hl: options.language || 'en',
                as_sdt: '0,5',
                as_vis: '1'
            };
            if (options.yearLow || options.yearHigh) {
                params.as_ylo = options.yearLow || '';
                params.as_yhi = options.yearHigh || '';
            }
            if (options.author) {
                params.as_sauthors = options.author;
            }
            logDebug('Google Scholar SerpApi request', { ...params, api_key: '[configured]' });
            let response;
            try {
                response = await axios.get(this.serpApiUrl, {
                    params: { ...params, api_key: this.serpApiKey },
                    timeout: Math.max(TIMEOUTS.DEFAULT, 30000)
                });
            }
            catch (error) {
                const status = error?.response?.status;
                throw new Error(\`Google Scholar SerpApi request failed${'${status ? ` with HTTP ${status}` : ""}'}. The API key was not logged.\`);
            }
            if (response.data?.error) {
                throw new Error(\`Google Scholar SerpApi error: ${'${String(response.data.error)}'}\`);
            }
            const results = Array.isArray(response.data?.organic_results) ? response.data.organic_results : [];
            for (const item of results) {
                if (papers.length >= maxResults) {
                    break;
                }
                const paper = this.parseSerpApiResult(item);
                if (paper) {
                    papers.push(paper);
                }
            }
            if (results.length < pageSize) {
                break;
            }
            start += results.length;
        }
        return papers;
    }
    parseSerpApiResult(item) {
        const title = this.cleanText(item?.title || '');
        if (!title) {
            return null;
        }
        const infoText = String(item?.publication_info?.summary || '');
        const structuredAuthors = Array.isArray(item?.publication_info?.authors)
            ? item.publication_info.authors.map(author => String(author?.name || '').trim()).filter(Boolean)
            : [];
        const authors = structuredAuthors.length > 0 ? structuredAuthors : this.extractAuthors(infoText);
        const year = this.extractYear(infoText);
        const resource = Array.isArray(item?.resources)
            ? item.resources.find(entry => String(entry?.file_format || '').toUpperCase() === 'PDF')
            : undefined;
        const citationCount = Number(item?.inline_links?.cited_by?.total || 0);
        const paperId = String(item?.result_id || '').trim() || this.generatePaperId(title, authors);
        return PaperFactory.create({
            paperId,
            title,
            authors,
            abstract: this.cleanText(item?.snippet || ''),
            doi: '',
            publishedDate: year ? new Date(year, 0, 1) : null,
            pdfUrl: String(resource?.link || ''),
            url: String(item?.link || resource?.link || ''),
            source: 'googlescholar',
            categories: [],
            keywords: [],
            citationCount: Number.isFinite(citationCount) ? citationCount : 0,
            journal: this.extractJournal(infoText),
            year,
            extra: {
                scholarId: paperId,
                infoText,
                backend: 'serpapi',
                citesId: String(item?.inline_links?.cited_by?.cites_id || ''),
                clusterId: String(item?.inline_links?.versions?.cluster_id || '')
            }
        });
    }
    async downloadPdf(paperId, options) {`;

const downloadSchemaBefore = `export const DownloadWithFallbackSchema = z
    .object({
    source: z.coerce.string().min(1),
    paperId: z.coerce.string().min(1),
    doi: z.coerce.string().optional().default(''),
    title: z.coerce.string().optional().default(''),
    savePath: z.coerce.string().optional(),
    useSciHub: z.boolean().optional().default(true)
})`;

const downloadSchemaAfter = `export const DownloadWithFallbackSchema = z
    .object({
    source: z.coerce.string().min(1),
    paperId: z.coerce.string().min(1),
    doi: z.coerce.string().optional().default(''),
    title: z.coerce.string().optional().default(''),
    pdfUrl: z.coerce.string().optional().default(''),
    savePath: z.coerce.string().optional(),
    useSciHub: z.boolean().optional().default(true)
})`;

const downloadToolsBefore = `            doi: { type: 'string', description: 'Optional DOI for OA fallback resolution' },
            title: { type: 'string', description: 'Optional title for repository discovery fallback' },
            savePath: { type: 'string', description: 'Directory to save the PDF file' },`;

const downloadToolsAfter = `            doi: { type: 'string', description: 'Optional DOI for OA fallback resolution' },
            title: { type: 'string', description: 'Optional title for repository discovery fallback' },
            pdfUrl: { type: 'string', description: 'Optional already-known direct PDF URL. When supplied, it is attempted before source-native and discovery fallbacks.' },
            savePath: { type: 'string', description: 'Directory to save the PDF file' },`;

const fallbackImportBefore = `import { createDirectPdfUrlTier } from './tiers/directPdfUrl.js';`;
const fallbackImportAfter = `import { createDirectPdfUrlTier, createSuppliedPdfUrlTier } from './tiers/directPdfUrl.js';`;

const fallbackTiersBefore = `    return [
        createPrimaryTier(),
        createDirectPdfUrlTier(),`;

const fallbackTiersAfter = `    return [
        createSuppliedPdfUrlTier(),
        createPrimaryTier(),
        createDirectPdfUrlTier(),`;

const fallbackContextBefore = `        doi: options.doi,
        title: options.title,
        savePath,`;

const fallbackContextAfter = `        doi: options.doi,
        title: options.title,
        pdfUrl: options.pdfUrl || '',
        savePath,`;

const directPdfBefore = `import { downloadPdfFromUrl, safeFilename } from '../../../infrastructure/pdf/PdfDownload.js';
export function createDirectPdfUrlTier() {`;

const directPdfAfter = `import { downloadPdfFromUrl, safeFilename } from '../../../infrastructure/pdf/PdfDownload.js';
export function createSuppliedPdfUrlTier() {
    return {
        id: 'supplied_pdf_url',
        stage: 'supplied_pdf_url',
        run: trySuppliedPdfUrl
    };
}
async function trySuppliedPdfUrl(context) {
    const pdfUrl = String(context.pdfUrl || '').trim();
    if (!pdfUrl) {
        return { status: 'skipped', message: 'No caller-supplied pdfUrl.' };
    }
    try {
        const path = await downloadPdfFromUrl(pdfUrl, context.savePath, \`supplied_\${safeFilename(context.paperId || context.title || 'paper')}\`);
        return { status: 'ok', path, message: path };
    }
    catch (error) {
        return { status: 'error', message: error?.message || String(error) };
    }
}
export function createDirectPdfUrlTier() {`;

const results = [
  patchFile(
    'node_modules/paper-search-cli/dist/capabilities/metadata-search/MultiSourceSearchService.js',
    multiSourceBefore,
    multiSourceAfter,
    'function sourceTaskTimeoutMs(source, defaultTimeoutMs)',
  ),
  patchFile(
    'node_modules/paper-search-cli/dist/platforms/ArxivSearcher.js',
    arxivBefore,
    arxivAfter,
    'const waitMs = await this.withArxivRateLimitLock',
  ),
  patchFile(
    'node_modules/paper-search-cli/dist/platforms/GoogleScholarSearcher.js',
    googleFieldsBefore,
    googleFieldsAfter,
    "serpApiUrl = 'https://serpapi.com/search.json'",
  ),
  patchFile(
    'node_modules/paper-search-cli/dist/platforms/GoogleScholarSearcher.js',
    googleSearchBefore,
    googleSearchAfter,
    "const requestedBackend = (process.env.PAPER_SEARCH_GOOGLE_SCHOLAR_BACKEND || 'auto')",
  ),
  patchFile(
    'node_modules/paper-search-cli/dist/platforms/GoogleScholarSearcher.js',
    googleMethodsAnchor,
    googleMethodsReplacement,
    'async searchViaSerpApi(query, options = {})',
  ),
  patchFile(
    'node_modules/paper-search-cli/dist/capabilities/pdf-discovery/schemas.js',
    downloadSchemaBefore,
    downloadSchemaAfter,
    "pdfUrl: z.coerce.string().optional().default('')",
  ),
  patchFile(
    'node_modules/paper-search-cli/dist/capabilities/pdf-discovery/tools.js',
    downloadToolsBefore,
    downloadToolsAfter,
    'Optional already-known direct PDF URL',
  ),
  patchFile(
    'node_modules/paper-search-cli/dist/capabilities/pdf-discovery/OpenAccessFallbackService.js',
    fallbackImportBefore,
    fallbackImportAfter,
    'createSuppliedPdfUrlTier',
  ),
  patchFile(
    'node_modules/paper-search-cli/dist/capabilities/pdf-discovery/OpenAccessFallbackService.js',
    fallbackTiersBefore,
    fallbackTiersAfter,
    '        createSuppliedPdfUrlTier(),',
  ),
  patchFile(
    'node_modules/paper-search-cli/dist/capabilities/pdf-discovery/OpenAccessFallbackService.js',
    fallbackContextBefore,
    fallbackContextAfter,
    "pdfUrl: options.pdfUrl || ''",
  ),
  patchFile(
    'node_modules/paper-search-cli/dist/capabilities/pdf-discovery/tiers/directPdfUrl.js',
    directPdfBefore,
    directPdfAfter,
    'export function createSuppliedPdfUrlTier()',
  ),
];

process.stdout.write(`${JSON.stringify({ ok: true, results })}\n`);
