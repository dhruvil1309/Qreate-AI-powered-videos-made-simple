<p align="center">
  <img src="web/favicon.svg" width="84" alt="Qreate logo">
</p>

<h1 align="center">Qreate</h1>

<h3 align="center">Topic in. Publish-ready Qoneqt reel out.</h3>

<p align="center">
  An AI video studio that turns any topic, prompt, idea or trend into a captioned 9:16 video
  for the <b>Qoneqt Global Feed</b>.<br>
  One repeatable pipeline researches, writes, critiques, voices, edits, quality-checks and packages every reel,
  in <b>English, हिन्दी and Hinglish</b>.
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white">
  <img alt="Pydantic v2" src="https://img.shields.io/badge/Pydantic-v2-E92063?logo=pydantic&logoColor=white">
  <img alt="FFmpeg" src="https://img.shields.io/badge/FFmpeg-video-007808?logo=ffmpeg&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white">
  <br>
  <img alt="pytest" src="https://img.shields.io/badge/pytest-21%20passing-2ea44f">
  <img alt="UAT" src="https://img.shields.io/badge/UAT-74%20passing-2ea44f">
  <img alt="No keys needed" src="https://img.shields.io/badge/API%20keys-optional-6A35F0">
  <img alt="Languages" src="https://img.shields.io/badge/English%20%C2%B7%20Hindi%20%C2%B7%20Hinglish-supported-6A35F0">
</p>

<p align="center">
  Built by <b>Team Fantastic Four</b> for <b>Qoneqt × CTRL FREAK 2026</b>: LLM-Powered Content Pipeline
</p>

<p align="center">
  <a href="https://qoneqt.com/qlips/8080"><b>▶ Our reel on Qoneqt</b></a> ·
  <a href="https://youtu.be/41FZuaFv9hQ"><b>🎥 Demo video</b></a> ·
  <a href="https://youtu.be/1v8AfLAQ8ko"><b>🎙️ Project explanation</b></a> ·
  <a href="#demo">Demo</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#the-llm-layer">LLM layer</a> ·
  <a href="#tech-stack">Tech stack</a> ·
  <a href="#api-reference">API</a>
</p>

![Qreate title card: team Fantastic Four, team code and members, with a finished reel in a phone](docs/images/slides/title.jpg)

---

## Contents

