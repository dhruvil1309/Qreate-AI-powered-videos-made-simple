# Qreate — User Acceptance Test plan

**Product:** Qreate, a video studio that turns a topic into a publish-ready
vertical video for the Qoneqt Global Feed.

**Purpose of this document.** It lists what a person should be able to do with
Qreate, in the words of someone using it rather than someone who built it.
Each case says what to do and what you should see. Anyone can work through it
by hand; `run_uat.py` in this folder also runs most of it automatically.

---

## How to run these tests

### By hand

```powershell
$env:OFFLINE_MODE = "1"          # no API keys needed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Open <http://127.0.0.1:8000/> and work down the cases.

`OFFLINE_MODE=1` makes the studio use local templates, generated title cards
and no narration audio. Everything in the interface behaves the same; only the
content quality differs. Two cases are marked **[keys]** because they can only
be judged with real providers configured.

### Automatically

```powershell
.\.venv\Scripts\python.exe tests\uat\run_uat.py
```

It starts its own server on a spare port, drives a real browser, writes
`tests/uat/REPORT.md`, and exits non-zero if anything fails. Cases it cannot
judge without a person looking at the screen are reported as **MANUAL**.

---

## Severity

| Level | Meaning |
|---|---|
| **Critical** | The product is unusable or produces a wrong result. Ship-blocking. |
| **Major** | A main task is blocked or badly degraded, but a workaround exists. |
| **Minor** | Cosmetic, or an edge case most people will not hit. |

---

## A. Starting up

| ID | Scenario | Steps | Expected result | Severity |
|---|---|---|---|---|
| A1 | The studio opens | Open the site root | The studio appears with composer, phone preview and details panel. No errors in the browser console. | Critical |
| A2 | Engine status is honest | Read the panel under **Make video** | It names the script, research, visual and voice engines actually in use, and says "Offline mode" when no keys are set. | Major |
| A3 | Missing FFmpeg is called out | Run with FFmpeg off `PATH` | A warning appears saying videos cannot be rendered. The app still loads. | Major |
| A4 | Server unreachable is explained | Stop the server, reload | The engine panel opens itself and says how to start the server, instead of failing silently. | Major |
| A5 | Theme follows the system | Open with the OS set to dark | The studio is dark. Switching the toggle flips it, and the choice survives a reload. | Minor |
| A6 | Page identity | Look at the browser tab | The tab shows the Qreate name and icon, not a default document icon. | Minor |

## B. Making a video

| ID | Scenario | Steps | Expected result | Severity |
|---|---|---|---|---|
| B1 | Make one video | Type a topic, press **Make video** | The job starts, appears at the top of **Your videos**, and the preview switches to live progress. | Critical |
| B2 | Nothing typed | Press **Make video** with an empty box | Nothing is submitted. The topic box is focused and a message asks for a topic. | Major |
| B3 | Keyboard submit | Type a topic, press `Ctrl`/`Cmd`+`Enter` | The job starts, exactly as if the button were pressed. | Minor |
| B4 | Jump to the topic box | Press `/` while not typing | The topic box takes focus. | Minor |
| B5 | Trending ideas | Press a suggestion chip | The topic box fills with that idea. **New ideas** loads a different set. | Minor |
| B6 | Choices are respected | Set community, tone, language, visuals and length, then submit | The created job records exactly those choices. | Critical |
| B7 | Batch | Switch to **Batch**, enter three topics on three lines, submit | Three separate jobs are created and queued. The button counts them before you press it. | Major |
| B8 | Batch ignores blank lines | Enter topics with blank lines between them | Only the real topics become jobs. | Minor |
| B9 | Topic length limits | Try a 2-character topic, and a 600+ character topic | The short one is refused with a readable message. The long one is capped at 600 and the counter shows it. | Minor |
| B10 | Length bounds | Request a duration outside 20–90 seconds via the API | It is refused, rather than producing an unusable video. | Minor |

## C. Watching it build

| ID | Scenario | Steps | Expected result | Severity |
|---|---|---|---|---|
| C1 | Progress is live | Submit a job and watch | Stages tick over on their own, with no page refresh and no visible polling delay. | Critical |
| C2 | Stages are legible | Watch the preview during a build | Each of the eight stages shows pending, running, done or failed, with detail such as "3/5 scenes". | Major |
| C3 | Percentage matches | Compare the ring to the stage list | The ring and percentage reflect how many stages are finished. | Minor |
| C4 | The list keeps up | Watch **Your videos** during a build | The row shows the current stage and a progress bar that advances. | Major |
| C5 | Hover is not stolen | Hover a job row while another job is building | The row's actions stay usable. The list does not flicker or reset under you. | Major |
| C6 | No editing mid-build | Open a building job's **Script** tab | Edit buttons are disabled and the panel says editing is available once it finishes. | Major |
| C7 | Streams close cleanly | Let a job finish, then watch the network | The live connection closes when the job is done. It does not reconnect forever. | Major |
| C8 | Failure is explained | Make a job fail | The failing stage is marked, the error text is shown, and the job is listed as failed. | Critical |
| C9 | Restart safety | Kill the server mid-build and restart it | The interrupted job is marked failed with an explanation, not left stuck as "running". | Major |

## D. Reviewing the result

| ID | Scenario | Steps | Expected result | Severity |
|---|---|---|---|---|
| D1 | The video plays | Open a finished video | It plays in the phone frame, vertical, with sound and captions. | Critical |
| D2 | Quality verdict is visible | Look at the preview and the **Review** tab | A QA badge shows pass or a warning count. The tab lists every check with its measured value. | Critical |
| D3 | Blocking vs advisory | Open **Review** for a job with warnings | Checks that merely advise are marked as advisory and distinguished from blocking failures. | Major |
| D4 | Critic scores | Open **Review** | Each rubric category has a score and bar, with the overall score and how many rewrites it took. | Major |
| D5 | Scene thumbnails | Look below the phone | One thumbnail per scene, showing the actual rendered frame. | Major |
| D6 | Jump to a scene | Press a scene thumbnail | The player jumps to that scene. | Minor |
| D7 | Preview one scene | Press a scene card's thumbnail | That scene plays on its own. `Esc` or the close button dismisses it. | Minor |
| D8 | Older videos still show | Open a video made before thumbnails existed | Thumbnails appear anyway, generated on demand. | Minor |
| D9 | Build history | Open **Activity** | Per-stage timings and the job log are shown. | Minor |

## E. Changing it

| ID | Scenario | Steps | Expected result | Severity |
|---|---|---|---|---|
| E1 | Edit one scene | Change a scene's text, press **Save and re-render** | Only that scene is rebuilt; the video is reassembled with the change. | Critical |
| E2 | Unsaved work is marked | Type in a scene without saving | The card is highlighted and marked **Unsaved**. | Major |
| E3 | Typing is never lost | Type in a scene while another job is building | What you typed stays. A live update does not overwrite it. | Critical |
| E4 | Different visual | Press **Try another visual** | That scene gets a different visual, with the rest untouched. | Major |
| E5 | Swap the opening hook | Pick a different hook on the **Script** tab | The opening line changes and only scene 1 is re-rendered. | Major |
| E6 | Current hook is not re-run | Try to pick the hook already in use | It is shown as selected and cannot be re-applied. | Minor |
| E7 | Edit the post copy | Change title, description or hashtags, press **Save copy** | The caption and package update. **No video is re-rendered.** | Major |
| E8 | Hashtags are tidied | Enter `ISRO, #ISRO, deep space` | Saved as `#ISRO #deepspace` — hashed, de-duplicated, spaces removed. | Minor |
| E9 | Title is required | Clear the title | **Save copy** cannot be pressed. | Minor |
| E10 | Caption copies | Press **Copy caption** | The full caption reaches the clipboard. | Major |

