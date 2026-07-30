#!/usr/bin/env python3
"""Generate AlgoCore AFP Schedule -- compact, no text wrapping in cells."""

from fpdf import FPDF

STUDENT = {
    "name": "_________________________",
    "regno": "_________________________",
    "programme": "_________________________",
    "year": "III Year / V Semester",
    "academic_year": "2026-27",
}

PROJECT_CONTEXT = (
    "AlgoCore - A faculty-led AI-powered coding assessment and adaptive feedback platform "
    "for educational institutions. I am building four major feature modules to upgrade the "
    "platform for the upcoming academic year.\n"
    "A. Skill Dashboard & Gamification - Activity heatmap, streaks, XP/Level system, radar "
    "chart, badges, and leaderboards for student growth visibility.\n"
    "B. Smart Practice Engine - Adaptive 'Recommended for You' problems based on mastery gaps, "
    "with streak-aware difficulty adjustment and teacher-override.\n"
    "C. AI Analysis Button - Post-submission analysis via Groq/Llama 3.1 returning approach, "
    "style, and efficiency feedback (never code). Future: user-supplied Gemini API key.\n"
    "D. Proctoring Model Fine-tune - Faster gadget detection in TensorFlow.js COCO-SSD via "
    "every-frame capture, motion-diff detection, lower thresholds, and sliding-window memory."
)

MONTHS = ["July 2026", "Aug 2026", "Sep 2026", "Oct 2026", "Nov 2026", "Dec 2026"]

WS_SHORT = ["Dashboard &\nGamification", "Smart Practice\nEngine", "AI Analysis\nButton", "Proctoring\nFine-tune"]

# Each bullet MUST fit on ONE line at 6pt in ~62mm cell
DATA = [
    # July
    [
        "XP/Level/streak data model",
        "Activity heatmap (GitHub grid)",
        "Streak counter (>=1 prob/day)",
    ], [
        "Adaptive recommendation research",
        "Map mastery data to skill graph",
        "'For You' component design",
    ], [
        "Study Groq integration code",
        "Design Analysis prompt",
        "Build Analysis button UI on results",
    ], [
        "Audit proctoring + COCO-SSD",
        "Every-frame capture impl",
        "Frame-diff motion detection",
    ],
    # August
    [
        "XP/Level progression system",
        "Radar chart (multi-skill)",
        "Sync XP/streaks to Firebase",
    ], [
        "Mastery-gap recommendation algo",
        "'For You' card component",
        "Connect to course progress data",
    ], [
        "Wire Analysis to Groq endpoint",
        "Results panel (markdown render)",
        "Enforce no-code/no-answer prompt",
    ], [
        "IoU tracking between frames",
        "Lower gadget class thresholds",
        "Frame-buffer sliding window",
    ],
    # September
    [
        "Milestone badge system design",
        "Leaderboards (daily/weekly/all)",
        "Topic filter on dashboard",
    ], [
        "Quick Practice mode (3/5/10)",
        "Streak-aware difficulty adjust",
        "Connect to exam result history",
    ], [
        "Polish Analysis results panel",
        "Edge: empty subs, timeouts",
        "Loading states + error handling",
    ], [
        "Motion detection -> violations",
        "Flag 'possible gadget detected'",
        "False-positive rate testing",
    ],
    # October
    [
        "Gamification loop: XP/level/badge",
        "Confetti on streak milestones",
        "Dark mode compatibility pass",
    ], [
        "Teacher-override recommend",
        "Skip/dismiss for recs",
        "Empty-state handling polish",
    ], [
        "Analysis -> submission pipeline",
        "Store analysis history in Firebase",
        "Test with real student subs",
    ], [
        "Gadget-detection violation type",
        "Log confidence + bounding box",
        "Real webcam movement testing",
    ],
    # November
    [
        "Beta test (10-15 users)",
        "Tweak XP rates + thresholds",
        "Edge: timezone, streak reset",
    ], [
        "Beta test with pilot group",
        "Tune algo from engagement data",
        "Edge: new user, zero history",
    ], [
        "Beta test Analysis with pilot",
        "Refine prompt from feedback",
        "Prep Gemini API key settings",
    ], [
        "Threshold tuning gadget vs norm",
        "Test different lighting/angles",
        "Document accuracy metrics",
    ],
    # December
    [
        "Production launch",
        "Admin docs + handover",
        "Knowledge transfer to team",
    ], [
        "Production launch",
        "Integration docs",
        "Handover algo documentation",
    ], [
        "Production launch",
        "Prompt templates + Groq docs",
        "Handover Gemini key guide",
    ], [
        "Production launch",
        "Detection pipeline docs",
        "Handover dataset + benchmarks",
    ],
]