| | | |
|---|---|---|
| **Overview**<br>[Team](#team)<br>[Demo](#demo)<br>[At a glance](#at-a-glance)<br>[The problem and our answer](#the-problem-and-our-answer)<br>[Features, with screenshots](#features-with-screenshots)<br>[Sample output](#sample-output) | **How it's built**<br>[How it works](#how-it-works)<br>[The LLM layer](#the-llm-layer)<br>[The media engine](#the-media-engine)<br>[Jobs, edits and caching](#jobs-edits-and-caching)<br>[Architecture](#architecture)<br>[Tech stack](#tech-stack) | **Use and run it**<br>[Quick start](#quick-start)<br>[Using the studio](#using-the-studio)<br>[Command line](#command-line)<br>[Configuration](#configuration)<br>[API reference](#api-reference)<br>[What you get](#what-you-get)<br>[Quality checks](#quality-checks)<br>[Testing](#testing)<br>[Deployment](#deployment)<br>[Optional: Wan 2.1](#optional-wan-21-local-text-to-video)<br>[Project layout](#project-layout)<br>[Troubleshooting](#troubleshooting)<br>[Responsible AI and security](#responsible-ai-and-security)<br>[Limitations and roadmap](#limitations-and-roadmap) |

---

## Team

| | |
|---|---|
| 👥 **Team** | Fantastic Four |
| 🔑 **Team code** | `team-7D4CF0F857DD` |
| 🧑‍💻 **Members** | Dhruvil Prajapati · Ronak Hinglajiya · Mihir Bhavsar · Vishwa Patel |
| 🏁 **Challenge** | Qoneqt × CTRL FREAK 2026: LLM-Powered Content Pipeline |
| 🎥 **Demo video** | [youtu.be/41FZuaFv9hQ](https://youtu.be/41FZuaFv9hQ) |
| 🎙️ **Project explanation** | [youtu.be/1v8AfLAQ8ko](https://youtu.be/1v8AfLAQ8ko) (with our voice-over) |
| 📱 **Our reel on Qoneqt** | [qoneqt.com/qlips/8080](https://qoneqt.com/qlips/8080) |
| 💻 **Repository** | [dhruvil1309/Qreate-AI-powered-videos-made-simple](https://github.com/dhruvil1309/Qreate-AI-powered-videos-made-simple) |

---

## Demo

### ▶ Watch our reel on Qoneqt

<p align="center">
  <a href="https://qoneqt.com/qlips/8080"><img alt="Watch on Qoneqt" src="https://img.shields.io/badge/%E2%96%B6%20Watch%20on%20Qoneqt-qlips%2F8080-6A35F0?style=for-the-badge"></a>
</p>

**Qoneqt video link:** <https://qoneqt.com/qlips/8080>

This is our **customised, LLM-generated video**, made end to end with Qreate and published on Qoneqt:
- the LLM agents researched the topic, wrote the script and critiqued it;
- the pipeline generated the visuals and the voice, then edited, captioned and quality-checked the reel;
- we published the final reel as a Qoneqt Qlip.

### 🎥 Demo video

<p align="center">
  <a href="https://youtu.be/41FZuaFv9hQ" title="Watch the Qreate demo on YouTube">
    <img src="https://img.youtube.com/vi/41FZuaFv9hQ/maxresdefault.jpg" alt="Qreate demo video by Team Fantastic Four. Click to play on YouTube." width="760">
  </a>
  <br><br>
  <a href="https://youtu.be/41FZuaFv9hQ"><img src="https://img.shields.io/badge/▶_Watch_the_demo-YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="Watch the demo on YouTube"></a>
  <br>
  <sub>👆 Click the preview to play the full demo on YouTube · <a href="https://youtu.be/41FZuaFv9hQ">youtu.be/41FZuaFv9hQ</a></sub>
</p>

### 🎙️ Project explanation video (with our voice-over)

<p align="center">
  <a href="https://youtu.be/1v8AfLAQ8ko" title="Watch the Qreate project explanation on YouTube">
    <img src="https://img.youtube.com/vi/1v8AfLAQ8ko/maxresdefault.jpg" alt="Qreate project explanation by Team Fantastic Four, with the team's voice-over. Click to play on YouTube." width="760">
  </a>
  <br><br>
  <a href="https://youtu.be/1v8AfLAQ8ko"><img src="https://img.shields.io/badge/▶_Watch_the_explanation-YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="Watch the project explanation on YouTube"></a>
  <br>
  <sub>🎙️ Our team explains Qreate in our own voice-over · <a href="https://youtu.be/1v8AfLAQ8ko">youtu.be/1v8AfLAQ8ko</a></sub>
</p>

### 📡 See it in action

<table>
  <tr>
    <td align="center" width="34%">
      <img src="docs/images/live-build.gif" width="300" alt="Live build: progress streams stage by stage, then the finished reel appears"><br>
      <sub><b>A real build, streamed live</b><br>(time-lapse of the actual job)</sub>
    </td>
    <td align="center" width="66%">
      <img src="docs/images/reels/four-reels.gif" width="560" alt="Four reels made by Qreate, playing side by side"><br>
      <sub><b>Four reels made by Qreate</b><br>English · Hinglish · Hindi · English</sub>
    </td>
  </tr>
</table>

---

## At a glance

| | | | |
|:---:|:---:|:---:|:---:|
| 🧭 **8**<br><sub>pipeline stages, topic to package</sub> | 🤖 **3**<br><sub>LLM agents: research, script, critic</sub> | 🔀 **4**<br><sub>LLM providers behind one router</sub> | 🗣️ **3**<br><sub>languages: English, Hindi, Hinglish</sub> |
| 🎯 **6**<br><sub>critic rubric criteria, pass mark 7.5</sub> | ✅ **10**<br><sub>automated QA checks (6 blocking)</sub> | 📱 **1080×1920**<br><sub>H.264/AAC, 30 fps, −14 LUFS</sub> | ⏱️ **~4 min**<br><sub>per 30-second reel on free tiers</sub> |
| 📦 **50**<br><sub>topics per batch request</sub> | ✂️ **1 scene**<br><sub>re-rendered per edit, not the whole reel</sub> | 🔑 **0**<br><sub>API keys needed to run</sub> | 🧪 **21 + 74**<br><sub>pytest tests + UAT cases passing</sub> |

---

## The problem and our answer

![The problem: a reel takes hours, quality is uneven, and one-by-one doesn't scale](docs/images/slides/problem.jpg)

Qoneqt asked how AI can turn ideas into engaging videos for the Global Feed **at scale**.

- **Hours per reel.** Research, scripting, finding visuals, recording a voice, editing and captioning are all manual.
- **Uneven quality.** Nothing checks the hook, the facts, the pacing or the format before a post goes out.
- **One by one doesn't scale.** Each new topic restarts the whole process from scratch.

**The gap:** no repeatable, fact-grounded, community-aware pipeline with quality control built in.
Qreate is that pipeline.

![Relevance: the brief mapped to what Qreate delivers](docs/images/slides/fit.jpg)

| The brief asks for | Qreate delivers | Where |
|---|---|---|
| Input: a topic, prompt, idea or trend | Free text, batch lists of up to 50 topics, live Google Trends for India | Composer, `/api/batch`, `/api/trends` |
| An LLM that writes the script and story | Research-grounded script agent with a critic agent and a rewrite loop | [The LLM layer](#the-llm-layer) |
| Multimodal models for visuals and video | AI images, stock footage, optional local AI video, neural voices | [The media engine](#the-media-engine) |
| A pipeline that composes and processes | FFmpeg edit, word-synced captions, loudness levelling, 10-check QA gate | [How it works](#how-it-works) |
| Ready-to-publish Global Feed video | 1080×1920 MP4 + thumbnail + title, description and hashtags, zipped | [What you get](#what-you-get) |
| Repeatable, at scale | Batch queue, parallel workers, scene-level caching, jobs saved on disk | [Jobs, edits and caching](#jobs-edits-and-caching) |

**Humans stay in charge.** Every reel can be reviewed and edited scene by scene before posting, and every
post carries a reminder to label it as AI-generated.

---

## Features, with screenshots

### 🎛️ The studio

![The Qreate studio: composer, phone preview with the finished reel, and the editable script](docs/images/studio.jpg)

The studio has three columns. On the left you **create**, in the middle a **phone preview** plays the reel,
and on the right you **inspect and edit** the selected video. The header shows totals: videos made, ready,
average critic score and average build time.

### ✍️ Create: one video or a batch

<table>
  <tr>
    <td width="50%"><img src="docs/images/batch.jpg" alt="Batch mode with three topics, ready to make three videos"></td>
    <td width="50%"><img src="docs/images/engines.jpg" alt="Engines panel showing which providers are live"></td>
  </tr>
  <tr>
    <td><sub><b>Batch mode:</b> one topic per line becomes a queue of videos ("Make 3 videos").</sub></td>
    <td><sub><b>Engines panel:</b> which script, research, visual and voice engines are live, with hints for keys you could add.</sub></td>
  </tr>
</table>

- **Topic box:** any topic, prompt, idea or trend, up to 600 characters.
- **Trending chips:** live Google Trends for India. **New ideas** fetches a fresh set.
- **Community:** pick or type a Qoneqt community (Study Buddies, Space Nerds, Tech Talk, Finance Basics, Health & Fitness, …).
- **Tone:** energetic, calm and clear, funny, inspiring, or serious explainer.
- **Language:** English, Hinglish (Roman script) or Hindi (Devanagari).
- **Visuals:** **Mix** lets the script choose per scene, **Real footage** prefers stock, **AI images** prefers generated art.
- **Length:** 30, 45 or 60 seconds. The API accepts anything from 20 to 90.
- **Shortcuts:** `Ctrl`/`⌘` + `Enter` submits from anywhere; `/` jumps to the topic box.

### 📡 Watch it build, live

<table>
  <tr>
    <td width="62%"><img src="docs/images/live-build.jpg" alt="Live build: stage list with timings inside the phone preview"></td>
    <td width="38%">
      Progress streams over <b>Server-Sent Events</b>, with no page refresh and no polling.<br><br>
      The phone shows a progress ring, the running stage, and every finished stage with its <b>real duration</b>
      and result (for example "3 sources", "5 scenes by openai", "8.0/10 after 1 rewrite").<br><br>
      The script, including its alternative hooks, appears on the right as soon as it's written, before any media exists.
    </td>
  </tr>
</table>

### 🎬 Play, jump to any scene, preview one scene

<table>
  <tr>
    <td width="50%"><img src="docs/images/scene-preview.jpg" alt="A single scene playing on its own in a lightbox"></td>
    <td width="50%"><img src="docs/images/mobile.jpg" width="300" alt="Phone layout of the studio"></td>
  </tr>
  <tr>
    <td><sub><b>Single-scene preview:</b> click any scene thumbnail in the Script tab to play that scene alone.</sub></td>
    <td><sub><b>Works on phones:</b> the layout reflows for small screens.</sub></td>
  </tr>
</table>

- The finished reel plays in the phone frame with a **QA badge** ("QA passed" or "N warnings").
- The **scene strip** shows a thumbnail per scene. Click one to jump the player to that scene.
- Buttons: **Download video**, **Package** (ZIP), **Open full size**.

### 🧐 Review: the critic's scores and the QA checklist

![Review tab: overall 8/10, six rubric bars, what the critic flagged, and the quality checklist](docs/images/review.jpg)

- **Overall score**, how many rewrites it took ("Rewritten 1 time to get here" or "Approved on the first pass"), and which model judged it.
- **Six rubric bars:** hook, clarity, accuracy, pacing, community fit and safety. Bars are coloured good (≥ 8), mid (≥ 6.5) or poor.
- **What the critic flagged:** up to 6 concrete fixes.
- **Quality checks:** all 10 checks with their measured values. Advisory checks are tagged so they're not mistaken for blockers.

### ✏️ Edit any scene, re-render only that scene

- **Opening hook:** pick one of the script agent's alternative hooks. Only scene 1's narration is re-recorded.
- **Per scene:** edit the on-screen text, the narration, and the image prompt or footage search, then **Save and re-render**.
- **Try another visual:** re-rolls just that scene's visual with a new seed or the next search result.
- Edits in progress are flagged "Unsaved" and kept while you type. Live progress updates never overwrite them.

### 📣 Post: publish-ready copy, no re-render

![Post tab: AI-label reminder, editable caption fields and a live preview](docs/images/post.jpg)

- Edit the **title, description and hashtags**, and see a live preview of the caption.
- **Save copy** rewrites `post.txt`, `plan.json` and the ZIP package **without touching the video**.
- **Copy caption**, download links, a step-by-step posting guide, and the research **sources**.
- A reminder to **label the post as AI-generated** on Qoneqt.

### ⏱️ Activity: real timings for every stage

![Activity tab: per-stage timings, total compute time and the job log](docs/images/activity.jpg)

### 🗂️ Library, filters and dark mode

![Dark theme with a Hindi reel about UPI](docs/images/studio-dark-hindi.jpg)

- **Your videos:** search by title or topic; filter by All, In progress, Ready or Failed.
- **Retry** a failed job, or **delete** a job together with its files.
- **Light and dark themes:** follows your system setting and remembers your choice.

---

## Sample output

Every image below is a frame from a reel Qreate made end to end: script, visuals, voice, captions and edit.

<table>
  <tr>
    <td align="center"><img src="docs/images/reels/reel1.jpg" width="190" alt="English reel about Chandrayaan-3"></td>
    <td align="center"><img src="docs/images/reels/reel2.jpg" width="190" alt="Hinglish reel about ISRO's low-cost missions"></td>
    <td align="center"><img src="docs/images/reels/reel3.jpg" width="190" alt="Hindi reel about UPI"></td>
    <td align="center"><img src="docs/images/reels/reel4.jpg" width="190" alt="English reel about study habits"></td>
  </tr>
  <tr>
    <td align="center"><sub><b>English</b> · Space Nerds<br>"Chandrayaan-3: India's Stellar Moon Landing Journey"<br>27.3 s · AI images</sub></td>
    <td align="center"><sub><b>Hinglish</b> · Space Nerds<br>"ISRO Missions: Choti Cost, Badi Success"<br>27.5 s · critic 8.0 · 10/10 QA</sub></td>
    <td align="center"><sub><b>हिन्दी</b> · Finance Basics<br>"UPI ने भारत में पेमेंट को कैसे बदला?"<br>18.1 s · AI images</sub></td>
    <td align="center"><sub><b>English</b> · Study Buddies<br>"5 Study Habits Backed by Science"<br>18.3 s · 10/10 QA</sub></td>
  </tr>
</table>

**One reel, scene by scene:** each scene has its own visual, a headline, and captions that highlight the word
being spoken.

![Five scenes of the Chandrayaan-3 reel](docs/images/reels/scenes-strip.jpg)

---

## How it works

![Our solution: input, AI agents, output and the 8 pipeline stages](docs/images/slides/solution.jpg)

```mermaid
flowchart TB
    subgraph W["Write: LLM agents"]
        direction LR
        A(["Topic, prompt or trend"]) --> R["1 · Research<br/>Wikipedia + Tavily"]
        R --> S["2 · Script agent<br/>hook + scene plan (JSON)"]
        S --> C{"3 · Critic agent<br/>score ≥ 7.5?"}
        C -- "no: rewrite, max 2 rounds" --> S
    end
    subgraph M["Make: media pipeline"]
        direction LR
        V["4 · Visuals + voice<br/>per scene, in parallel"] --> RN["5 · Render<br/>word-synced captions"]
        RN --> E["6 · Edit and mix<br/>loudness −14 LUFS"]
        E --> Q["7 · QA gate<br/>10 checks"]
        Q --> P(["8 · Package<br/>MP4 · thumbnail · post · ZIP"])
    end
    W -- "score ≥ 7.5, or rounds used up" --> M
```

| # | Stage (as shown in the studio) | What happens | Output |
|:-:|---|---|---|
| 1 | **Research the topic** | Wikipedia's top 3 matching articles, plus Tavily web search when a key is set. Up to 8 notes with source links. | `notes.json` |
| 2 | **Write hook and scene plan** | The script agent writes the hook, alternative hooks and a scene-by-scene plan as strict JSON. | `plan.json` |
| 3 | **Critique and rewrite** | The critic scores 6 criteria. Below 7.5 the script is rewritten with the critic's fixes, up to 2 rounds. | critique in `job.json` |
| 4 | **Find visuals, record voice** | Every scene gets a visual and a narration track, 4 scenes at a time, with caching. | `scenes/NN/assets.json` |
| 5 | **Render scenes with captions** | Background motion, headline, word-highlighted captions and voice are composed per scene, 2 scenes at a time. | `scenes/NN/scene.mp4` |
| 6 | **Edit, mix and level audio** | Scenes are joined, an optional music bed is mixed in, and loudness is normalised. | `output/qreate-<slug>.mp4` |
| 7 | **Run quality checks** | 10 technical and editorial checks; 6 of them decide whether the video is ready. | QA in `job.json` |
| 8 | **Package for Qoneqt** | Thumbnail, `post.txt` and `plan.json` are zipped with the video. | `package.zip` |

### Where the time goes

Measured on a real 30-second English reel ("5 Study Habits Backed by Science") with free-tier providers:

```mermaid
pie showData title Build time of a real 30-second reel (225 s total)
    "Find visuals, record voice" : 205.1
    "Write hook and scene plan" : 7.8
    "Render scenes with captions" : 4.9
    "Critique and rewrite" : 3.8
    "Research the topic" : 2.7
    "Edit, mix, QA and package" : 1.2
```

Over 90% of the build is the visuals-and-voice stage, and almost all of that is waiting for images. The free
Pollinations tier allows roughly **one image every 50 seconds**, so Qreate queues image requests and retries
politely. Research, script and critic together take about 15 seconds; rendering, editing and QA about 6.

### One request, end to end

```mermaid
sequenceDiagram
    autonumber
    actor U as Creator
    participant S as Studio (browser)
    participant A as FastAPI
    participant W as Worker thread
    participant L as LLM agents
    participant P as Media providers
    participant F as FFmpeg
    U->>S: Topic and options, then Make video
    S->>A: POST /api/jobs
    A-->>S: 202 Accepted, job id
    S->>A: GET /api/stream/jobs/{id} (SSE)
    A->>W: queue the job
    W->>L: research, script, critic, rewrite
    W->>P: visuals and voice for every scene
    W->>F: render scenes, join, level audio
    W->>W: QA checks, then package
    A-->>S: a snapshot after every change
    A-->>S: event end (job finished)
    S->>A: GET /api/jobs/{id}/video
    U->>S: review, edit, download, publish
```

---

## The LLM layer

![LLM explanation: research, script and critic agents, the rewrite loop and the model router](docs/images/slides/llm.jpg)

Qreate uses hosted LLMs as **specialised agents** that share one structured plan, the `ScenePlan`. Each agent
has a narrow job and a validated contract, so the output of one is always safe input for the next.

### 🔎 Research agent: grounding

| | |
|---|---|
| **Wikipedia** (always, no key) | Searches for the topic, then fetches the summaries of the top 3 articles (up to 900 characters each) with their links. |
| **Tavily** (optional key) | Adds a search summary and up to 5 fresh web results. Useful for trending topics. |
| **Result** | Up to 8 notes, numbered `[1] title: snippet` in the script prompt. Notes with a URL become the post's **Sources**. |
| **If nothing is found** | The prompt says "no research available, stay general and avoid specific statistics". The stage shows "No live sources". |

### ✍️ Script agent: the story

The script agent writes the whole reel as **one JSON object**. Its brief is sized from the target length:
about **2.4 spoken words per second**, split across `max(4, min(9, round(seconds ÷ 6.5)))` scenes.

<!-- ⚠️ The README pasted into chat ended here. Paste the rest of your original README below this line,
     starting from the "| Target | Scenes asked for | Spoken ..." table. -->
