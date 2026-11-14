# Kello live demo, Sunday 15 Nov 14:00: 3 minutes

The audience is AstraZeneca marketing, medical affairs and business excellence. Use one county, one page and one plan,
and end on the pilot ask. Timings come from a first-time run on 14 Nov (8742): the first screen loads in 0.8 s, the
county page in 0.2 s, **With the plan** is instant, a web check takes 22–33 s, and a stored plan opens in 0.6 s.
**A web check can make the plan rewrite itself: 40 s in English, 55 s in Finnish.** So the plan tabs are opened before
the check and never reloaded after it.

**Before you go on stage (10 minutes before)**
- Use a browser at 1280×720 or larger, zoomed to 125%.
- Tab 1: `http://127.0.0.1:8742/#/` (the first screen).
- Tab 2: `#/county/21`. Click **Today** above the dot chart (it opens on "With the plan"). On action 1, "Precise
  radiotherapy (SBRT) …", click **Check on the web** once and wait for the result, so this morning's answer is stored.
- Then tab 3: `#/plan/21?budget=1000000&lang=fi`, and wait until the page is written (up to 55 s after that check).
  Tab 4: `#/plan/21?budget=1000000&lang=en`, wait until written (up to 40 s). Do not reload tabs 3 and 4 after this.
- If a county page or plan takes 40 s on first load, it is regenerating, not broken. Wait it out before going on.

| Time | Click | Say |
|---|---|---|
| 0:00 | Tab 1, the first screen. Point at Lapland's dots, then Vantaa and Kerava's. | "You lead cancer care in Lapland. Of a hundred of your lung cancer patients, eighteen are treated to cure. In Vantaa and Kerava, thirty-six. Same country. Same cancer." |
| 0:15 | Click **See where Lapland loses patients** (opens tab 2's page; or switch to tab 2). Point at the line under the headline. | "Lapland's patients do not wait longer: thirty-one days from diagnosis to treatment, thirty-seven in Finland. Fewer are treated to cure. About twelve patients a year." |
| 0:30 | Scroll a little: **Is this gap real?** sits inside the top panel, under the dots. Point at the five answers left to right. | "Is the gap real? Not chance, not age, not just missing records. Stage at diagnosis is not published: an eight-week, eight-thousand-euro records audit settles it." |
| 0:45 | Scroll up to the dot chart, click **With the plan**. Pause one beat: each moved patient drops into "treated to cure" and 18.5 counts up to 22.2. | "Now switch on Kello's plan. Six actions, for two hundred and eleven thousand five hundred euros a year. By the model, five of those twelve patients are treated to cure. Forty-three percent of the gap." |
| 1:05 | Scroll to action 1, **Precise radiotherapy**. Point at the cost, **Then, the first step**, **Owner**. | "Each action is an order. Precise radiotherapy, for early cancer that cannot be operated: thirty thousand four hundred euros a year. First step: write the referral rule. Owner: the chief of oncology." |
| 1:25 | Point at the **Ask first** pill next to the title (this morning's finding). Then click **Check on the web**. The box "Checking now, through the Oxylabs Web API" appears. | "This is what this morning's check found. Now Kello checks again, live, through Oxylabs. It searches, reads the hospital's own pages, and quotes them." Talk over the rows as they arrive. |
| ~1:55 | The result: "Previous stored answer" and "New run" lines (or, if the answer changed, the boxes **Stored answer, 14 Nov** / **This run, 14 Nov**), then the OYS quote. Point at both, then the quote. | "This morning's check and the live run agree: Oulu University Hospital already offers it. Ask them first." |
| 2:10 | Tab 3 (Finnish plan, already written). Scroll to row 1, the web check note. Flick to tab 4 (English). | "That goes straight into the plan: one page, in English or Finnish, ready to send." |
| 2:25 | Tab 2. Scroll to the chart, click the source tag **p. 14**. Point at the quoted row. | "Every number opens its source. Gemini read nine hundred and sixty-six registry values, each with its page and quote." |
| 2:40 | Close the drawer. Scroll to the bottom: **The ask** block. Point at about 71, 64, Vantaa and Kerava, then 18.5% → 20.5%. | "We ask for a six-month pilot of two actions: a chest surgeon reviews every decision not to operate, and those who cannot be operated get radiotherapy. In six months that is about seventy-one patients and sixty-four decisions reviewed. The goal: from eighteen and a half to twenty and a half percent treated to cure, by 2028." |

Say "twenty and a half" for the pilot. 22.2% is the full six-action plan, not the pilot.

**If the web check is slow (still running after 30 s)**
Say: "It usually takes about twenty-five seconds. The answer it stored this morning is already on the card." Point at
the **Ask first** line from this morning and go on to tab 3. Do not wait longer than 35 s. Do not open or reload a plan
tab while the check runs.

**If the check fails or the network is down**
The stored answer stays on the card as the **Ask first** pill (click it to open the finding). Say "This is
this morning's check" and go on.

**If a plan tab shows the grey skeleton**
It is rewriting after the check (40–55 s). Stay on tab 2 and show the card's first step and owner instead: "The
plan is written from exactly these lines."

**Known rough edges (do not click into them on stage)**
- The plan page shows the pilot block twice, and the study list repeats the action cards: stay at the top and row 1.
- The check result says "Previous stored answer: mixed" while the pill says "Partly in place · Ask first": say "same answer" and point at the quote.
- "OYS" (Oulu University Hospital) and "Lapha" (Lapland's wellbeing services county) are not explained on screen: say
  the full names.
