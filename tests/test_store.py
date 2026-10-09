"""The database imports: sheet workbook -> sheet_row/sheet_change, Steam -> steam_*, title matching."""

import io
import json
import unittest
import zipfile
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from harbinger import load_config, sheet, steam, store, titles
from harbinger.build import assemble

from .test_build import CFG, FORECAST, TABS, TODAY, row


def xlsx(sheets: dict[str, dict[int, dict[str, object]]]) -> bytes:
    """A minimal workbook: {tab: {row: {col: value}}}, strings inline, numbers as numbers."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        names = list(sheets)
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
                   "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1)) +
                   "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", "<Relationships>" + "".join(
            f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1)) +
                   "</Relationships>")
        for i, n in enumerate(names, 1):
            rows = []
            for r, cells in sorted(sheets[n].items()):
                cs = "".join(f'<c r="{c}{r}"><v>{v}</v></c>' if isinstance(v, (int, float)) else
                             f'<c r="{c}{r}" t="inlineStr"><is><t>{escape(v)}</t></is></c>' for c, v in cells.items())
                rows.append(f'<row r="{r}">{cs}</row>')
            z.writestr(f"xl/worksheets/sheet{i}.xml",
                       '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                       + "".join(rows) + "</sheetData></worksheet>")
    return buf.getvalue()


def header(spec: sheet.Tab) -> dict[int, dict[str, str]]:
    rows = {spec.header_row: {c: want for c, _, want in spec.columns}}
    if spec.groups:
        rows.setdefault(1, {}).update(spec.groups)
    return rows


def workbook(master_rows: dict[int, dict[str, object]], **tweak) -> bytes:
    sheets = {spec.sheet: header(spec) for spec in sheet.TABS.values()}
    sheets["Master List"].update(master_rows)
    for name, rows in tweak.items():
        sheets[name].update(rows)
    return xlsx(sheets)


OCT_21_2025 = 45951  # Excel serial
MASTER = {
    3: {"A": "Pacific Drive", "B": "Xbox / PC", "D": "Active", "E": OCT_21_2025, "G": 11.6, "K": 20},
    4: {"A": "Conker", "B": "Xbox", "D": "Active", "E": 46000, "G": 9.9, "K": 8},
    5: {"A": "Conker", "B": "Xbox", "D": "Removed", "E": 43000, "F": 44000, "G": 30.0, "K": 8},
}


def db():
    return store.connect(Path(":memory:"))


class SheetImport(unittest.TestCase):
    def test_reads_types_dates_and_stints(self):
        tabs = sheet.extract(sheet.read_xlsx(workbook(MASTER), {t.sheet for t in sheet.TABS.values()}))
        pd = [r for r in tabs["master"] if r["title"] == "Pacific Drive"][0]
        self.assertEqual(pd["added"], "2025-10-21")
        self.assertEqual(pd["completion_h"], 20)
        conker = sorted((r["stint"], r["status"]) for r in tabs["master"] if r["key"] == "conker")
        self.assertEqual(conker, [(1, "Removed"), (2, "Active")])

    def test_moved_column_fails_loudly(self):
        bad = workbook(MASTER, **{"Master List": {2: {**header(sheet.TABS["master"])[2], "K": "Genre"}}})
        with self.assertRaises(sheet.SheetLayoutError):
            sheet.extract(sheet.read_xlsx(bad, {t.sheet for t in sheet.TABS.values()}))

    def test_month_only_text_dates(self):
        self.assertEqual(sheet._date("June 2026"), "2026-06")
        self.assertEqual(sheet._date("10/1/25"), "2025-10-01")
        self.assertEqual(sheet._date("TBA"), "TBA")

    def test_change_log(self):
        d = db()
        wanted = {t.sheet for t in sheet.TABS.values()}
        first = sheet.extract(sheet.read_xlsx(workbook(MASTER), wanted))
        self.assertIn("baseline", sheet.import_rows(d, first, "2026-10-03T08:46:00"))
        later = dict(MASTER)
        later[3] = {**MASTER[3], "D": "Leaving Soon", "G": 12.1}          # status flips, months ticks on
        del later[4]                                                     # second Conker stint vanishes
        later[6] = {"A": "New Game", "B": "Xbox", "D": "Active", "E": 46300, "G": 0.2}
        sheet.import_rows(d, sheet.extract(sheet.read_xlsx(workbook(later), wanted)), "2026-10-18T08:46:00")
        got = {(t, k, f, o, n) for t, k, f, o, n in d.execute(
            "SELECT title, kind, field, old, new FROM sheet_change WHERE tab = 'master'")}
        self.assertEqual(got, {("Pacific Drive", "changed", "status", "Active", "Leaving Soon"),
                               ("Conker", "dropped", None, None, None),
                               ("New Game", "added", None, None, None)})
        s = sheet.load(d, CFG)
        self.assertEqual(s.fetched, "2026-10-18T08:46:00")
        self.assertEqual({g.name for g in s.games}, {"Pacific Drive", "Conker", "New Game"})


def owned(appid, name, minutes):
    return {"appid": appid, "name": name, "playtime_forever": minutes, "rtime_last_played": 1760000000}


class SteamImport(unittest.TestCase):
    def test_history_only_when_something_moves(self):
        d = db()
        ach = [{"apiname": "A", "achieved": 1, "unlocktime": 1760000000}, {"apiname": "B", "achieved": 0}]
        steam.save(d, {"owned": [owned(1, "Evil West", 60), owned(2, "DREDGE", 0)], "achievements": {1: ach}},
                   "2026-10-09T06:30:00")
        steam.save(d, {"owned": [owned(1, "Evil West", 120)], "achievements": {}}, "2026-10-10T06:30:00")
        hist = d.execute("SELECT sync_id, appid, playtime_min, ach_done FROM steam_history ORDER BY sync_id, appid")
        self.assertEqual(hist.fetchall(), [(1, 1, 60, 1), (1, 2, 0, None), (2, 1, 120, 1)])
        lib = steam.load(d)
        self.assertEqual(lib["synced_at"], "2026-10-10T06:30:00")
        self.assertEqual(lib["games"]["evil west"],  # achievements kept from the earlier fetch
                         {"name": "Evil West", "appid": 1, "played_h": 2.0, "ach_done": 1, "ach_total": 2})
        self.assertNotIn("dredge", lib["games"])  # dropped out of the library
        self.assertEqual(d.execute("SELECT owned FROM steam_game WHERE appid = 2").fetchone(), (0,))


class Titles(unittest.TestCase):
    KEYS = {"hades", "doom 1993", "doom eternal", "forza horizon 5", "sopa tale of the stolen potato"}

    def test_rungs_and_corrections(self):
        m = titles.Matcher(self.KEYS, {"same": {"DOOM": "DOOM (1993)"}, "different": {"Hades II": ["Hades"]}})
        self.assertEqual(m.match("HADES"), ("hades", "exact"))
        self.assertEqual(m.match("Forza Horizon 5 Premium Edition"), ("forza horizon 5", "edition"))
        self.assertEqual(m.match("Forza Horizon 5 Hot Wheels"), (None, "none"))
        self.assertEqual(m.match("Hades: Definitive Edition"), ("hades", "edition"))
        self.assertEqual(m.match("DOOM"), ("doom 1993", "alias"))
        self.assertEqual(m.match("Sopa"), ("sopa tale of the stolen potato", "prefix"))
        self.assertEqual(m.near("Hades II"), [])  # settled as a different game
        self.assertEqual(m.near("Forza Horizon 5 Hot Wheels")[0][0], "forza horizon 5")

    def test_reconcile_records_and_reports(self):
        d = db()
        steam.save(d, {"owned": [owned(10, "Pacific Drive", 30), owned(11, "Evil Wesst", 0),
                                 owned(12, "Half-Life", 0)], "achievements": {}}, "2026-10-09T06:30:00")
        cfg = dict(CFG, queue={"tracking": ["Not A Real Game"], "gone": []})
        titles.reconcile(d, sheet.parse(TABS, "2026-10-09T08:46:00"), FORECAST, cfg)
        r = titles.report(d)
        self.assertEqual([i["title"] for i in r["near"]], ["Evil Wesst"])
        self.assertEqual([i["title"] for i in r["unmatched"]], ["Not A Real Game"])
        self.assertEqual(r["counts"]["steam->xbox"], (3, 1))


class Matching(unittest.TestCase):
    """Rules learned from the first real Steam import (1,307 games, 2026-10-09)."""

    def test_trademarks_accents_apostrophes_and_roman_numerals(self):
        self.assertEqual(sheet.norm("Batman™: Arkham Knight"), sheet.norm("Batman: Arkham Knight"))
        self.assertEqual(sheet.norm("Mørkredd"), "morkredd")
        self.assertEqual(sheet.norm("Spacer’s Choice"), sheet.norm("Spacer's Choice"))
        self.assertEqual(sheet.norm("Chivalry II"), sheet.norm("Chivalry 2"))

    def test_sequels_never_match_or_suggest(self):
        keys = {"sniper elite 4", "portal 2", "q u b e 2", "orwell keeping an eye on you"}
        m = titles.Matcher(keys)
        self.assertEqual(m.match("Q.U.B.E."), (None, "none"))       # prefix rung skips a sequel number
        self.assertEqual(m.match("Orwell")[1], "prefix")
        self.assertEqual(m.near("Sniper Elite 3"), [])
        self.assertEqual(m.near("Portal"), [])

    def test_steam_is_strict(self):
        m = titles.Matcher({"prince of persia the lost crown"})
        self.assertEqual(m.match("Prince of Persia")[1], "prefix")
        self.assertEqual(m.match("Prince of Persia", loose=False), (None, "none"))

    def test_typos_and_bundles(self):
        m = titles.Matcher({"mechwarrior 5 clans", "heroes 2", "heroes 3"}, {"same": {"Heroes 2 & 3": ["Heroes II", "Heroes III"]}})
        self.assertEqual(m.match("MechWarriror 5: Clans"), ("mechwarrior 5 clans", "fuzzy"))
        self.assertEqual(m.match_all("Heroes 2 & 3"), (["heroes 2", "heroes 3"], "alias"))

    def test_tools_are_not_games(self):
        d = db()
        steam.save(d, {"owned": [owned(20, "Fallout 76 Public Test Server", 0)], "achievements": {}}, "2026-10-09")
        tabs = dict(TABS, master=TABS["master"] + [row("Fallout 76", "Active", "Jan 2026", 9, 100)])
        titles.reconcile(d, sheet.parse(tabs, "2026-10-09T08:46:00"), FORECAST, CFG)
        self.assertEqual(d.execute("SELECT method, candidates FROM title_match WHERE source = 'steam'").fetchone(),
                         ("not a game", None))


class ConsoleScope(unittest.TestCase):
    def setUp(self):

        self.tabs = {t: [dict(r, system="PC") if r["title"].startswith("Nova Roma") else r for r in rows]
                     for t, rows in TABS.items()}
        self.tabs["master"] = self.tabs["master"] + [
            dict(row("Only On PC", "Active", "Nov 2025", 11.2, 10), system="PC"),
            dict(row("Both Ways", "Removed", "Jan 2023", 12.0, 10, removed="Jan 2024"), system="PC"),
            row("Both Ways", "Active", "Nov 2025", 11.2, 10)]
        self.sheet = sheet.parse(self.tabs, "2026-10-09T08:46:00", ["PC"])

    def test_pc_only_rows_leave_the_model(self):
        self.assertEqual(self.sheet.out_of_scope, {"nova roma", "only on pc"})
        self.assertIn("both ways", {g.key for g in self.sheet.games})
        cfg = dict(CFG, queue={"tracking": ["Only On PC"], "gone": []})
        fc = dict(FORECAST, confirmed=[{"game": "Only On PC", "wave": "2026-10-31", "source": "Xbox Wire"}])
        d = assemble(cfg, self.sheet, fc, {"games": {}}, TODAY, TODAY)
        self.assertEqual(d["summary"]["confirmed_count"], 7)  # Nova Roma is PC Game Pass only
        self.assertNotIn("Only On PC", [r["game"] for r in d["confirmed"] + d["watchlist"]])
        self.assertEqual(d["queue"][0]["state"], "PC only")

    def test_a_pc_only_title_never_lands_on_a_lookalike(self):
        m = titles.Matcher({"only on pc 2"}, None, {"only on pc"})
        self.assertEqual(m.match("Only On PC"), (None, "pc only"))


class Stints(unittest.TestCase):
    def test_back_on_the_service_is_not_gone(self):
        tabs = dict(TABS, master=TABS["master"] + [
            row("Comeback Game", "Active", "Mar 2026", 7.2, 10),
            row("Comeback Game", "Removed", "Jan 2023", 12.0, 10, removed="Jan 2024")])
        cfg = dict(CFG, queue={"tracking": ["Comeback Game"], "gone": []})
        d = assemble(cfg, sheet.parse(tabs, "2026-10-09T08:46:00"), FORECAST, {"games": {}}, TODAY, TODAY)
        q = {r["game"]: r for r in d["queue"]}
        self.assertEqual(q["Comeback Game"]["state"], "Active")


class TitlesFile(unittest.TestCase):
    def test_shared_corrections_load(self):
        cfg = load_config(local=None)
        self.assertIn("same", cfg["titles"])
        self.assertIn("different", cfg["titles"])


if __name__ == "__main__":
    unittest.main()