## F. Managing your videos

| ID | Scenario | Steps | Expected result | Severity |
|---|---|---|---|---|
| F1 | Search | Type into the search box | The list narrows to matching topics or titles. | Minor |
| F2 | Filter by status | Press **In progress**, **Ready**, **Failed** | Only matching videos are listed; an empty result says so. | Minor |
| F3 | Open a video | Press a row | Its preview, script, review and post load. | Critical |
| F4 | Delete | Delete a finished video, confirm | It leaves the list and its files are removed from disk. | Major |
| F5 | Deletion is guarded | Try to delete a building video | It is refused with an explanation. | Major |
| F6 | Retry a failure | Press retry on a failed video | It runs again from the start. | Major |
| F7 | Totals | Look at the top bar | Counts of made, running and ready, plus average score and build time. | Minor |

## G. Publishing

| ID | Scenario | Steps | Expected result | Severity |
|---|---|---|---|---|
| G1 | AI labelling is prompted | Open the **Post** tab | A clear note says Qreate does not post for you and the post must be marked AI-generated. | Critical |
| G2 | Download the video | Press **Download video** | An MP4 downloads, 1080×1920, H.264/AAC. | Critical |
| G3 | Download the package | Press **Package** | A ZIP containing the video, thumbnail, caption and plan. | Major |
| G4 | Sources are shown | Open **Post** for a researched topic | The sources used are listed and link out. | Major |
| G5 | Posting steps | Read the **Post it on Qoneqt** list | Clear manual steps naming the chosen community. | Minor |

