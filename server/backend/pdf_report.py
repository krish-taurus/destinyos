"""The downloadable PDF of a person's report: numbers, HALIA snapshot, the written chapters and, when bought,
the three-year report. Built with fpdf2 from data already saved; no model call and nothing new is calculated."""
from __future__ import annotations
from datetime import date, datetime
from pathlib import Path

from fpdf import FPDF

FONTS = Path(__file__).parent / "fonts"
INK, DIM, GOLD, GOLD_2, STONE, IVORY, PALE, RED = (26, 18, 8), (107, 98, 82), (150, 106, 22), (201, 152, 62), (13, 10, 7), (243, 233, 214), (246, 241, 230), (200, 68, 43)
M, W = 18, 210 - 36          # margin and text width, mm
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
NOTE = ("Numbers, chart positions and Dasha periods are calculated from your birth details. What they mean is a matter of tradition, "
        "offered for reflection and not as a prediction. HALIA uses only the answers you gave about your life today. "
        "Nothing here replaces medical, legal, financial or mental-health advice.")


class Doc(FPDF):
    def __init__(self, who: str):
        super().__init__(format="A4", unit="mm")
        self.who = who
        self.set_margins(M, M, M)
        self.set_auto_page_break(True, 22)
        self.add_font("Sans", "", str(FONTS / "NotoSans-Regular.ttf"))
        self.add_font("Sans", "B", str(FONTS / "NotoSans-Bold.ttf"))
        self.add_font("Serif", "B", str(FONTS / "NotoSerif-Bold.ttf"))
        self.add_font("Deva", "", str(FONTS / "NotoSansDevanagari-Regular.ttf"))
        self.add_font("Deva", "B", str(FONTS / "NotoSansDevanagari-Bold.ttf"))
        self.set_fallback_fonts(["Deva"], exact_match=False)
        self.set_text_shaping(True)
        self.set_title(f"Destiny OS report: {who}")
        self.set_author("Destiny OS")

    def footer(self):
        self.set_y(-14)
        self.set_font("Sans", "", 7.5)
        self.set_text_color(*DIM)
        self.cell(W / 2, 5, f"Destiny OS  ·  {self.who}  ·  destinyos.in")
        self.cell(W / 2, 5, str(self.page_no()), align="R")

    # ── building blocks ──
    def room(self, h: float):
        if self.get_y() + h > 297 - 22:
            self.add_page()

    def h2(self, text: str):
        self.room(26)
        self.ln(5)
        self.set_draw_color(*GOLD_2); self.set_line_width(.5)
        self.line(M, self.get_y(), M + 14, self.get_y())
        self.ln(3)
        self.set_font("Serif", "B", 17); self.set_text_color(*INK)
        self.multi_cell(W, 7.6, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)

    def h3(self, text: str, colour=GOLD):
        self.room(16)
        self.ln(2)
        self.set_font("Serif", "B", 12.5); self.set_text_color(*colour)
        self.multi_cell(W, 6, text, new_x="LMARGIN", new_y="NEXT")

    def para(self, text: str, size: float = 10.5, colour=INK, w: float = W, lh: float = 5.7):
        self.set_font("Sans", "", size); self.set_text_color(*colour)
        self.multi_cell(w, lh, str(text or "").strip(), new_x="LMARGIN", new_y="NEXT")
        self.ln(1.6)

    def body(self, text: str):
        """Paragraphs, or a list when every line is a bullet or a 'Month YYYY:' line."""
        lines = [l.strip() for l in str(text or "").split("\n") if l.strip()]
        if len(lines) > 1:
            for l in lines:
                self.bullet(l.lstrip("•- ").strip())
            self.ln(1)
        else:
            for l in lines:
                self.para(l.lstrip("• ").strip())

    def bullet(self, text: str, mark: str | None = None):
        self.room(8)
        y = self.get_y()
        if mark:
            self.set_font("Serif", "B", 13); self.set_text_color(*GOLD)
            self.set_xy(M, y - .6); self.cell(8, 6, mark)
        else:
            self.set_fill_color(*GOLD_2)
            self.rect(M + 1.2, y + 2, 1.7, 1.7, style="F")
        self.set_xy(M + 8, y)
        self.set_font("Sans", "", 10.5); self.set_text_color(*INK)
        self.multi_cell(W - 8, 5.7, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(1.2)

    def box(self, title: str, text: str, x: float, w: float, y: float) -> float:
        """A pale panel; returns its bottom edge."""
        self.set_xy(x + 4, y + 3.5)
        self.set_font("Serif", "B", 11); self.set_text_color(*GOLD)
        self.cell(w - 8, 5.5, title)
        self.set_xy(x + 4, y + 9.5)
        self.set_font("Sans", "", 9.5); self.set_text_color(*INK)
        self.multi_cell(w - 8, 5, str(text or ""), new_x="LMARGIN", new_y="NEXT")
        return self.get_y() + 3.5


def _day(iso: str, back: int = 0) -> str:
    d = date.fromordinal(date.fromisoformat(iso).toordinal() - back)
    return f"{d.day} {MON[d.month - 1]}"


def build(user: dict, core: dict, snap: dict | None, three: dict | None) -> bytes:
    first = user["name"].split()[0]
    pdf = Doc(user["name"])
    pdf.add_page()

    # ── cover band ──
    pdf.set_fill_color(*STONE); pdf.rect(0, 0, 210, 86, style="F")
    pdf.set_fill_color(*GOLD_2); pdf.rect(0, 86, 210, 1.2, style="F")
    pdf.set_xy(M, 15); pdf.set_font("Serif", "B", 10); pdf.set_text_color(*GOLD_2)
    pdf.cell(W, 5, "D E S T I N Y   O S")
    pdf.set_xy(M, 30); pdf.set_font("Serif", "B", 34); pdf.set_text_color(*IVORY)
    pdf.multi_cell(W, 13.5, user["name"], new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(M); pdf.set_font("Serif", "B", 14); pdf.set_text_color(*GOLD_2)
    pdf.multi_cell(W, 7, core.get("headline") or "", new_x="LMARGIN", new_y="NEXT")
    born = f"Born {user['dob']}" + (f", {user['birth_time']}" if user.get("birth_time") else "") + f", {user['city']}"
    made = datetime.fromtimestamp(core["created_at"]).strftime("%-d %b %Y") if core.get("created_at") else date.today().strftime("%-d %b %Y")
    pdf.set_xy(M, 76); pdf.set_font("Sans", "", 9); pdf.set_text_color(200, 190, 170)
    pdf.cell(W, 5, f"{born}   ·   Report written {made}")

    # ── numbers ──
    n = (core.get("numbers") or {}).get("pythagorean") or {}
    y = 95
    pdf.set_fill_color(*PALE); pdf.rect(M, y, 52, 46, style="F")
    pdf.set_draw_color(*GOLD_2); pdf.set_line_width(.5); pdf.rect(M, y, 52, 46)
    pdf.set_xy(M, y + 5); pdf.set_font("Serif", "B", 58); pdf.set_text_color(*GOLD)
    pdf.cell(52, 24, str(n.get("lifePath", "")), align="C")
    pdf.set_xy(M, y + 34); pdf.set_font("Serif", "B", 12); pdf.set_text_color(*INK)
    pdf.cell(52, 6, "Life Path", align="C")
    tiles = [("Birth number", n.get("birthNumber")), ("Expression", n.get("expression")), ("Soul urge", n.get("soulUrge")), ("Personal year", n.get("personalYear"))]
    tw = (W - 52 - 4 - 4) / 2
    for i, (label, v) in enumerate(tiles):
        x, ty = M + 56 + (i % 2) * (tw + 4), y + (i // 2) * 24.5
        pdf.set_draw_color(214, 204, 184); pdf.set_line_width(.3); pdf.rect(x, ty, tw, 21.5)
        pdf.set_xy(x + 4, ty + 2.5); pdf.set_font("Serif", "B", 24); pdf.set_text_color(*GOLD)
        pdf.cell(20, 11, str(v if v is not None else ""))
        pdf.set_xy(x + 4, ty + 13.5); pdf.set_font("Sans", "", 9); pdf.set_text_color(*DIM)
        pdf.cell(tw - 8, 5, label)
    pdf.set_y(y + 50)

    # ── HALIA snapshot ──
    if snap and snap.get("answered"):
        pdf.h2("Where you stand today")
        why = (f"You chose to work on {snap['focus_name'].lower()} first." if snap.get("chosen")
               else f"{snap['focus_name']} is your lowest area right now, so HALIA starts there.")
        pdf.para(why)
        for l in snap["levels"]:
            yy = pdf.get_y()
            pdf.set_font("Sans", "B" if l["pillar"] == snap["lowest"] else "", 10); pdf.set_text_color(*INK)
            pdf.set_xy(M, yy); pdf.cell(36, 6, l["name"])
            pdf.set_fill_color(232, 224, 208); pdf.rect(M + 38, yy + 1.6, 90, 3, style="F")
            if l["value"]:
                pdf.set_fill_color(*(RED if l["pillar"] == snap["lowest"] else GOLD_2)); pdf.rect(M + 38, yy + 1.6, 18 * l["value"], 3, style="F")
            pdf.set_xy(M + 132, yy); pdf.set_font("Sans", "", 9.5); pdf.set_text_color(*DIM); pdf.cell(40, 6, l["label"] or "Not answered")
            pdf.set_y(yy + 7)
        pdf.ln(2); pdf.room(26)
        yy = pdf.get_y()
        pdf.set_fill_color(*PALE)
        pdf.set_font("Sans", "", 9.5)
        bottom = None
        pdf.rect(M, yy, W, 22, style="F"); pdf.set_fill_color(*GOLD_2); pdf.rect(M, yy, 1.2, 22, style="F")
        pdf.set_xy(M + 5, yy + 3); pdf.set_text_color(*DIM); pdf.cell(W - 10, 5, f"One step for today, about {snap['minutes']} minutes")
        pdf.set_xy(M + 5, yy + 9); pdf.set_font("Serif", "B", 12); pdf.set_text_color(*INK)
        pdf.multi_cell(W - 10, 5.8, snap["step"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_y(max(pdf.get_y(), yy + 22) + 3)
        pdf.para(snap["note"], 8.5, DIM, lh=4.6)

    # ── three-year report ──
    if three and three.get("years"):
        y0 = three["years"][0]["year"]
        pdf.add_page()
        pdf.set_font("Serif", "B", 30); pdf.set_text_color(*INK)
        pdf.cell(W, 14, f"{y0} to {y0 + 2}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Serif", "B", 13); pdf.set_text_color(*GOLD)
        pdf.multi_cell(W, 6.5, three.get("headline") or "", new_x="LMARGIN", new_y="NEXT"); pdf.ln(2)
        pdf.h3("Where you stand today"); pdf.para(three.get("where_you_stand"))
        cal = {c["year"]: c for c in three.get("calendar") or []}
        for yr in three["years"]:
            c = cal.get(yr["year"], {"dasha": []})
            pdf.add_page()
            pdf.set_font("Serif", "B", 56); pdf.set_text_color(*GOLD)
            pdf.cell(70, 22, str(yr["year"]))
            x, yy = pdf.get_x(), pdf.get_y()
            pdf.set_xy(x, yy + 3); pdf.set_font("Serif", "B", 16); pdf.set_text_color(*INK)
            pdf.multi_cell(W - 70, 7, str(yr.get("theme") or ""), new_x="LEFT", new_y="NEXT")
            pdf.set_x(x); pdf.set_font("Sans", "", 9.5); pdf.set_text_color(*DIM)
            pdf.cell(W - 70, 5, f"Personal Year {c.get('personal_year', '')}")
            pdf.set_y(max(pdf.get_y() + 8, yy + 26))
            if c["dasha"]:
                total = sum((date.fromisoformat(d["end"]) - date.fromisoformat(d["start"])).days for d in c["dasha"]) or 1
                sx, sy = M, pdf.get_y()
                for i, d in enumerate(c["dasha"]):
                    w = W * (date.fromisoformat(d["end"]) - date.fromisoformat(d["start"])).days / total
                    pdf.set_fill_color(*(GOLD_2 if i % 2 == 0 else (176, 134, 60))); pdf.rect(sx, sy, w, 8, style="F")
                    if w > 22:
                        pdf.set_xy(sx, sy + 1.4); pdf.set_font("Sans", "B", 8); pdf.set_text_color(*INK); pdf.cell(w, 5, d["antar"], align="C")
                    sx += w
                pdf.set_xy(M, sy + 9); pdf.set_font("Sans", "", 7.5); pdf.set_text_color(*DIM)
                pdf.cell(W / 2, 4, "January"); pdf.cell(W / 2, 4, "December", align="R")
                pdf.set_xy(M, sy + 14)
                pdf.para("   ·   ".join(f"{d['maha']}–{d['antar']} {_day(d['start'])} to {_day(d['end'], 1)}" for d in c["dasha"]), 8.5, DIM, lh=4.6)
            pdf.body(yr.get("overview"))
            for title, key in (("Work and money", "work_money"), ("Relationships", "relationships"), ("Energy and habits", "energy_habits")):
                pdf.h3(title); pdf.para(yr.get(key))
            pdf.room(34)
            yy, half = pdf.get_y() + 1, (W - 4) / 2
            pdf.set_fill_color(*PALE)
            # measure by drawing: panels sized to the longer text
            hgt = 12 + 5 * max(len(pdf.multi_cell(half - 8, 5, str(yr.get(k) or ""), dry_run=True, output="LINES")) for k in ("good_months", "go_slow"))
            pdf.rect(M, yy, half, hgt, style="F"); pdf.rect(M + half + 4, yy, half, hgt, style="F")
            pdf.box("Supportive months", yr.get("good_months"), M, half, yy)
            pdf.box("Go slowly", yr.get("go_slow"), M + half + 4, half, yy)
            pdf.set_y(yy + hgt + 3)
            pdf.h3(f"Three steps for {yr['year']}", INK)
            for i, a in enumerate(yr.get("actions") or [], 1):
                pdf.bullet(str(a), str(i))
        pdf.add_page()
        pdf.h2("What to build across three years"); pdf.body(three.get("three_year_plan")); pdf.para(three.get("closing"))
        if not three.get("halia_answers"):
            pdf.para("Written without HALIA answers, so the steps are general.", 9, DIM)

    # ── the written chapters ──
    open_, shut = [s for s in core["sections"] if not s["locked"]], [s for s in core["sections"] if s["locked"]]
    if three and three.get("years"):
        pdf.add_page()
    for s in open_:
        pdf.h2(s["title"]); pdf.body(s["body"])
    if shut:
        pdf.h2("Still to open")
        pdf.para("These chapters are written and open with the three-year report:", colour=DIM)
        for s in shut:
            pdf.bullet(s["title"])

    pdf.ln(4); pdf.room(24)
    pdf.set_draw_color(214, 204, 184); pdf.set_line_width(.3); pdf.line(M, pdf.get_y(), M + W, pdf.get_y()); pdf.ln(3)
    pdf.para(NOTE + "  How every number is calculated: destinyos.in/guide", 8.5, DIM, lh=4.6)
    return bytes(pdf.output())
