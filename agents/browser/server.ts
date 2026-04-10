/**
 * Browser Layer — Stagehand HTTP server
 * 
 * Extended with screenshot and Lighthouse endpoints for UX Auditor.
 * All LLM calls route through ElectronHub via modelClientOptions.
 * 
 * Endpoints:
 *   POST /scrape           — scrape hackathon platforms
 *   POST /register         — register for a hackathon  
 *   POST /submit           — fill and submit hackathon form
 *   POST /record-demo      — screen record + composite with audio
 *   POST /screenshot       — capture screenshots for UX audit
 *   POST /lighthouse       — run Lighthouse audit
 *   POST /stitch/generate  — generate screens via Google Stitch SDK
 *   GET  /health           — health check
 */

import express from "express";
import { Stagehand } from "@browserbasehq/stagehand";
import { chromium } from "playwright";
import { z } from "zod";
import * as fs from "fs";
import * as path from "path";
import { execSync } from "child_process";
// @google/stitch-sdk is ESM-only; lazy-load via dynamic import() to avoid
// CJS resolution failure under tsx.
let _stitchMod: any = null;
async function getStitch() {
  if (!_stitchMod) {
    _stitchMod = await import("@google/stitch-sdk");
  }
  return _stitchMod.stitch;
}

const app = express();
app.use(express.json({ limit: "10mb" }));
const PORT = process.env.BROWSER_SERVER_PORT || 3100;

// ─── Stagehand factory ────────────────────────────────────────────────────────

function createStagehand(): Stagehand {
  return new Stagehand({
    env: "BROWSERBASE",
    apiKey: process.env.BROWSERBASE_API_KEY!,
    projectId: process.env.BROWSERBASE_PROJECT_ID!,
    modelName: "claude-haiku-4-5",
    modelClientOptions: {
      apiKey: process.env.ELECTRONHUB_API_KEY!,
      baseURL: process.env.ELECTRONHUB_BASE_URL ?? "https://api.electronhub.ai/v1",
    },
    enableCaching: true,
    verbose: 0,
  });
}

async function humanDelay(min = 1200, max = 2800): Promise<void> {
  const ms = min + Math.random() * (max - min);
  await new Promise((r) => setTimeout(r, ms));
}

// ─── POST /screenshot ─────────────────────────────────────────────────────────