## H. Robustness

| ID | Scenario | Steps | Expected result | Severity |
|---|---|---|---|---|
| H1 | Unknown video | Request a video ID that does not exist | A clear "no job with that id" message, not a crash. | Major |
| H2 | Bad input | Send malformed values to the API | Refused with a readable reason. | Major |
| H3 | Not-ready downloads | Request the video of a job that has not rendered | Refused with "not ready yet", not a server error. | Major |
| H4 | Missing thumbnails | Request a scene thumbnail that cannot exist | Refused cleanly; the studio shows a placeholder, never a broken image. | Minor |
| H5 | Concurrency | Start several jobs at once | They queue and complete without corrupting each other. | Major |
| H6 | Non-Latin topics | Use a Hindi or emoji topic | It is accepted and stored and displayed correctly. | Major |

## I. Access and layout

| ID | Scenario | Steps | Expected result | Severity |
|---|---|---|---|---|
| I1 | Keyboard only | Tab through the studio | Every control is reachable with a visible focus ring. | Major |
| I2 | Screen reader labels | Inspect icon-only buttons | Each has a readable name. | Major |
| I3 | Tabs are announced | Inspect the Script/Review/Post/Activity tabs | Proper tab roles and selected state. | Major |
| I4 | Choice groups | Inspect the language/visuals/length toggles | Grouped and labelled, with the chosen option marked. | Minor |
| I5 | Phone width | View at 400px wide | Single column, preview first, nothing cut off, no sideways scrolling. | Major |
| I6 | Tablet width | View at ~1000px wide | Two columns with details below. Nothing overlaps. | Minor |
| I7 | Reduced motion | Enable the OS reduced-motion setting | Animations stop; nothing becomes unusable. | Minor |
| I8 | Text contrast | Check body text against its background | Meets WCAG AA (4.5:1) in both themes. | Major |

## J. Quality of the output **[keys]**

These need real providers configured and a person watching the video.

| ID | Scenario | Expected result | Severity |
|---|---|---|---|
| J1 | The video is watchable | Captions are readable and in time with the narration, visuals change per scene, audio is level, and it opens with a hook. | Critical |
| J2 | The content is sound | The script matches the topic, the research sources support it, and nothing is unsafe or misleading. | Critical |

---

## Recording results

| Field | |
|---|---|
| Tested by | |
| Date | |
| Build / commit | |
| Mode | offline / with keys |
| Result | pass / pass with issues / fail |