class AFP_PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 9, "ACADEMIC FLEXIBILITY PLAN (AFP)", new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_font("Helvetica", "I", 10)
        self.cell(0, 6, "Under Learner Autonomy (LA) Policy - Odd Semester 2026-27", new_x="LMARGIN", new_y="NEXT", align="C")
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 8, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title):
        self.set_font("Helvetica", "B", 11)
        self.set_fill_color(220, 220, 220)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT", fill=True)
        self.ln(1.5)

    def student_details(self):
        self.section_title("STUDENT DETAILS")
        self.set_font("Helvetica", "", 10)
        for label, val in [("Name of the Student", STUDENT["name"]),
                           ("Register Number", STUDENT["regno"]),
                           ("Programme", STUDENT["programme"]),
                           ("Year / Semester", STUDENT["year"]),
                           ("Academic Year", STUDENT["academic_year"])]:
            self.set_font("Helvetica", "B", 10)
            self.cell(46, 5.5, f"{label}  :")
            self.set_font("Helvetica", "", 10)
            self.cell(0, 5.5, val, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def project_context(self):
        self.section_title("PROJECT CONTEXT")
        self.set_font("Helvetica", "", 9)
        self.multi_cell(0, 4.8, PROJECT_CONTEXT)
        self.ln(2)


    def month_table(self):
        self.section_title("MONTH-WISE SCHEDULE (July - December 2026)")
        self.set_font("Helvetica", "I", 8.5)
        self.cell(0, 5, "Total: ~26 hrs/week across the four workstreams (~6-7 hrs/week each).",
                  new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)

        lm = self.l_margin
        body = 277
        cm = 16
        ch = 11
        cw = int((body - cm - ch) / 4)
        cw = 63
        ch = 11
        cm = 16

        cols = [cm, cw, cw, cw, cw, ch]
        headers = ["Month"] + WS_SHORT + ["Hrs\n/Wk"]

        hh = 8
        rh = 11

        def draw_header(y):
            self.set_font("Helvetica", "B", 7.5)
            self.set_fill_color(200, 200, 200)
            self.set_draw_color(50, 50, 50)
            x0 = lm
            for i, h in enumerate(headers):
                x = x0 + sum(cols[:i])
                self.rect(x, y, cols[i], hh)
                self.set_xy(x + 0.3, y + 0.3)
                self.multi_cell(cols[i] - 0.6, 3.2, h, align="C")
            return y + hh

        def draw_ws_cell(x, y, w, h, bullets):
            self.set_draw_color(50, 50, 50)
            self.rect(x, y, w, h)
            self.set_font("Helvetica", "", 6)
            lh = 3.2
            for i, b in enumerate(bullets):
                txt = f"- {b}"
                self.set_xy(x + 0.25, y + 0.4 + i * lh)
                self.cell(w - 0.5, lh, txt)

        cy = draw_header(self.get_y())

        for midx in range(6):
            y0 = cy
            if y0 + rh > 285:
                self.add_page()
                cy = draw_header(self.get_y())
                y0 = cy

            self.set_draw_color(50, 50, 50)
            self.set_font("Helvetica", "B", 7)
            self.rect(lm, y0, cm, rh)
            self.set_xy(lm + 0.2, y0 + (rh - 3.5) / 2)
            self.cell(cm - 0.4, 3.5, MONTHS[midx], align="C")

            base = midx * 4
            for ws in range(4):
                x = lm + sum(cols[:ws + 1])
                draw_ws_cell(x, y0, cols[ws + 1], rh, DATA[base + ws])

            xh = lm + sum(cols[:5])
            self.set_draw_color(50, 50, 50)
            self.set_font("Helvetica", "B", 7.5)
            self.rect(xh, y0, ch, rh)
            self.set_xy(xh, y0 + (rh - 4) / 2)
            self.cell(ch, 4, "26", align="C")

            cy = y0 + rh

        self.set_xy(lm, cy + 3)


    def expected_outcomes(self):
        self.section_title("EXPECTED OUTCOMES")
        self.set_font("Helvetica", "", 9)
        outcomes = [
            "A. Skill Dashboard & Gamification - Activity heatmap, XP/Level system, streaks, radar chart, badges, and leaderboards live in production.",
            "B. Smart Practice Engine - Adaptive recommendation system serving targeted problems based on mastery gaps, with streak-aware difficulty and teacher-override.",
            "C. AI Analysis Button - Post-submission analysis using Groq/Llama 3.1 providing approach, style, and efficiency feedback (never code).",
            "D. Proctoring Model Fine-tune - Improved gadget detection catches fast movements via every-frame capture, motion detection, and sliding-window tracking.",
            "Handover documentation and knowledge-transfer complete for all four workstreams.",
        ]
        for o in outcomes:
            self.multi_cell(0, 5, f"  {o}")
            self.ln(0.3)
        self.ln(2)

    def declaration(self):
        self.section_title("DECLARATION")
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 5.5, "I hereby declare that the above schedule is my proposed enrichment plan under the Learner Autonomy Policy. I will adhere to the timeline and deliverables mentioned above and submit progress reports as required.")
        self.ln(10)
        self.cell(60, 7, "__________________________")
        self.cell(75)
        self.cell(60, 7, "__________________________", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "B", 10)
        self.cell(60, 7, "Signature of the Student")
        self.cell(75)
        self.cell(60, 7, "Signature of the Mentor / Supervisor", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)
        self.cell(60, 6, "Date: _______________")
        self.cell(75)
        self.cell(60, 6, "Date: _______________")


pdf = AFP_PDF(orientation="L", format="A4")
pdf.alias_nb_pages()
pdf.set_auto_page_break(auto=True, margin=10)
pdf.set_margins(10, 8, 10)
pdf.add_page()

pdf.student_details()
pdf.project_context()
pdf.month_table()
pdf.expected_outcomes()
pdf.declaration()

out = r"C:\Users\vamsi\Desktop\Namma-Agent\data\uploads\AlgoCore_AFP_Schedule_Jul-Dec_2026.pdf"
pdf.output(out)
print(f"Done: {out}")
print(f"Pages: {pdf.page_no()}")