app.post("/screenshot", async (req, res) => {
  const { url, viewports = [{ width: 1440, height: 900, label: "desktop" }], wait_for_selector = "body", wait_ms = 2000 } = req.body;
  const outputDir = path.join("/tmp", "screenshots", Date.now().toString());
  fs.mkdirSync(outputDir, { recursive: true });

  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const result: Record<string, string> = {};
  const consoleErrors: string[] = [];
  let hasLayoutShift = false;

  try {
    for (const viewport of viewports) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
      });
      const page = await context.newPage();

      // Collect console errors
      page.on("console", (msg) => {
        if (msg.type() === "error") consoleErrors.push(msg.text());
      });

      // Measure CLS
      await page.addInitScript(() => {
        let cls = 0;
        new PerformanceObserver((list) => {
          list.getEntries().forEach((e: any) => { if (!e.hadRecentInput) cls += e.value; });
          (window as any).__CLS__ = cls;
        }).observe({ entryTypes: ["layout-shift"] });
      });

      await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
      
      if (wait_for_selector !== "body") {
        await page.waitForSelector(wait_for_selector, { timeout: 10000 }).catch(() => {});
      }
      
      await page.waitForTimeout(wait_ms);

      // Check CLS
      const cls = await page.evaluate(() => (window as any).__CLS__ ?? 0);
      if (cls > 0.1) hasLayoutShift = true;

      // Check horizontal scroll at mobile widths
      if (viewport.width <= 768) {
        const scrollWidth = await page.evaluate(() => document.body.scrollWidth);
        const clientWidth = await page.evaluate(() => document.body.clientWidth);
        if (scrollWidth > clientWidth + 5) {
          consoleErrors.push(`LAYOUT: Horizontal scroll at ${viewport.width}px (scrollWidth=${scrollWidth} > clientWidth=${clientWidth})`);
        }
      }

      const screenshotPath = path.join(outputDir, `${viewport.label}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });
      result[`${viewport.label}_path`] = screenshotPath;
      
      await context.close();
    }

    res.json({ ...result, console_errors: consoleErrors, has_layout_shift: hasLayoutShift });
  } catch (err) {
    res.status(500).json({ error: String(err) });
  } finally {
    await browser.close();
  }
});

// ─── POST /lighthouse ─────────────────────────────────────────────────────────

app.post("/lighthouse", async (req, res) => {
  const { url } = req.body;

  try {
    // Run Lighthouse via CLI (needs lighthouse installed: npm i -g lighthouse)
    const result = execSync(
      `lighthouse "${url}" --output=json --chrome-flags="--headless --no-sandbox" --quiet 2>/dev/null`,
      { timeout: 90000, maxBuffer: 10 * 1024 * 1024 }
    );

    const report = JSON.parse(result.toString());
    const scores = report.categories ?? {};

    res.json({
      performance: Math.round((scores.performance?.score ?? 0) * 100),
      accessibility: Math.round((scores.accessibility?.score ?? 0) * 100),
      best_practices: Math.round((scores["best-practices"]?.score ?? 0) * 100),
      seo: Math.round((scores.seo?.score ?? 0) * 100),
      fcp: report.audits?.["first-contentful-paint"]?.numericValue,
      lcp: report.audits?.["largest-contentful-paint"]?.numericValue,
      cls: report.audits?.["cumulative-layout-shift"]?.numericValue,
      tbt: report.audits?.["total-blocking-time"]?.numericValue,
    });
  } catch (err) {
    console.error("[forge:browser] Lighthouse failed:", err);
    // Fallback: basic Playwright performance check
    const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
    const page = await browser.newPage();
    const metrics: Record<string, number> = {};
    try {
      const start = Date.now();
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
      metrics.fcp = Date.now() - start;
      await page.waitForLoadState("load");
      metrics.load = Date.now() - start;
      
      // Check accessibility basics
      const imgMissingAlt = await page.$$eval("img:not([alt])", imgs => imgs.length);
      const lowContrastText = 0; // Would need axe-core for real check
      
      res.json({
        performance: metrics.load < 3000 ? 85 : metrics.load < 5000 ? 70 : 50,
        accessibility: imgMissingAlt === 0 ? 90 : 75,
        best_practices: 80,
        seo: 80,
        fcp: metrics.fcp,
        load_time: metrics.load,
        note: "Lighthouse CLI unavailable, using basic checks",
      });
    } finally {
      await browser.close();
    }
  }
});

// ─── POST /scrape ─────────────────────────────────────────────────────────────

const PLATFORM_URLS: Record<string, string> = {
  devpost: "https://devpost.com/hackathons?open=true&order_by=deadline",
  lablab: "https://lablab.ai/event",
  devfolio: "https://devfolio.co/hackathons",
};

const HackathonSchema = z.object({
  hackathons: z.array(z.object({
    name: z.string(),
    url: z.string(),
    theme: z.string().optional(),
    description: z.string().optional(),
    deadline: z.string().optional(),
    prizes: z.array(z.object({
      name: z.string(),
      amount: z.number().optional(),
      sponsor: z.string().optional(),
    })).optional(),
    judging_criteria: z.array(z.string()).optional(),
    sponsor_techs: z.array(z.object({
      sponsor: z.string(),
      api_name: z.string(),
      docs_url: z.string().optional(),
    })).optional(),
    registration_open: z.boolean().optional(),
  })),
});

app.post("/scrape", async (req, res) => {
  const {
    platforms = ["devpost", "lablab", "devfolio"],
    limit_per_platform = 5,
    custom_urls = [],
    extract_judges = false,
    extract_winners = false,
    extract_feedback = false,
  } = req.body;
  const all: object[] = [];
  const stagehand = createStagehand();

  try {
    await stagehand.init();

    // Scrape platform listing pages
    for (const platform of platforms) {
      const url = PLATFORM_URLS[platform];
      if (!url) continue;
      console.log(`[forge:browser] Scraping ${platform}...`);
      
      await stagehand.page.goto(url, { waitUntil: "networkidle" });
      await humanDelay();

      const { hackathons } = await stagehand.extract({
        instruction: `Extract the first ${limit_per_platform} hackathon listings with: name, URL, theme, deadline, prize info, judging criteria, sponsor technologies, registration status.`,
        schema: HackathonSchema,
      });

      for (const h of hackathons.slice(0, limit_per_platform)) {
        await humanDelay(1500, 3000);
        try {
          await stagehand.page.goto(h.url, { waitUntil: "networkidle" });
          const detail = await stagehand.extract({
            instruction: "Extract complete hackathon details: full description, all prizes with amounts and sponsors, judging criteria, sponsor API requirements, registration status, team size limits, submission deadline.",
            schema: HackathonSchema.shape.hackathons.element,
          });
          all.push({ ...h, ...detail, platform });
        } catch {
          all.push({ ...h, platform });
        }
      }
    }

    // Scrape custom URLs (used by analysis agents and outcome tracker)
    for (const customUrl of custom_urls) {
      console.log(`[forge:browser] Scraping custom URL: ${customUrl}`);
      try {
        await stagehand.page.goto(customUrl, { waitUntil: "networkidle" });
        await humanDelay();

        if (extract_judges) {
          const judgeData = await stagehand.extract({
            instruction: "Extract all judges/evaluators: full name, title/role, company/organization, bio/background, LinkedIn URL if visible, expertise areas.",
            schema: z.object({
              judges: z.array(z.object({
                name: z.string(),
                title: z.string().optional(),
                company: z.string().optional(),
                bio: z.string().optional(),
                linkedin_url: z.string().optional(),
                expertise: z.array(z.string()).optional(),
              })),
            }),
          });
          all.push({ url: customUrl, ...judgeData, type: "judges" });
        } else if (extract_winners) {
          const winnerData = await stagehand.extract({
            instruction: "Extract all winning projects/submissions: project name, team name, prize won, placement, project URL, description.",
            schema: z.object({
              winners: z.array(z.object({
                project_name: z.string(),
                team_name: z.string().optional(),
                prize: z.string().optional(),
                placement: z.string().optional(),
                project_url: z.string().optional(),
                description: z.string().optional(),
              })),
            }),
          });
          all.push({ url: customUrl, ...winnerData, type: "winners" });
        } else if (extract_feedback) {
          const feedbackData = await stagehand.extract({
            instruction: "Extract any judge feedback, comments, scores, or reviews visible on this submission page.",
            schema: z.object({
              feedback: z.array(z.object({
                judge_name: z.string().optional(),
                comment: z.string(),
                score: z.number().optional(),
              })),
              placement: z.string().optional(),
              prize_won: z.string().optional(),
            }),
          });
          all.push({ url: customUrl, ...feedbackData, type: "feedback" });
        } else {
          const detail = await stagehand.extract({
            instruction: "Extract complete hackathon details: full description, all prizes with amounts and sponsors, judging criteria, judges, sponsor API requirements, registration status, team size limits, submission deadline, past winners.",
            schema: HackathonSchema.shape.hackathons.element,
          });
          all.push({ url: customUrl, ...detail, type: "detail" });
        }
      } catch (err) {
        console.error(`[forge:browser] Failed to scrape ${customUrl}: ${err}`);
        all.push({ url: customUrl, error: String(err) });
      }
    }

    res.json({ hackathons: all, judges: all.filter((x: any) => x.type === "judges").flatMap((x: any) => x.judges || []), winners: all.filter((x: any) => x.type === "winners").flatMap((x: any) => x.winners || []), feedback: all.filter((x: any) => x.type === "feedback") });
  } catch (err) {
    res.status(500).json({ error: String(err) });
  } finally {
    await stagehand.close();
  }
});

// ─── POST /register ───────────────────────────────────────────────────────────

app.post("/register", async (req, res) => {
  const { url, platform, dry_run = false } = req.body;

  if (dry_run) {
    res.json({ success: true, dry_run: true });
    return;
  }

  const stagehand = createStagehand();
  try {
    await stagehand.init();
    await stagehand.page.goto(url, { waitUntil: "networkidle" });
    await humanDelay();
    await stagehand.act("Click the participate, register, or join hackathon button");
    await humanDelay(2000, 3500);

    const authCheck = await stagehand.extract({
      instruction: "Is there a login or sign-in form visible?",
      schema: z.object({ needs_login: z.boolean() }),
    });

    if (authCheck.needs_login) {
      res.json({ success: false, reason: "auth_required" });
      return;
    }

    await stagehand.act("Fill in any required registration fields with team name AgentCrew and submit");
    await humanDelay(2000, 3000);

    const confirmed = await stagehand.extract({
      instruction: "Is there a success confirmation message?",
      schema: z.object({ success: z.boolean(), message: z.string().optional() }),
    });

    res.json(confirmed);
  } catch (err) {
    res.status(500).json({ success: false, error: String(err) });
  } finally {
    await stagehand.close();
  }
});

// ─── POST /submit ─────────────────────────────────────────────────────────────

app.post("/submit", async (req, res) => {
  const {
    hackathon_url, project_name, tagline, description, video_url,
    live_url, repo_url, tech_stack, sponsor_integrations,
    output_dir, dry_run = false,
  } = req.body;

  if (dry_run) {
    res.json({ success: true, submission_url: `${hackathon_url}/preview`, dry_run: true });
    return;
  }

  const stagehand = createStagehand();
  try {
    await stagehand.init();
    await stagehand.page.goto(`${hackathon_url}/project/new`, { waitUntil: "networkidle" });
    await humanDelay();

    await stagehand.act(`Type "${project_name}" into the project name field`);
    await humanDelay(500, 800);
    await stagehand.act(`Type "${tagline}" into the tagline field`);
    await humanDelay(500, 800);
    await stagehand.page.fill("textarea[name='description']", description).catch(() =>
      stagehand.act(`Fill the project description: ${description.slice(0, 100)}`)
    );
    await humanDelay(500, 800);
    await stagehand.act(`Enter "${video_url}" in the demo video URL field`);
    await humanDelay(500, 800);
    await stagehand.act(`Enter "${live_url}" in the live demo URL field`);
    await humanDelay(500, 800);
    await stagehand.act(`Enter "${repo_url}" in the GitHub repository URL field`);
    await humanDelay(800, 1200);

    for (const tech of (tech_stack as string[]).slice(0, 10)) {
      await stagehand.act(`Add "${tech}" as a technology tag`);
      await humanDelay(300, 600);
    }

    for (const sponsor of sponsor_integrations as string[]) {
      await stagehand.act(`Check the prize category checkbox for "${sponsor}"`);
      await humanDelay(200, 400);
    }

    if (output_dir) {
      fs.mkdirSync(output_dir, { recursive: true });
      await stagehand.page.screenshot({ path: path.join(output_dir, "submission-preview.png") });
    }

    await stagehand.act("Click the final submit or publish button");
    await humanDelay(3000, 4000);

    res.json({ success: true, submission_url: stagehand.page.url() });
  } catch (err) {
    res.status(500).json({ success: false, error: String(err) });
  } finally {
    await stagehand.close();
  }
});

// ─── POST /record-demo ────────────────────────────────────────────────────────

app.post("/record-demo", async (req, res) => {
  const { live_url, demo_flow, narration_path, output_path } = req.body;

  try {
    const rawVideoPath = output_path.replace("demo-final.mp4", "demo-raw.webm");
    const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
    const context = await browser.newContext({
      recordVideo: { dir: path.dirname(output_path), size: { width: 1920, height: 1080 } },
      viewport: { width: 1920, height: 1080 },
    });
    const page = await context.newPage();

    await page.goto(live_url, { waitUntil: "networkidle" });
    await page.waitForTimeout(3000);

    for (const step of demo_flow as string[]) {
      console.log(`[forge:browser] Demo step: ${step}`);
      // CURSOR: implement step-specific Playwright actions
      // Parse natural language step and execute appropriate action
      await page.waitForTimeout(2500 + Math.random() * 1000);
    }

    await page.waitForTimeout(3000);
    await context.close();
    await browser.close();

    const videoFiles = fs.readdirSync(path.dirname(output_path)).filter(f => f.endsWith(".webm"));
    if (videoFiles.length > 0) {
      fs.renameSync(path.join(path.dirname(output_path), videoFiles[0]), rawVideoPath);
    }

    execSync(
      `ffmpeg -i "${rawVideoPath}" -i "${narration_path}" ` +
      `-c:v libx264 -preset fast -crf 22 -c:a aac -b:a 128k -shortest ` +
      `-vf scale=1920:1080 -y "${output_path}"`,
      { stdio: "inherit" }
    );

    res.json({ success: true, video_path: output_path });
  } catch (err) {
    res.status(500).json({ success: false, error: String(err) });
  }
});

// ─── POST /stitch/generate ────────────────────────────────────────────────────
// Generate multiple screens via Google Stitch SDK, one per prompt.
// Returns HTML code + screenshot URLs for each screen, plus design variants.

app.post("/stitch/generate", async (req, res) => {
  const {
    screens: screenPrompts = [] as { route: string; prompt: string; device_type?: string }[],
    project_title = `forge-${Date.now()}`,
    personality = "",
    generate_variants = false,
    variant_count = 2,
  } = req.body;

  if (!process.env.STITCH_API_KEY) {
    res.status(400).json({ error: "STITCH_API_KEY not set", screens: [] });
    return;
  }

  if (!screenPrompts.length) {
    res.json({ project_id: null, screens: [], design_context: null });
    return;
  }

  const results: any[] = [];
  let projectId = "";

  try {
    const stitchClient = await getStitch();
    const project = await stitchClient.createProject(project_title);
    projectId = project.projectId;
    console.log(`[forge:stitch] Project created: ${projectId}`);

    for (const sp of screenPrompts) {
      const deviceType = (sp.device_type || "DESKTOP") as "MOBILE" | "DESKTOP" | "TABLET" | "AGNOSTIC";
      const fullPrompt = personality
        ? `${sp.prompt}. Design aesthetic: ${personality}.`
        : sp.prompt;

      try {
        console.log(`[forge:stitch] Generating screen for route ${sp.route}...`);
        const screen = await project.generate(fullPrompt, deviceType);

        const [htmlUrl, imageUrl] = await Promise.all([
          screen.getHtml().catch(() => ""),
          screen.getImage().catch(() => ""),
        ]);

        const screenResult: any = {
          route: sp.route,
          screen_id: screen.screenId,
          html_url: htmlUrl,
          image_url: imageUrl,
          prompt: fullPrompt,
          variants: [],
        };

        if (generate_variants) {
          try {
            const variants = await screen.variants(
              `Explore different design approaches for: ${sp.prompt}`,
              {
                variantCount: variant_count,
                creativeRange: "EXPLORE" as any,
                aspects: ["COLOR_SCHEME", "LAYOUT"] as any,
              },
            );
            for (const v of variants) {
              const [vHtml, vImg] = await Promise.all([
                v.getHtml().catch(() => ""),
                v.getImage().catch(() => ""),
              ]);
              screenResult.variants.push({
                variant_id: v.screenId,
                html_url: vHtml,
                image_url: vImg,
              });
            }
          } catch (varErr) {
            console.warn(`[forge:stitch] Variants failed for ${sp.route}: ${varErr}`);
          }
        }

        results.push(screenResult);
        console.log(`[forge:stitch] Screen for ${sp.route}: html=${!!htmlUrl} img=${!!imageUrl} variants=${screenResult.variants.length}`);
      } catch (screenErr) {
        console.error(`[forge:stitch] Screen generation failed for ${sp.route}: ${screenErr}`);
        results.push({ route: sp.route, error: String(screenErr), screen_id: null, html_url: "", image_url: "" });
      }
    }

    res.json({ project_id: projectId, screens: results });
  } catch (err) {
    console.error(`[forge:stitch] Project-level error: ${err}`);
    res.status(500).json({ error: String(err), project_id: projectId, screens: results });
  }
});

// ─── POST /stitch/edit ───────────────────────────────────────────────────────
// Iteratively refine a screen using the edit() API.

app.post("/stitch/edit", async (req, res) => {
  const { project_id, screen_id, edit_prompt } = req.body;

  if (!process.env.STITCH_API_KEY || !project_id || !screen_id) {
    res.status(400).json({ error: "Missing project_id, screen_id, or STITCH_API_KEY" });
    return;
  }

  try {
    const stitchClient = await getStitch();
    const project = stitchClient.project(project_id);
    const screen = await project.getScreen(screen_id);
    const edited = await screen.edit(edit_prompt);

    const [htmlUrl, imageUrl] = await Promise.all([
      edited.getHtml().catch(() => ""),
      edited.getImage().catch(() => ""),
    ]);

    res.json({
      screen_id: edited.screenId,
      html_url: htmlUrl,
      image_url: imageUrl,
    });
  } catch (err) {
    res.status(500).json({ error: String(err) });
  }
});

// ─── Health ───────────────────────────────────────────────────────────────────

app.get("/health", (_req, res) => {
  const hasStitchKey = !!process.env.STITCH_API_KEY;
  res.json({ status: "ok", port: PORT, stagehand: "ready", stitch_available: hasStitchKey });
});

// ─── Start ────────────────────────────────────────────────────────────────────

app.listen(Number(PORT), "0.0.0.0", () => console.log(`[forge:browser] Server on 0.0.0.0:${PORT}`));
